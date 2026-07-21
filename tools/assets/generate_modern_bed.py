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


ASSET_ID = "project-modern-upholstered-bed"
GENERATOR_VERSION = "modern-upholstered-bed-v1"


def parse_arguments() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Generate the project-owned modern bed GLB")
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
        principled.inputs["Specular IOR Level"].default_value = 0.28
    value.diffuse_color = color
    return value


def rounded_box(
    name: str,
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    assigned_material: bpy.types.Material,
    bevel_width: float,
    rotation: tuple[float, float, float] = (0, 0, 0),
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    modifier = obj.modifiers.new(name="soft-edge", type="BEVEL")
    modifier.width = min(bevel_width, min(size) * 0.45)
    modifier.segments = 4
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    obj.data.materials.append(assigned_material)
    return obj


def bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    if not points:
        raise RuntimeError("generated bed has no bounds")
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def generate() -> list[bpy.types.Object]:
    upholstery = material("warm-oat-upholstery", (0.48, 0.39, 0.31, 1), 0.72)
    linen = material("soft-ivory-linen", (0.82, 0.77, 0.67, 1), 0.86)
    duvet = material("sand-duvet", (0.66, 0.58, 0.48, 1), 0.8)
    accent = material("clay-throw", (0.38, 0.19, 0.12, 1), 0.78)
    wood = material("dark-oak-legs", (0.09, 0.045, 0.024, 1), 0.5)
    objects: list[bpy.types.Object] = []

    objects.append(rounded_box("platform", (2.02, 2.18, 0.29), (0, -0.04, 0.27), upholstery, 0.09))
    objects.append(rounded_box("mattress", (1.88, 1.98, 0.27), (0, -0.08, 0.52), linen, 0.11))
    objects.append(rounded_box("duvet", (1.9, 1.5, 0.18), (0, -0.3, 0.71), duvet, 0.08))
    objects.append(rounded_box("foot-throw", (1.91, 0.43, 0.09), (0, -0.78, 0.81), accent, 0.035))

    objects.append(rounded_box("headboard-core", (2.1, 0.16, 1.22), (0, 1.02, 0.77), upholstery, 0.1))
    for index, x in enumerate((-0.8, -0.4, 0, 0.4, 0.8)):
        objects.append(
            rounded_box(
                f"headboard-channel-{index + 1}",
                (0.34, 0.065, 1.03),
                (x, 0.91, 0.78),
                upholstery,
                0.06,
            )
        )

    objects.append(
        rounded_box(
            "pillow-left",
            (0.78, 0.43, 0.18),
            (-0.43, 0.59, 0.82),
            linen,
            0.09,
            rotation=(math.radians(-8), math.radians(2), math.radians(-5)),
        )
    )
    objects.append(
        rounded_box(
            "pillow-right",
            (0.78, 0.43, 0.18),
            (0.43, 0.59, 0.82),
            linen,
            0.09,
            rotation=(math.radians(-8), math.radians(-2), math.radians(5)),
        )
    )
    for x in (-0.82, 0.82):
        for y in (-0.9, 0.77):
            objects.append(rounded_box(f"leg-{x}-{y}", (0.1, 0.1, 0.18), (x, y, 0.09), wood, 0.02))

    minimum, maximum = bounds(objects)
    offset = Vector((-(minimum.x + maximum.x) / 2, -(minimum.y + maximum.y) / 2, -minimum.z))
    for obj in objects:
        obj.location += offset
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
