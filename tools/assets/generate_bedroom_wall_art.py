from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector


ASSET_ID = "project-warm-minimal-bedroom-art"
GENERATOR_VERSION = "warm-minimal-bedroom-art-v1"
QUANTIZATION_STEPS = 4096


def parse_arguments() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Generate reusable warm-minimal bedroom wall art")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args(values)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def material(
    name: str,
    color: tuple[float, float, float, float],
    roughness: float,
    metallic: float = 0,
) -> bpy.types.Material:
    value = bpy.data.materials.new(name=name)
    value.use_nodes = True
    principled = value.node_tree.nodes.get("Principled BSDF")
    if principled is None:
        raise RuntimeError("Blender Principled BSDF is unavailable")
    principled.inputs["Base Color"].default_value = color
    principled.inputs["Roughness"].default_value = roughness
    principled.inputs["Metallic"].default_value = metallic
    if "Specular IOR Level" in principled.inputs:
        principled.inputs["Specular IOR Level"].default_value = 0.25
    value.diffuse_color = color
    return value


def rounded_box(
    name: str,
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    assigned_material: bpy.types.Material,
    bevel_width: float,
    rotation_z_degrees: float = 0,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(
        location=location,
        rotation=(0, 0, math.radians(rotation_z_degrees)),
    )
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bevel = obj.modifiers.new(name="soft-edge", type="BEVEL")
    bevel.width = min(bevel_width, min(size) * 0.45)
    bevel.segments = 3
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    obj.data.materials.append(assigned_material)
    return obj


def relief_disc(
    name: str,
    diameter: float,
    location: tuple[float, float, float],
    assigned_material: bpy.types.Material,
) -> bpy.types.Object:
    radius = diameter / 2
    half_depth = 0.0225
    segments = 48
    vertices = [(0, half_depth, 0), (0, -half_depth, 0)]
    for y in (half_depth, -half_depth):
        vertices.extend(
            (
                math.cos(index * math.tau / segments) * radius,
                y,
                math.sin(index * math.tau / segments) * radius,
            )
            for index in range(segments)
        )
    faces: list[tuple[int, int, int]] = []
    front_start = 2
    back_start = front_start + segments
    for index in range(segments):
        following = (index + 1) % segments
        faces.append((0, front_start + index, front_start + following))
        faces.append((1, back_start + following, back_start + index))
        faces.append((front_start + index, back_start + index, back_start + following))
        faces.append((front_start + index, back_start + following, front_start + following))
    mesh = bpy.data.meshes.new(f"{name}-mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    obj.data.materials.append(assigned_material)
    return obj


def quantize_mesh(obj: bpy.types.Object) -> None:
    if obj.type != "MESH":
        return
    for vertex in obj.data.vertices:
        vertex.co = tuple(
            round(value * QUANTIZATION_STEPS) / QUANTIZATION_STEPS for value in vertex.co
        )
    for uv_layer in obj.data.uv_layers:
        for entry in uv_layer.data:
            entry.uv = tuple(
                round(value * QUANTIZATION_STEPS) / QUANTIZATION_STEPS for value in entry.uv
            )
    obj.data.update()


def bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def generate() -> list[bpy.types.Object]:
    canvas = material("warm-linen-canvas", (0.72, 0.59, 0.46, 1), 0.9)
    ivory = material("chalk-relief", (0.86, 0.81, 0.7, 1), 0.84)
    clay = material("burnt-clay-relief", (0.46, 0.18, 0.08, 1), 0.78)
    oak = material("dark-oak-frame", (0.075, 0.032, 0.016, 1), 0.52)
    objects = [
        rounded_box("canvas", (1.3, 0.045, 0.74), (0, 0, 0.37), canvas, 0.018),
        rounded_box("frame-top", (1.38, 0.07, 0.045), (0, 0.01, 0.762), oak, 0.012),
        rounded_box("frame-bottom", (1.38, 0.07, 0.045), (0, 0.01, -0.022), oak, 0.012),
        rounded_box("frame-left", (0.045, 0.07, 0.74), (-0.667, 0.01, 0.37), oak, 0.012),
        rounded_box("frame-right", (0.045, 0.07, 0.74), (0.667, 0.01, 0.37), oak, 0.012),
        relief_disc("clay-sun", 0.47, (-0.27, 0.055, 0.46), clay),
        relief_disc("ivory-moon", 0.3, (0.35, 0.065, 0.3), ivory),
        rounded_box(
            "ivory-horizon",
            (0.72, 0.045, 0.12),
            (0.23, 0.075, 0.57),
            ivory,
            0.05,
            rotation_z_degrees=-8,
        ),
        rounded_box(
            "clay-horizon",
            (0.58, 0.045, 0.09),
            (0.12, 0.085, 0.2),
            clay,
            0.04,
            rotation_z_degrees=7,
        ),
    ]
    for obj in objects:
        quantize_mesh(obj)
        obj["catalogAssetId"] = ASSET_ID
        obj["generatorVersion"] = GENERATOR_VERSION
        obj["licenseSpdx"] = "CC0-1.0"
        obj.select_set(True)
    bpy.context.view_layer.update()
    return objects


def main() -> None:
    args = parse_arguments()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    objects = generate()
    minimum, maximum = bounds(objects)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(args.output),
        export_format="GLB",
        export_yup=True,
        export_apply=True,
        export_normals=False,
        use_selection=True,
        export_extras=True,
    )
    size = maximum - minimum
    report: dict[str, Any] = {
        "id": ASSET_ID,
        "generatorVersion": GENERATOR_VERSION,
        "deliveryFile": args.output.name,
        "deliverySha256": sha256(args.output),
        "deliveryBytes": args.output.stat().st_size,
        "canonicalSize": [round(size.x, 6), round(size.z, 6), round(size.y, 6)],
        "objects": len(objects),
        "materials": len(bpy.data.materials),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
