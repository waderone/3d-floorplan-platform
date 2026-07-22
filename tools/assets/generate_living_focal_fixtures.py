from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Callable

import bpy
from mathutils import Vector


GENERATOR_VERSION = "living-focal-fixtures-v1"


def parse_arguments() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Generate project-owned living-room focal assets")
    parser.add_argument("--asset", required=True, choices=("television", "floor-lamp"))
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
    emission: tuple[float, float, float, float] | None = None,
    emission_strength: float = 0,
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
        principled.inputs["Specular IOR Level"].default_value = 0.35
    if emission is not None:
        principled.inputs["Emission Color"].default_value = emission
        principled.inputs["Emission Strength"].default_value = emission_strength
    value.diffuse_color = color
    return value


def rounded_box(
    name: str,
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    assigned_material: bpy.types.Material,
    bevel_width: float,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location)
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


def cylinder(
    name: str,
    radius: float,
    depth: float,
    location: tuple[float, float, float],
    assigned_material: bpy.types.Material,
    vertices: int = 48,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices,
        radius=radius,
        depth=depth,
        location=location,
    )
    obj = bpy.context.object
    obj.name = name
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    obj.data.materials.append(assigned_material)
    return obj


def build_television() -> tuple[str, list[bpy.types.Object]]:
    asset_id = "project-modern-television"
    graphite = material("television-graphite", (0.018, 0.02, 0.023, 1), 0.24, 0.55)
    glass = material(
        "television-glass",
        (0.008, 0.012, 0.018, 1),
        0.08,
        0.08,
        emission=(0.018, 0.027, 0.04, 1),
        emission_strength=0.08,
    )
    indicator = material(
        "television-indicator",
        (0.22, 0.06, 0.025, 1),
        0.3,
        emission=(1, 0.08, 0.015, 1),
        emission_strength=1.6,
    )
    objects = [
        rounded_box("screen-shell", (1.42, 0.105, 0.78), (0, 0.035, 0.49), graphite, 0.035),
        rounded_box("screen-glass", (1.34, 0.018, 0.69), (0, -0.0265, 0.5), glass, 0.022),
        rounded_box("stand-neck", (0.12, 0.11, 0.16), (0, 0.04, 0.105), graphite, 0.025),
        rounded_box("stand-foot", (0.58, 0.28, 0.035), (0, 0.045, 0.018), graphite, 0.018),
        cylinder("status-light", 0.009, 0.012, (0.58, -0.032, 0.115), indicator, vertices=24),
    ]
    return asset_id, objects


def build_floor_lamp() -> tuple[str, list[bpy.types.Object]]:
    asset_id = "project-brass-floor-lamp"
    brass = material("satin-brass", (0.43, 0.25, 0.08, 1), 0.25, 0.82)
    stone = material("warm-stone-base", (0.42, 0.34, 0.27, 1), 0.58)
    shade = material("linen-shade", (0.8, 0.67, 0.49, 1), 0.82)
    bulb = material(
        "warm-bulb",
        (1, 0.55, 0.2, 1),
        0.18,
        emission=(1, 0.28, 0.055, 1),
        emission_strength=3.2,
    )
    objects: list[bpy.types.Object] = [
        cylinder("stone-base", 0.22, 0.07, (0, 0, 0.035), stone, vertices=64),
        cylinder("brass-stem", 0.018, 1.36, (0, 0, 0.75), brass, vertices=24),
        cylinder("shade-ring-bottom", 0.235, 0.018, (0, 0, 1.41), brass, vertices=64),
        cylinder("shade-ring-top", 0.16, 0.018, (0, 0, 1.73), brass, vertices=64),
        cylinder("bulb", 0.055, 0.13, (0, 0, 1.5), bulb, vertices=32),
    ]
    bpy.ops.mesh.primitive_cone_add(
        vertices=64,
        radius1=0.235,
        radius2=0.16,
        depth=0.32,
        location=(0, 0, 1.57),
    )
    lamp_shade = bpy.context.object
    lamp_shade.name = "linen-shade"
    for polygon in lamp_shade.data.polygons:
        polygon.use_smooth = True
    lamp_shade.data.materials.append(shade)
    objects.append(lamp_shade)
    return asset_id, objects


BUILDERS: dict[str, Callable[[], tuple[str, list[bpy.types.Object]]]] = {
    "television": build_television,
    "floor-lamp": build_floor_lamp,
}


def bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def main() -> None:
    args = parse_arguments()
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise RuntimeError("set PYTHONHASHSEED=0 for a reproducible GLB export")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    asset_id, objects = BUILDERS[args.asset]()
    minimum, maximum = bounds(objects)
    offset = Vector((-(minimum.x + maximum.x) / 2, -(minimum.y + maximum.y) / 2, -minimum.z))
    for obj in objects:
        obj.location += offset
        obj["catalogAssetId"] = asset_id
        obj["generatorVersion"] = GENERATOR_VERSION
        obj["licenseSpdx"] = "CC0-1.0"
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        if obj.type == "MESH":
            obj.data.validate(clean_customdata=True)
            obj.data.update(calc_edges=True)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.update()
    minimum, maximum = bounds(objects)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(args.output),
        export_format="GLB",
        export_yup=True,
        export_apply=False,
        export_meshopt_compression_enable=True,
        export_texcoords=False,
        use_selection=True,
        export_extras=True,
    )
    size = maximum - minimum
    report: dict[str, Any] = {
        "id": asset_id,
        "generatorVersion": GENERATOR_VERSION,
        "deliveryFile": args.output.name,
        "deliverySha256": sha256(args.output),
        "deliveryBytes": args.output.stat().st_size,
        "canonicalSize": [round(size.x, 6), round(size.z, 6), round(size.y, 6)],
        "objects": len(objects),
        "materials": len(bpy.data.materials),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
