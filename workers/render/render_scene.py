from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector


def parse_arguments() -> argparse.Namespace:
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Render a styled floorplan GLB")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--style", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args(arguments)


def hex_color(value: str) -> tuple[float, float, float, float]:
    if len(value) != 7 or not value.startswith("#"):
        raise ValueError(f"invalid color: {value}")

    def linear(channel: int) -> float:
        srgb = channel / 255
        return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4

    return (
        linear(int(value[1:3], 16)),
        linear(int(value[3:5], 16)),
        linear(int(value[5:7], 16)),
        1,
    )


def load_style(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"id", "version", "materials", "environment", "camera", "output", "layout"}
    if not isinstance(value, dict) or not required.issubset(value):
        raise ValueError("style pack is invalid")
    return value


def create_material(name: str, value: dict[str, Any]) -> bpy.types.Material:
    material = bpy.data.materials.new(name=f"style-{name}")
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled is None:
        raise RuntimeError("Blender Principled BSDF node is unavailable")
    color = hex_color(value["baseColor"])
    principled.inputs["Base Color"].default_value = color
    principled.inputs["Metallic"].default_value = float(value["metallic"])
    principled.inputs["Roughness"].default_value = float(value["roughness"])
    material.diffuse_color = color
    return material


def mesh_bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    if not points:
        raise RuntimeError("GLB contains no renderable meshes")
    minimum = Vector(tuple(min(point[index] for point in points) for index in range(3)))
    maximum = Vector(tuple(max(point[index] for point in points) for index in range(3)))
    return minimum, maximum


def apply_material(obj: bpy.types.Object, material: bpy.types.Material) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(material)


def bevel(obj: bpy.types.Object, size: tuple[float, float, float]) -> None:
    modifier = obj.modifiers.new(name="soft-edges", type="BEVEL")
    modifier.width = min(size) * 0.08
    modifier.segments = 3
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.select_set(False)


def create_primitive(
    placement: dict[str, Any],
    center: Vector,
    floor_top: float,
    material: bpy.types.Material,
) -> bpy.types.Object:
    x, y, z = (float(value) for value in placement["position"])
    size = tuple(float(value) for value in placement["size"])
    blender_size = (size[0], size[2], size[1])
    location = (center.x + x, center.y + z, floor_top + y)
    kind = placement["kind"]
    if kind == "box":
        bpy.ops.mesh.primitive_cube_add(location=location)
        obj = bpy.context.object
        obj.dimensions = blender_size
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        bevel(obj, blender_size)
    elif kind == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=48,
            radius=max(size[0], size[2]) / 2,
            depth=size[1],
            location=location,
        )
        obj = bpy.context.object
        bevel(obj, blender_size)
    elif kind == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, location=location)
        obj = bpy.context.object
        obj.scale = (size[0] / 2, size[2] / 2, size[1] / 2)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    else:
        raise ValueError(f"unsupported procedural primitive: {kind}")
    obj.name = f"style-{placement['id']}"
    obj.rotation_euler[2] = math.radians(float(placement["rotationYDegrees"]))
    apply_material(obj, material)
    return obj


def point_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def add_area_light(name: str, location: Vector, target: Vector, color: str, energy: float) -> None:
    data = bpy.data.lights.new(name=name, type="AREA")
    data.color = hex_color(color)[:3]
    data.energy = energy
    data.shape = "DISK"
    data.size = 5
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    point_at(obj, target)


def configure_scene(style: dict[str, Any], imported: list[bpy.types.Object]) -> int:
    scene = bpy.context.scene
    materials = {
        role: create_material(role, value) for role, value in style["materials"].items()
    }
    for obj in imported:
        apply_material(obj, materials["architecture"])

    minimum, maximum = mesh_bounds(imported)
    center = (minimum + maximum) / 2
    floor_padding = float(style["layout"]["floorPadding"])
    floor_width = max(6.0, maximum.x - minimum.x + floor_padding * 2)
    floor_depth = max(6.0, maximum.y - minimum.y + floor_padding * 2)
    floor_height = 0.12
    floor_top = minimum.z
    bpy.ops.mesh.primitive_cube_add(
        location=(center.x, center.y, floor_top - floor_height / 2),
        scale=(floor_width / 2, floor_depth / 2, floor_height / 2),
    )
    floor = bpy.context.object
    floor.name = "style-floor"
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    apply_material(floor, materials["floor"])

    procedural = [
        create_primitive(placement, center, floor_top, materials[placement["role"]])
        for placement in style["layout"]["placements"]
    ]
    all_meshes = imported + [floor] + procedural
    styled_minimum, styled_maximum = mesh_bounds(all_meshes)
    target = (styled_minimum + styled_maximum) / 2
    target.z = floor_top + max(0.8, (styled_maximum.z - floor_top) * 0.42)

    environment = style["environment"]
    world = bpy.data.worlds.new("style-world") if scene.world is None else scene.world
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is None:
        raise RuntimeError("Blender world background node is unavailable")
    background.inputs["Color"].default_value = hex_color(environment["backgroundColor"])
    background.inputs["Strength"].default_value = float(environment["ambientIntensity"]) * 0.32

    radius = max(8.0, (styled_maximum - styled_minimum).length * 1.25)
    add_area_light(
        "style-key",
        target + Vector((radius * 0.45, -radius * 0.5, radius * 0.75)),
        target,
        environment["sunColor"],
        850 * float(environment["sunIntensity"]),
    )
    add_area_light(
        "style-fill",
        target + Vector((-radius * 0.55, radius * 0.35, radius * 0.42)),
        target,
        environment["ambientColor"],
        420 * float(environment["ambientIntensity"]),
    )

    camera_value = style["camera"]
    alpha = math.radians(float(camera_value["alphaDegrees"]))
    beta = math.radians(float(camera_value["betaDegrees"]))
    camera_radius = radius * float(camera_value["radiusMultiplier"])
    direction = Vector(
        (
            math.cos(alpha) * math.sin(beta),
            math.sin(alpha) * math.sin(beta),
            math.cos(beta),
        )
    )
    camera_data = bpy.data.cameras.new("style-camera")
    camera_data.lens = 48
    camera = bpy.data.objects.new("style-camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = target + direction * camera_radius
    point_at(camera, target)
    scene.camera = camera

    scene.render.engine = "BLENDER_EEVEE"
    if not hasattr(scene, "eevee"):
        raise RuntimeError("Blender 5.x EEVEE settings are unavailable")
    scene.eevee.taa_render_samples = int(style["output"]["samples"])
    scene.render.resolution_x = int(style["output"]["width"])
    scene.render.resolution_y = int(style["output"]["height"])
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.view_settings.look = "AgX - Medium High Contrast"
    return len(all_meshes)


def main() -> None:
    started = time.monotonic()
    args = parse_arguments()
    style = load_style(args.style)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.input), import_shading="NORMALS")
    imported = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    object_count = configure_scene(style, imported)
    bpy.context.scene.render.filepath = str(args.output)
    bpy.ops.render.render(write_still=True)
    report = {
        "engine": bpy.context.scene.render.engine,
        "blenderVersion": bpy.app.version_string,
        "renderSeconds": round(time.monotonic() - started, 3),
        "objects": object_count,
        "styleId": style["id"],
        "styleVersion": style["version"],
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
