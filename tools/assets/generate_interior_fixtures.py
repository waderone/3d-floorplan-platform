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


GENERATOR_VERSION = "interior-fixtures-v2"


def parse_arguments() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Generate project-owned interior fixture GLBs")
    parser.add_argument(
        "--asset",
        required=True,
        choices=("kitchen", "bathroom", "planter", "bedside-table"),
    )
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
    alpha: float = 1,
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
    principled.inputs["Alpha"].default_value = alpha
    if emission is not None:
        if "Emission Color" in principled.inputs:
            principled.inputs["Emission Color"].default_value = emission
        elif "Emission" in principled.inputs:
            principled.inputs["Emission"].default_value = emission
        if "Emission Strength" in principled.inputs:
            principled.inputs["Emission Strength"].default_value = emission_strength
    if "Specular IOR Level" in principled.inputs:
        principled.inputs["Specular IOR Level"].default_value = 0.3
    value.diffuse_color = (*color[:3], alpha)
    if alpha < 1:
        value.surface_render_method = "DITHERED"
    return value


def rounded_box(
    name: str,
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    assigned_material: bpy.types.Material,
    bevel_width: float = 0.02,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    modifier = obj.modifiers.new(name="soft-edge", type="BEVEL")
    modifier.width = min(bevel_width, min(size) * 0.45)
    modifier.segments = 3
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
    rotation: tuple[float, float, float] = (0, 0, 0),
    vertices: int = 32,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices,
        radius=radius,
        depth=depth,
        location=location,
        rotation=rotation,
    )
    obj = bpy.context.object
    obj.name = name
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    obj.data.materials.append(assigned_material)
    return obj


