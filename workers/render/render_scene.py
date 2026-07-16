from __future__ import annotations

import argparse
import hashlib
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
    parser.add_argument("--layout", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
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


def load_layout(path: Path, style: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"layoutId", "pipelineVersion", "style", "status", "placements"}
    if not isinstance(value, dict) or not required.issubset(value):
        raise ValueError("layout manifest is invalid")
    if value["style"] != {"id": style["id"], "version": style["version"]}:
        raise ValueError("layout manifest style does not match the style pack")
    if value["status"] not in {"ready", "partial", "fallback"} or not isinstance(value["placements"], list):
        raise ValueError("layout manifest status is invalid")
    return value


def load_catalog(path: Path, layout: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"schemaVersion", "id", "version", "assets"}
    if not isinstance(value, dict) or not required.issubset(value) or not isinstance(value["assets"], list):
        raise ValueError("asset catalog is invalid")
    if layout.get("assetCatalog") != {"id": value["id"], "version": value["version"]}:
        raise ValueError("layout manifest asset catalog does not match")
    assets = {
        asset["id"]: asset
        for asset in value["assets"]
        if isinstance(asset, dict) and isinstance(asset.get("id"), str)
    }
    if len(assets) != len(value["assets"]):
        raise ValueError("asset catalog ids are invalid or duplicated")
    for asset in assets.values():
        delivery = asset.get("delivery")
        if delivery is None:
            continue
        model_path = path.parent / "models" / Path(delivery["url"]).name
        content = model_path.read_bytes()
        if len(content) != delivery["bytes"] or hashlib.sha256(content).hexdigest() != delivery["sha256"]:
            raise ValueError(f"asset catalog model integrity failed: {asset['id']}")
    return value, assets


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
    floor_top: float,
    material: bpy.types.Material,
) -> bpy.types.Object:
    x, y, z = (float(value) for value in placement["position"])
    size = tuple(float(value) for value in placement["size"])
    blender_size = (size[0], size[2], size[1])
    location = (x, z, floor_top + y)
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


def create_catalog_model(
    placement: dict[str, Any],
    asset: dict[str, Any],
    catalog_path: Path,
    floor_top: float,
) -> list[bpy.types.Object]:
    delivery = asset.get("delivery")
    if asset.get("kind") != "model" or not isinstance(delivery, dict):
        return []
    model_path = catalog_path.parent / "models" / Path(delivery["url"]).name
    before = set(bpy.context.scene.objects)
    try:
        bpy.ops.import_scene.gltf(filepath=str(model_path), import_shading="NORMALS")
        imported = [obj for obj in bpy.context.scene.objects if obj not in before]
        meshes = [obj for obj in imported if obj.type == "MESH"]
        if not meshes:
            raise RuntimeError("catalog GLB contains no meshes")
        roots = [obj for obj in imported if obj.parent not in imported]
        root = bpy.data.objects.new(f"asset-{placement['id']}", None)
        bpy.context.collection.objects.link(root)
        for obj in roots:
            obj.parent = root
        width, height, depth = (float(value) for value in placement["size"])
        source_width, source_height, source_depth = (
            float(value) for value in asset["canonicalSize"]
        )
        root.scale = (
            width / source_width,
            depth / source_depth,
            height / source_height,
        )
        x, y, z = (float(value) for value in placement["position"])
        root.location = (x, z, floor_top + y - height / 2)
        root.rotation_euler[2] = math.radians(float(placement["rotationYDegrees"]))
        return meshes
    except Exception:
        for obj in [obj for obj in bpy.context.scene.objects if obj not in before]:
            bpy.data.objects.remove(obj, do_unlink=True)
        return []


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


def configure_scene(
    style: dict[str, Any],
    layout: dict[str, Any],
    catalog_path: Path,
    assets: dict[str, dict[str, Any]],
    imported: list[bpy.types.Object],
) -> tuple[int, int, int]:
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

    furniture_meshes: list[bpy.types.Object] = []
    procedural: list[bpy.types.Object] = []
    real_asset_placements = 0
    fallback_placements = 0
    for placement in layout["placements"]:
        asset = assets.get(placement["assetId"])
        if asset is None:
            raise ValueError(f"layout references missing asset: {placement['assetId']}")
        model_meshes = create_catalog_model(placement, asset, catalog_path, floor_top)
        if model_meshes:
            furniture_meshes.extend(model_meshes)
            real_asset_placements += 1
            continue
        fallback = create_primitive(placement, floor_top, materials[placement["role"]])
        procedural.append(fallback)
        if asset.get("kind") == "model":
            fallback_placements += 1
    all_meshes = imported + [floor] + furniture_meshes + procedural
    styled_minimum, styled_maximum = mesh_bounds(all_meshes)
    furnished_rooms = [
        room for room in layout["rooms"] if room["id"] in layout.get("furnishedRoomIds", [])
    ]
    if furnished_rooms:
        room_x = [float(point[0]) for room in furnished_rooms for point in room["polygon"]]
        room_y = [float(point[1]) for room in furnished_rooms for point in room["polygon"]]
        target = Vector(
            (
                (min(room_x) + max(room_x)) / 2,
                (min(room_y) + max(room_y)) / 2,
                floor_top + max(0.8, (styled_maximum.z - floor_top) * 0.42),
            )
        )
        focus_diagonal = math.hypot(max(room_x) - min(room_x), max(room_y) - min(room_y))
    else:
        target = (styled_minimum + styled_maximum) / 2
        target.z = floor_top + max(0.8, (styled_maximum.z - floor_top) * 0.42)
        focus_diagonal = (styled_maximum - styled_minimum).length

    environment = style["environment"]
    world = bpy.data.worlds.new("style-world") if scene.world is None else scene.world
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is None:
        raise RuntimeError("Blender world background node is unavailable")
    background.inputs["Color"].default_value = hex_color(environment["backgroundColor"])
    background.inputs["Strength"].default_value = float(environment["ambientIntensity"]) * 0.32

    radius_factor = 1.5 if len(furnished_rooms) > 1 else 0.92
    radius = max(7.0, focus_diagonal * radius_factor)
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
    beta_degrees = float(camera_value["betaDegrees"])
    if len(furnished_rooms) > 1:
        beta_degrees = min(beta_degrees, 42)
    beta = math.radians(beta_degrees)
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
    return len(all_meshes), real_asset_placements, fallback_placements


def main() -> None:
    started = time.monotonic()
    args = parse_arguments()
    style = load_style(args.style)
    layout = load_layout(args.layout, style)
    catalog, assets = load_catalog(args.catalog, layout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.input), import_shading="NORMALS")
    imported = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    object_count, real_asset_placements, fallback_placements = configure_scene(
        style,
        layout,
        args.catalog,
        assets,
        imported,
    )
    bpy.context.scene.render.filepath = str(args.output)
    bpy.ops.render.render(write_still=True)
    report = {
        "engine": bpy.context.scene.render.engine,
        "blenderVersion": bpy.app.version_string,
        "renderSeconds": round(time.monotonic() - started, 3),
        "objects": object_count,
        "styleId": style["id"],
        "styleVersion": style["version"],
        "layoutId": layout["layoutId"],
        "layoutStatus": layout["status"],
        "placements": len(layout["placements"]),
        "assetCatalogId": catalog["id"],
        "assetCatalogVersion": catalog["version"],
        "realAssetPlacements": real_asset_placements,
        "fallbackPlacements": fallback_placements,
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