def cone(
    name: str,
    radius_bottom: float,
    radius_top: float,
    depth: float,
    location: tuple[float, float, float],
    assigned_material: bpy.types.Material,
    vertices: int = 40,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cone_add(
        vertices=vertices,
        radius1=radius_bottom,
        radius2=radius_top,
        depth=depth,
        location=location,
    )
    obj = bpy.context.object
    obj.name = name
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    obj.data.materials.append(assigned_material)
    return obj


def sphere(
    name: str,
    scale: tuple[float, float, float],
    location: tuple[float, float, float],
    assigned_material: bpy.types.Material,
    rotation: tuple[float, float, float] = (0, 0, 0),
) -> bpy.types.Object:
    # Icospheres contain triangles from the start; using UV-sphere quads would
    # leave the exporter to choose diagonals and make independent GLBs vary.
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(assigned_material)
    return obj


def build_kitchen() -> tuple[str, list[bpy.types.Object]]:
    asset_id = "project-warm-minimal-kitchen"
    oak = material("natural-oak", (0.34, 0.17, 0.075, 1), 0.5)
    ivory = material("warm-ivory-cabinet", (0.72, 0.65, 0.54, 1), 0.58)
    stone = material("travertine-worktop", (0.56, 0.47, 0.36, 1), 0.3)
    graphite = material("graphite-appliance", (0.018, 0.021, 0.024, 1), 0.2, 0.58)
    steel = material("brushed-steel", (0.34, 0.36, 0.38, 1), 0.18, 0.82)
    glass = material("smoked-appliance-glass", (0.025, 0.035, 0.04, 1), 0.08, 0.72)
    warm_light = material(
        "under-cabinet-warm-light",
        (0.9, 0.66, 0.36, 1),
        0.22,
        emission=(1.0, 0.52, 0.2, 1),
        emission_strength=2.8,
    )
    ceramic = material("countertop-ceramic", (0.74, 0.69, 0.6, 1), 0.48)
    objects: list[bpy.types.Object] = []

    objects.extend(
        [
            rounded_box("base-carcass", (1.82, 0.58, 0.7), (0, 0, 0.43), oak, 0.035),
            rounded_box("toe-kick", (1.7, 0.48, 0.1), (0, 0.03, 0.07), graphite, 0.018),
            rounded_box("worktop", (1.9, 0.66, 0.075), (0, 0, 0.82), stone, 0.028),
            rounded_box("backsplash", (1.9, 0.055, 0.54), (0, 0.305, 1.1), stone, 0.012),
            rounded_box("wall-cabinet-left", (0.82, 0.36, 0.72), (-0.52, 0.13, 1.72), ivory, 0.035),
        ]
    )
    for index, x in enumerate((-0.68, -0.23, 0.68), start=1):
        objects.append(rounded_box(f"base-door-{index}", (0.41, 0.035, 0.59), (x, -0.305, 0.46), ivory, 0.018))
        objects.append(cylinder(f"base-handle-{index}", 0.012, 0.24, (x + 0.13, -0.335, 0.51), steel))
    objects.append(rounded_box("wall-door-left", (0.77, 0.03, 0.66), (-0.52, -0.065, 1.72), ivory, 0.018))
    objects.append(cylinder("wall-handle-left", 0.011, 0.25, (-0.24, -0.09, 1.67), steel))

    objects.append(rounded_box("induction-hob", (0.58, 0.44, 0.018), (0.55, -0.045, 0.868), graphite, 0.012))
    for index, (x, y) in enumerate(((0.4, -0.15), (0.68, -0.15), (0.4, 0.04), (0.68, 0.04)), start=1):
        objects.append(cylinder(f"hob-ring-{index}", 0.075, 0.008, (x, y, 0.881), steel, vertices=40))
    objects.append(rounded_box("sink-basin", (0.52, 0.38, 0.055), (-0.53, -0.03, 0.86), steel, 0.055))
    objects.append(rounded_box("sink-inner", (0.42, 0.29, 0.025), (-0.53, -0.04, 0.887), graphite, 0.045))
    objects.append(cylinder("faucet-base", 0.04, 0.24, (-0.53, 0.17, 0.98), steel))
    objects.append(cylinder("faucet-spout", 0.025, 0.26, (-0.53, 0.08, 1.09), steel, rotation=(math.pi / 2, 0, 0)))
    objects.append(rounded_box("oven-frame", (0.41, 0.045, 0.56), (0.23, -0.31, 0.46), graphite, 0.018))
    objects.append(rounded_box("oven-window", (0.33, 0.018, 0.31), (0.23, -0.34, 0.46), glass, 0.012))
    objects.append(cylinder("oven-handle", 0.015, 0.3, (0.23, -0.37, 0.68), steel, rotation=(0, math.pi / 2, 0)))
    objects.append(rounded_box("hood-chimney", (0.34, 0.22, 0.48), (0.55, 0.2, 1.84), steel, 0.02))
    objects.append(rounded_box("hood-canopy", (0.72, 0.39, 0.12), (0.55, 0.06, 1.52), steel, 0.035))
    objects.append(rounded_box("under-cabinet-light", (0.76, 0.045, 0.025), (-0.52, -0.08, 1.34), warm_light, 0.008))
    objects.append(rounded_box("oak-cutting-board", (0.28, 0.035, 0.36), (-0.12, -0.09, 0.9), oak, 0.018))
    objects.append(cylinder("ceramic-canister-large", 0.075, 0.18, (-0.17, 0.12, 1.02), ceramic, vertices=32))
    objects.append(cylinder("ceramic-canister-small", 0.055, 0.13, (-0.02, 0.12, 0.995), ceramic, vertices=32))
    return asset_id, objects


def build_bathroom() -> tuple[str, list[bpy.types.Object]]:
    asset_id = "project-warm-minimal-bathroom"
    oak = material("bathroom-oak", (0.38, 0.2, 0.1, 1), 0.5)
    ceramic = material("porcelain", (0.88, 0.86, 0.81, 1), 0.24)
    stone = material("bathroom-stone", (0.62, 0.57, 0.5, 1), 0.38)
    graphite = material("bathroom-graphite", (0.025, 0.03, 0.035, 1), 0.18, 0.72)
    glass = material("shower-glass", (0.63, 0.76, 0.78, 1), 0.08, alpha=0.2)
    mirror = material(
        "silvered-mirror",
        (0.36, 0.43, 0.46, 1),
        0.12,
        0.58,
        emission=(0.2, 0.27, 0.3, 1),
        emission_strength=0.16,
    )
    towel = material("woven-towel", (0.68, 0.58, 0.47, 1), 0.9)
    warm_light = material(
        "mirror-warm-light",
        (0.94, 0.72, 0.43, 1),
        0.2,
        emission=(1.0, 0.58, 0.25, 1),
        emission_strength=3.2,
    )
    objects: list[bpy.types.Object] = []

    objects.extend(
        [
            rounded_box("vanity", (0.74, 0.48, 0.55), (-0.38, 0, 0.48), oak, 0.04),
            rounded_box("vanity-top", (0.8, 0.54, 0.06), (-0.38, 0, 0.79), stone, 0.025),
            rounded_box("basin", (0.53, 0.36, 0.11), (-0.38, -0.02, 0.86), ceramic, 0.08),
            rounded_box("mirror-frame", (0.75, 0.055, 0.83), (-0.38, 0.25, 1.45), graphite, 0.035),
            rounded_box("mirror-face-front", (0.68, 0.018, 0.76), (-0.38, 0.287, 1.45), mirror, 0.025),
            rounded_box("mirror-face-back", (0.68, 0.018, 0.76), (-0.38, 0.213, 1.45), mirror, 0.025),
            rounded_box("mirror-light", (0.54, 0.025, 0.035), (-0.38, 0.21, 1.9), warm_light, 0.01),
            rounded_box("shower-glass", (0.035, 0.74, 1.72), (0.76, 0.12, 0.88), glass, 0.012),
            rounded_box("shower-rail", (0.055, 0.055, 1.72), (0.76, 0.47, 0.88), graphite, 0.014),
            rounded_box("shower-tray", (0.7, 0.68, 0.055), (0.42, 0.1, 0.04), stone, 0.025),
        ]
    )
    objects.append(cylinder("basin-faucet", 0.025, 0.24, (-0.38, 0.18, 1.0), graphite))
    objects.append(rounded_box("vanity-drawer-upper", (0.66, 0.025, 0.19), (-0.38, -0.255, 0.61), oak, 0.015))
    objects.append(rounded_box("vanity-drawer-lower", (0.66, 0.025, 0.19), (-0.38, -0.255, 0.38), oak, 0.015))
    objects.append(cylinder("vanity-handle-upper", 0.01, 0.24, (-0.38, -0.285, 0.64), graphite, rotation=(0, math.pi / 2, 0)))
    objects.append(cylinder("vanity-handle-lower", 0.01, 0.24, (-0.38, -0.285, 0.41), graphite, rotation=(0, math.pi / 2, 0)))
    objects.append(rounded_box("vanity-drawer-upper-back", (0.66, 0.025, 0.19), (-0.38, 0.255, 0.61), oak, 0.015))
    objects.append(rounded_box("vanity-drawer-lower-back", (0.66, 0.025, 0.19), (-0.38, 0.255, 0.38), oak, 0.015))
    objects.append(cylinder("vanity-handle-upper-back", 0.01, 0.24, (-0.38, 0.285, 0.64), graphite, rotation=(0, math.pi / 2, 0)))
    objects.append(cylinder("vanity-handle-lower-back", 0.01, 0.24, (-0.38, 0.285, 0.41), graphite, rotation=(0, math.pi / 2, 0)))
    objects.append(cylinder("toilet-base", 0.2, 0.38, (0.42, 0.02, 0.24), ceramic, vertices=40))
    objects.append(sphere("toilet-bowl", (0.28, 0.36, 0.17), (0.42, -0.03, 0.49), ceramic))
    objects.append(rounded_box("toilet-tank", (0.45, 0.22, 0.58), (0.42, 0.23, 0.54), ceramic, 0.07))
    objects.append(rounded_box("toilet-seat", (0.47, 0.5, 0.055), (0.42, -0.07, 0.62), ceramic, 0.12))
    objects.append(cylinder("shower-head", 0.11, 0.035, (0.66, 0.42, 1.72), graphite, rotation=(math.pi / 2, 0, 0), vertices=40))
    objects.append(cylinder("shower-pipe", 0.018, 0.75, (0.66, 0.47, 1.38), graphite))
    objects.append(cylinder("shower-control", 0.055, 0.035, (0.55, 0.47, 1.05), graphite, rotation=(math.pi / 2, 0, 0), vertices=32))
    objects.append(cylinder("towel-rail", 0.012, 0.42, (-0.82, -0.02, 1.12), graphite, rotation=(0, math.pi / 2, 0), vertices=24))
    objects.append(rounded_box("folded-towel", (0.34, 0.06, 0.46), (-0.82, -0.055, 0.91), towel, 0.025))
    objects.append(cylinder("toilet-flush", 0.035, 0.018, (0.42, 0.115, 0.85), graphite, rotation=(math.pi / 2, 0, 0), vertices=32))
    return asset_id, objects


def build_bedside_table() -> tuple[str, list[bpy.types.Object]]:
    asset_id = "project-warm-minimal-bedside-table"
    oak = material("bedside-natural-oak", (0.31, 0.15, 0.065, 1), 0.52)
    stone = material("bedside-travertine", (0.62, 0.54, 0.43, 1), 0.34)
    brass = material("bedside-brushed-brass", (0.38, 0.2, 0.07, 1), 0.2, 0.82)
    linen = material("bedside-linen-shade", (0.74, 0.66, 0.54, 1), 0.82)
    warm_light = material(
        "bedside-warm-bulb",
        (0.95, 0.68, 0.35, 1),
        0.18,
        emission=(1.0, 0.45, 0.16, 1),
        emission_strength=3.5,
    )
    objects = [
        rounded_box("cabinet", (0.46, 0.4, 0.46), (0, 0, 0.34), oak, 0.045),
        rounded_box("stone-top", (0.49, 0.43, 0.045), (0, 0, 0.59), stone, 0.018),
        rounded_box("drawer-face", (0.38, 0.025, 0.15), (0, -0.215, 0.43), oak, 0.015),
        cylinder("drawer-pull", 0.009, 0.16, (0, -0.245, 0.43), brass, rotation=(0, math.pi / 2, 0), vertices=20),
        cylinder("lamp-base", 0.095, 0.025, (0, 0, 0.625), brass, vertices=32),
        cylinder("lamp-stem", 0.015, 0.27, (0, 0, 0.77), brass, vertices=20),
        sphere("warm-bulb", (0.055, 0.055, 0.065), (0, 0, 0.88), warm_light),
        cone("linen-shade", 0.16, 0.1, 0.24, (0, 0, 0.9), linen),
    ]
    for index, (x, y) in enumerate(((-0.16, -0.14), (0.16, -0.14), (-0.16, 0.14), (0.16, 0.14)), start=1):
        objects.append(cylinder(f"leg-{index}", 0.018, 0.14, (x, y, 0.07), brass, vertices=16))
    return asset_id, objects


def build_planter() -> tuple[str, list[bpy.types.Object]]:
    asset_id = "project-sculptural-planter"
    pot = material("sandstone-pot", (0.51, 0.39, 0.28, 1), 0.78)
    stem = material("plant-stem", (0.08, 0.16, 0.065, 1), 0.72)
    leaf = material("olive-leaf", (0.16, 0.3, 0.12, 1), 0.68)
    objects: list[bpy.types.Object] = []
    bpy.ops.mesh.primitive_cone_add(vertices=40, radius1=0.3, radius2=0.24, depth=0.46, location=(0, 0, 0.23))
    planter = bpy.context.object
    planter.name = "tapered-planter"
    planter.data.materials.append(pot)
    objects.append(planter)
    for index, (x, y, angle) in enumerate(((-0.09, 0.01, -12), (0.08, -0.03, 10), (0, 0.05, 0)), start=1):
        objects.append(cylinder(f"stem-{index}", 0.018, 0.92, (x, y, 0.87), stem, rotation=(0, math.radians(angle), 0), vertices=16))
    leaf_specs = (
        (-0.22, 0.02, 0.72, -28), (0.23, 0.03, 0.82, 28), (-0.18, -0.03, 1.02, -35),
        (0.2, -0.02, 1.14, 30), (-0.08, 0.04, 1.28, -15), (0.11, 0.05, 1.4, 18),
        (-0.28, 0.02, 1.19, -42), (0.3, 0.01, 0.98, 42),
    )
    for index, (x, y, z, angle) in enumerate(leaf_specs, start=1):
        objects.append(sphere(f"leaf-{index}", (0.24, 0.08, 0.12), (x, y, z), leaf, rotation=(0, math.radians(angle), 0)))
    return asset_id, objects


BUILDERS: dict[str, Callable[[], tuple[str, list[bpy.types.Object]]]] = {
    "kitchen": build_kitchen,
    "bathroom": build_bathroom,
    "planter": build_planter,
    "bedside-table": build_bedside_table,
}


def bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    if not points:
        raise RuntimeError("generated fixture has no bounds")
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
    # Bake transforms before exporting so Blender does not recompute rotated
    # vertices while serialising the GLB. This keeps independently generated
    # delivery files byte-for-byte reproducible.
    for obj in objects:
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
