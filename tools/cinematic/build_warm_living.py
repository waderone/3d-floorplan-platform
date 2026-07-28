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


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPEC = (
    REPOSITORY_ROOT / "packages" / "cinematic-scenes" / "warm-minimal-living-v1.json"
)
DEFAULT_ASSETS = REPOSITORY_ROOT / "work" / "cinematic-assets"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "work" / "cinematic-renders" / "warm-minimal-living"


def parse_arguments() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="生成暖木极简客厅离线主场景")
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--asset-directory", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output-blend", type=Path)
    parser.add_argument(
        "--profile",
        choices=("draft", "preview", "panorama-preview", "hero", "panorama"),
        default="draft",
    )
    parser.add_argument(
        "--view",
        action="append",
        choices=("hero", "seating", "wide", "layout", "panorama"),
    )
    return parser.parse_args(values)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 对象无效：{path}")
    return value


def sha256(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def validate_inputs(spec_path: Path, asset_directory: Path) -> dict[str, Any]:
    spec = load_json(spec_path)
    if spec.get("schemaVersion") != "1.0":
        raise ValueError("场景规格版本无效")
    for source_name in ("scene", "image"):
        path = REPOSITORY_ROOT / spec["source"][f"{source_name}Path"]
        if sha256(path) != spec["source"][f"{source_name}Sha256"]:
            raise RuntimeError(f"权威输入发生变化：{path}")
    catalog = load_json(REPOSITORY_ROOT / "packages" / "cinematic-assets" / "catalog.json")
    for resource in catalog["resources"]:
        path = asset_directory / resource["delivery"]["path"]
        if not path.is_file() or path.stat().st_size != resource["delivery"]["bytes"]:
            raise RuntimeError(f"离线素材缺失或字节数变化：{path}")
    return spec


def hex_color(value: str) -> tuple[float, float, float, float]:
    if not value.startswith("#") or len(value) != 7:
        raise ValueError(value)
    channels = [int(value[index : index + 2], 16) / 255 for index in (1, 3, 5)]

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    return (*[linear(channel) for channel in channels], 1.0)


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for collection in list(bpy.data.collections):
        if collection.users == 0:
            bpy.data.collections.remove(collection)


def image(path: Path, non_color: bool = False) -> bpy.types.Image:
    loaded = bpy.data.images.load(str(path), check_existing=True)
    if non_color:
        loaded.colorspace_settings.name = "Non-Color"
    return loaded


def principled_material(
    name: str,
    base_color: str,
    roughness: float,
    metallic: float = 0.0,
) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled is None:
        raise RuntimeError("Principled BSDF 不可用")
    principled.inputs["Base Color"].default_value = hex_color(base_color)
    principled.inputs["Roughness"].default_value = roughness
    principled.inputs["Metallic"].default_value = metallic
    return material


def textured_material(
    name: str,
    diffuse_path: Path,
    normal_path: Path,
    roughness_path: Path,
    tint: str,
    scale: tuple[float, float, float],
    normal_strength: float,
    roughness_multiplier: float = 1.0,
    use_diffuse: bool = True,
) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    principled = nodes.get("Principled BSDF")
    if principled is None:
        raise RuntimeError("Principled BSDF 不可用")

    coordinates = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = scale
    links.new(coordinates.outputs["Generated"], mapping.inputs["Vector"])

    roughness = nodes.new("ShaderNodeTexImage")
    roughness.image = image(roughness_path, non_color=True)
    roughness.extension = "REPEAT"
    normal = nodes.new("ShaderNodeTexImage")
    normal.image = image(normal_path, non_color=True)
    normal.extension = "REPEAT"
    for texture in (roughness, normal):
        links.new(mapping.outputs["Vector"], texture.inputs["Vector"])
    if use_diffuse:
        diffuse = nodes.new("ShaderNodeTexImage")
        diffuse.image = image(diffuse_path)
        diffuse.extension = "REPEAT"
        links.new(mapping.outputs["Vector"], diffuse.inputs["Vector"])
        multiply = nodes.new("ShaderNodeMixRGB")
        multiply.blend_type = "MULTIPLY"
        multiply.inputs[0].default_value = 1.0
        multiply.inputs[2].default_value = hex_color(tint)
        links.new(diffuse.outputs["Color"], multiply.inputs[1])
        links.new(multiply.outputs["Color"], principled.inputs["Base Color"])
    else:
        principled.inputs["Base Color"].default_value = hex_color(tint)

    rough_curve = nodes.new("ShaderNodeMath")
    rough_curve.operation = "MULTIPLY"
    rough_curve.inputs[1].default_value = roughness_multiplier
    links.new(roughness.outputs["Color"], rough_curve.inputs[0])
    links.new(rough_curve.outputs["Value"], principled.inputs["Roughness"])

    normal_map = nodes.new("ShaderNodeNormalMap")
    normal_map.inputs["Strength"].default_value = normal_strength
    links.new(normal.outputs["Color"], normal_map.inputs["Color"])
    links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])
    return material


def emission_material(name: str, color: str, strength: float) -> bpy.types.Material:
    material = principled_material(name, color, 0.35)
    principled = material.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Emission Color"].default_value = hex_color(color)
    principled.inputs["Emission Strength"].default_value = strength
    return material


def assign(obj: bpy.types.Object, material: bpy.types.Material) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(material)


def rounded_box(
    name: str,
    dimensions: tuple[float, float, float],
    location: tuple[float, float, float],
    material: bpy.types.Material,
    bevel: float = 0.03,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    segments: int = 4,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel > 0:
        modifier = obj.modifiers.new("soft-edges", "BEVEL")
        modifier.width = min(bevel, min(dimensions) * 0.42)
        modifier.segments = segments
        modifier.limit_method = "ANGLE"
        modifier.harden_normals = True
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    assign(obj, material)
    return obj


def cylinder(
    name: str,
    radius: float,
    depth: float,
    location: tuple[float, float, float],
    material: bpy.types.Material,
    vertices: int = 64,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices,
        radius=radius,
        depth=depth,
        location=location,
    )
    obj = bpy.context.object
    obj.name = name
    assign(obj, material)
    return obj


def beam_between(
    name: str,
    start: Vector,
    end: Vector,
    thickness: float,
    material: bpy.types.Material,
) -> bpy.types.Object:
    direction = end - start
    obj = rounded_box(
        name,
        (direction.length, thickness, thickness),
        tuple((start + end) / 2),
        material,
        bevel=thickness * 0.22,
        segments=3,
    )
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = direction.to_track_quat("X", "Z")
    return obj


def curve_seam(
    name: str,
    points: list[tuple[float, float, float]],
    material: bpy.types.Material,
    radius: float = 0.006,
) -> bpy.types.Object:
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = radius
    curve.bevel_resolution = 3
    spline = curve.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for point, coordinate in zip(spline.bezier_points, points, strict=True):
        point.co = coordinate
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    curve.materials.append(material)
    return obj


def piping_loop(
    name: str,
    points: list[tuple[float, float, float]],
    material: bpy.types.Material,
    radius: float = 0.005,
) -> bpy.types.Object:
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = radius
    curve.bevel_resolution = 3
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, coordinate in zip(spline.points, points, strict=True):
        point.co = (*coordinate, 1.0)
    spline.use_cyclic_u = True
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    curve.materials.append(material)
    return obj


def rounded_rectangle_points(
    center: tuple[float, float, float],
    width: float,
    height: float,
    radius: float,
    plane: str,
    segments: int = 7,
) -> list[tuple[float, float, float]]:
    x_center, y_center, z_center = center
    x_radius = width / 2 - radius
    y_radius = height / 2 - radius
    points: list[tuple[float, float, float]] = []
    for corner in range(4):
        angle_start = corner * math.pi / 2
        corner_x = x_radius if corner in (0, 3) else -x_radius
        corner_y = y_radius if corner in (0, 1) else -y_radius
        for index in range(segments):
            angle = angle_start + index * (math.pi / 2) / (segments - 1)
            local_x = corner_x + math.cos(angle) * radius
            local_y = corner_y + math.sin(angle) * radius
            if plane == "XY":
                points.append((x_center + local_x, y_center + local_y, z_center))
            elif plane == "XZ":
                points.append((x_center + local_x, y_center, z_center + local_y))
            else:
                raise ValueError(f"不支持的包边平面：{plane}")
    return points


def soft_cushion(
    name: str,
    dimensions: tuple[float, float, float],
    location: tuple[float, float, float],
    material: bpy.types.Material,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    bevel: float = 0.065,
    noise_strength: float = 0.0035,
    sag: float = 0.0,
    sag_axis: str = "Z",
) -> bpy.types.Object:
    obj = rounded_box(
        name,
        dimensions,
        location,
        material,
        bevel=bevel,
        rotation=rotation,
        segments=10,
    )
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    subdivision = obj.modifiers.new("cloth-subdivision", "SUBSURF")
    subdivision.levels = 1
    subdivision.render_levels = 2
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=subdivision.name)
    if sag > 0:
        width, depth, height = dimensions
        for vertex in obj.data.vertices:
            x, y, z = vertex.co
            if sag_axis == "Z" and z > 0:
                influence = max(0.0, 1.0 - (abs(x) / (width / 2)) ** 4)
                influence *= max(0.0, 1.0 - (abs(y) / (depth / 2)) ** 4)
                vertex.co.z -= sag * influence
            elif sag_axis == "Y" and y > 0:
                influence = max(0.0, 1.0 - (abs(x) / (width / 2)) ** 4)
                influence *= max(0.0, 1.0 - (abs(z) / (height / 2)) ** 4)
                vertex.co.y -= sag * influence
    texture = bpy.data.textures.new(f"{name}-micro-wrinkle", type="CLOUDS")
    texture.noise_scale = 0.11
    texture.noise_depth = 1
    displacement = obj.modifiers.new("cloth-relief", "DISPLACE")
    displacement.texture = texture
    displacement.texture_coords = "GLOBAL"
    displacement.strength = noise_strength
    displacement.mid_level = 0.5
    return obj


def create_architecture(
    spec: dict[str, Any],
    materials: dict[str, bpy.types.Material],
) -> None:
    width, depth, height = spec["envelope"]["localSize"]
    wall = float(spec["envelope"]["wallThickness"])
    rounded_box(
        "floor",
        (width + 0.18, depth + 0.18, 0.12),
        (0.0, 0.0, -0.06),
        materials["floor"],
        bevel=0.01,
    )
    rounded_box(
        "north-wall",
        (width + wall, wall, height),
        (0.0, depth / 2, height / 2),
        materials["plaster"],
        bevel=0.018,
    )
    door_center_y = 0.55
    door_width = 0.9
    north_segment_depth = depth / 2 - (door_center_y + door_width / 2)
    south_segment_depth = door_center_y - door_width / 2 + depth / 2
    for side, x in (("west", -width / 2), ("east", width / 2)):
        rounded_box(
            f"{side}-wall-north",
            (wall, north_segment_depth, height),
            (x, depth / 2 - north_segment_depth / 2, height / 2),
            materials["plaster"],
            bevel=0.018,
        )
        rounded_box(
            f"{side}-wall-south",
            (wall, south_segment_depth, height),
            (x, -depth / 2 + south_segment_depth / 2, height / 2),
            materials["plaster"],
            bevel=0.018,
        )
        for trim_y in (door_center_y - door_width / 2, door_center_y + door_width / 2):
            rounded_box(
                f"{side}-door-jamb",
                (0.07, 0.08, 2.18),
                (x + (0.045 if side == "west" else -0.045), trim_y, 1.09),
                materials["oak"],
                bevel=0.008,
            )
        rounded_box(
            f"{side}-door-head",
            (0.07, door_width + 0.08, 0.08),
            (x + (0.045 if side == "west" else -0.045), door_center_y, 2.14),
            materials["oak"],
            bevel=0.008,
        )
        rounded_box(
            f"{side}-adjacent-backdrop",
            (wall, 1.5, height),
            (x + (-0.95 if side == "west" else 0.95), door_center_y, height / 2),
            materials["plaster"],
            bevel=0.018,
        )
        adjacent_x = x + (-0.52 if side == "west" else 0.52)
        rounded_box(
            f"{side}-adjacent-floor",
            (1.15, 1.7, 0.12),
            (adjacent_x, door_center_y, -0.06),
            materials["floor"],
            bevel=0.01,
        )
        rounded_box(
            f"{side}-adjacent-ceiling",
            (1.15, 1.7, 0.12),
            (adjacent_x, door_center_y, height + 0.06),
            materials["plaster"],
            bevel=0.01,
        )
    rounded_box(
        "ceiling-main",
        (width + 0.12, depth * 0.78, 0.12),
        (0.0, -depth * 0.11, height + 0.06),
        materials["plaster"],
        bevel=0.01,
    )
    rounded_box(
        "ceiling-north-west",
        (0.92, depth * 0.22, 0.12),
        (-width / 2 + 0.46, depth * 0.39, height + 0.06),
        materials["plaster"],
        bevel=0.01,
    )
    rounded_box(
        "ceiling-north-east",
        (0.64, depth * 0.22, 0.12),
        (width / 2 - 0.32, depth * 0.39, height + 0.06),
        materials["plaster"],
        bevel=0.01,
    )
    corridor_depth = 2.55
    rounded_box(
        "corridor-floor",
        (width + 0.18, corridor_depth, 0.12),
        (0.0, -depth / 2 - corridor_depth / 2, -0.06),
        materials["floor"],
        bevel=0.01,
    )
    rounded_box(
        "corridor-ceiling",
        (width + 0.12, corridor_depth, 0.12),
        (0.0, -depth / 2 - corridor_depth / 2, height + 0.06),
        materials["plaster"],
        bevel=0.01,
    )
    for x in (-width / 2, width / 2):
        rounded_box(
            "corridor-wall",
            (wall, corridor_depth, height),
            (x, -depth / 2 - corridor_depth / 2, height / 2),
            materials["plaster"],
            bevel=0.018,
        )
    for side, x in (("west", -width / 2 + 0.08), ("east", width / 2 - 0.08)):
        rounded_box(
            f"baseboard-{side}-north",
            (0.035, north_segment_depth, 0.105),
            (x, depth / 2 - north_segment_depth / 2, 0.052),
            materials["trim"],
            bevel=0.008,
        )
        rounded_box(
            f"baseboard-{side}-south",
            (0.035, south_segment_depth + corridor_depth, 0.105),
            (x, -depth / 2 - corridor_depth / 2 + south_segment_depth / 2, 0.052),
            materials["trim"],
            bevel=0.008,
        )
    rounded_box(
        "baseboard-north",
        (width, 0.035, 0.105),
        (0.0, depth / 2 - 0.08, 0.052),
        materials["trim"],
        bevel=0.008,
    )


def create_staircase(materials: dict[str, bpy.types.Material]) -> None:
    steps = 13
    x_start = -1.42
    x_end = 1.42
    tread_depth = 0.82
    for index in range(steps):
        progress = index / (steps - 1)
        x = x_start + (x_end - x_start) * progress
        z = 0.12 + index * 0.2
        rounded_box(
            f"stair-tread-{index + 1:02d}",
            (0.34, tread_depth, 0.065),
            (x, 1.43, z),
            materials["oak"],
            bevel=0.015,
            segments=3,
        )
    beam_between(
        "stair-stringer",
        Vector((x_start - 0.08, 1.43, 0.06)),
        Vector((x_end + 0.08, 1.43, 2.48)),
        0.08,
        materials["metal"],
    )
    rail_y = 1.0
    post_tops: list[Vector] = []
    for index in range(0, steps, 2):
        progress = index / (steps - 1)
        x = x_start + (x_end - x_start) * progress
        step_z = 0.12 + index * 0.2
        post = cylinder(
            f"stair-post-{index:02d}",
            0.014,
            0.72,
            (x, rail_y, step_z + 0.39),
            materials["metal"],
            vertices=24,
        )
        post_tops.append(Vector((post.location.x, post.location.y, step_z + 0.75)))
    beam_between("stair-handrail", post_tops[0], post_tops[-1], 0.045, materials["metal"])


def create_upper_landing(materials: dict[str, bpy.types.Material]) -> None:
    """给通往二层的楼梯补齐可见落地环境，避免全景直接看到空世界背景。"""
    rounded_box(
        "upper-landing-floor",
        (0.72, 1.58, 0.14),
        (1.72, 1.22, 2.72),
        materials["floor"],
        bevel=0.012,
    )
    rounded_box(
        "upper-landing-north-wall",
        (4.34, 0.18, 1.72),
        (0.0, 2.05, 3.58),
        materials["plaster"],
        bevel=0.018,
    )
    rounded_box(
        "upper-landing-east-wall",
        (0.18, 1.74, 1.72),
        (2.08, 1.2, 3.58),
        materials["plaster"],
        bevel=0.018,
    )
    rounded_box(
        "upper-landing-ceiling",
        (4.34, 1.74, 0.12),
        (0.0, 1.2, 4.46),
        materials["plaster"],
        bevel=0.012,
    )
    rounded_box(
        "upper-landing-cove",
        (2.8, 0.035, 0.016),
        (0.1, 1.95, 4.32),
        materials["warm-emission"],
        bevel=0.006,
    )
    add_area_light(
        "upper-landing-fill",
        (0.3, 1.3, 4.2),
        (0.35, 1.35, 2.75),
        (1.0, 0.92, 0.84),
        260,
        2.6,
        "RECTANGLE",
        1.2,
    )


def create_media_wall(materials: dict[str, bpy.types.Material]) -> None:
    rounded_box(
        "media-oak-panel",
        (1.72, 0.055, 1.68),
        (0.54, 1.825, 1.02),
        materials["oak"],
        bevel=0.008,
    )
    for index in range(11):
        rounded_box(
            f"media-slat-{index:02d}",
            (0.026, 0.04, 1.54),
            (-0.36 + index * 0.068, 1.785, 1.05),
            materials["dark-oak"],
            bevel=0.006,
        )
    rounded_box(
        "media-console",
        (1.86, 0.4, 0.32),
        (0.48, 1.5, 0.25),
        materials["oak"],
        bevel=0.045,
        segments=5,
    )
    for x in (-0.22, 0.48, 1.18):
        rounded_box(
            "console-groove",
            (0.012, 0.008, 0.24),
            (x, 1.294, 0.25),
            materials["shadow"],
            bevel=0.002,
        )
    tv = rounded_box(
        "television",
        (1.24, 0.045, 0.71),
        (0.54, 1.745, 1.24),
        materials["screen"],
        bevel=0.018,
        segments=5,
    )
    rounded_box(
        "tv-backlight",
        (1.32, 0.012, 0.79),
        (tv.location.x, 1.775, tv.location.z),
        materials["warm-emission"],
        bevel=0.028,
    )
    tv.location.y = 1.738
    cylinder("console-vase", 0.095, 0.28, (1.2, 1.36, 0.55), materials["ceramic"])
    rounded_box(
        "console-book-1",
        (0.34, 0.22, 0.028),
        (-0.1, 1.39, 0.44),
        materials["book-terracotta"],
        bevel=0.008,
    )
    rounded_box(
        "console-book-2",
        (0.3, 0.2, 0.025),
        (-0.08, 1.39, 0.475),
        materials["book-cream"],
        bevel=0.008,
        rotation=(0, 0, math.radians(-3)),
    )


def create_sofa(materials: dict[str, bpy.types.Material]) -> None:
    center_x = -0.28
    center_y = -1.02
    rounded_box(
        "sofa-recessed-plinth",
        (2.34, 0.72, 0.14),
        (center_x, center_y - 0.02, 0.18),
        materials["dark-oak"],
        bevel=0.035,
        segments=8,
    )
    soft_cushion(
        "sofa-upholstered-base",
        (2.52, 0.84, 0.24),
        (center_x, center_y, 0.34),
        materials["fabric"],
        bevel=0.08,
        noise_strength=0.002,
        sag=0.004,
    )
    cushion_width = 0.76
    for index in range(3):
        x = center_x + (index - 1) * 0.79
        soft_cushion(
            f"sofa-seat-{index + 1}",
            (cushion_width, 0.67, 0.19),
            (x, center_y + 0.1, 0.55),
            materials["fabric"],
            bevel=0.06,
            noise_strength=0.004,
            sag=0.018 + index * 0.002,
        )
        soft_cushion(
            f"sofa-back-{index + 1}",
            (cushion_width, 0.19, 0.64),
            (x, center_y - 0.31, 0.91),
            materials["fabric"],
            bevel=0.06,
            rotation=(math.radians(-5), 0, 0),
            noise_strength=0.0045,
            sag=0.014 + index * 0.001,
            sag_axis="Y",
        )
        back_piping = piping_loop(
            f"sofa-back-piping-{index + 1}",
            rounded_rectangle_points(
                (0.0, 0.102, 0.0),
                cushion_width - 0.04,
                0.64 - 0.04,
                0.055,
                "XZ",
            ),
            materials["seam"],
            0.003,
        )
        back_piping.location = (x, center_y - 0.31, 0.91)
        back_piping.rotation_euler = (math.radians(-5), 0, 0)
    for x in (center_x - 1.23, center_x + 1.23):
        soft_cushion(
            "sofa-arm",
            (0.2, 0.83, 0.54),
            (x, center_y - 0.01, 0.61),
            materials["fabric"],
            bevel=0.065,
            noise_strength=0.003,
            sag=0.005,
            sag_axis="Y",
        )

    pillow = soft_cushion(
        "sofa-pillow",
        (0.52, 0.15, 0.49),
        (center_x + 0.86, center_y - 0.1, 0.86),
        materials["accent-fabric"],
        rotation=(math.radians(-11), 0, math.radians(11)),
        bevel=0.09,
        noise_strength=0.006,
        sag=0.018,
        sag_axis="Y",
    )
    pillow_piping = piping_loop(
        "sofa-pillow-piping",
        rounded_rectangle_points((0.0, 0.078, 0.0), 0.47, 0.44, 0.08, "XZ"),
        materials["seam"],
        0.0045,
    )
    pillow_piping.location = pillow.location
    pillow_piping.rotation_euler = pillow.rotation_euler


def create_rug_and_table(
    materials: dict[str, bpy.types.Material],
    asset_directory: Path,
) -> None:
    rounded_box(
        "natural-rug",
        (2.72, 1.55, 0.035),
        (-0.08, -0.32, 0.028),
        materials["rug"],
        bevel=0.028,
        segments=5,
    )
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(
        filepath=str(
            asset_directory
            / "models"
            / "modern-coffee-table-01"
            / "modern_coffee_table_01_4k.gltf"
        )
    )
    imported = [
        obj
        for obj in bpy.data.objects
        if obj not in before and obj.type in {"MESH", "EMPTY"}
    ]
    if not imported:
        raise RuntimeError("现代茶几未导入任何对象")
    for obj in imported:
        obj.name = f"modern-coffee-table-01-{obj.name}"
        obj.location = (-0.02, -0.08, 0.0)
        obj.rotation_euler[2] = math.radians(90)
    rounded_box(
        "coffee-book",
        (0.32, 0.23, 0.025),
        (-0.18, -0.1, 0.405),
        materials["book-cream"],
        bevel=0.008,
        rotation=(0, 0, math.radians(8)),
    )
    cylinder("coffee-vase", 0.07, 0.18, (0.22, -0.07, 0.49), materials["ceramic"])


def create_side_elements(
    materials: dict[str, bpy.types.Material],
) -> None:
    cylinder("floor-lamp-base", 0.18, 0.035, (-1.75, -1.48, 0.03), materials["metal"])
    cylinder("floor-lamp-stem", 0.018, 1.55, (-1.75, -1.48, 0.79), materials["metal"], 32)
    bpy.ops.mesh.primitive_cone_add(
        vertices=64,
        radius1=0.28,
        radius2=0.17,
        depth=0.38,
        location=(-1.75, -1.48, 1.66),
    )
    shade = bpy.context.object
    shade.name = "floor-lamp-shade"
    assign(shade, materials["lamp-shade"])
    add_point_light(
        "floor-lamp-light",
        (-1.75, -1.48, 1.55),
        (1.0, 0.76, 0.58),
        75,
        2.8,
    )

    rounded_box(
        "west-art-frame",
        (0.055, 0.78, 0.92),
        (-1.91, -0.62, 1.52),
        materials["dark-oak"],
        bevel=0.018,
        segments=6,
    )
    rounded_box(
        "west-art-canvas",
        (0.025, 0.69, 0.83),
        (-1.875, -0.62, 1.52),
        materials["art-linen"],
        bevel=0.012,
        segments=5,
    )
    rounded_box(
        "west-art-relief-vertical",
        (0.015, 0.2, 0.55),
        (-1.855, -0.74, 1.53),
        materials["art-clay"],
        bevel=0.08,
        rotation=(math.radians(8), 0, math.radians(-10)),
        segments=8,
    )
    rounded_box(
        "west-art-relief-horizontal",
        (0.016, 0.42, 0.16),
        (-1.845, -0.49, 1.35),
        materials["book-cream"],
        bevel=0.065,
        rotation=(math.radians(-7), 0, math.radians(5)),
        segments=8,
    )


def add_area_light(
    name: str,
    location: tuple[float, float, float],
    target: tuple[float, float, float],
    color: tuple[float, float, float],
    energy: float,
    size: float,
    shape: str = "RECTANGLE",
    size_y: float | None = None,
) -> bpy.types.Object:
    data = bpy.data.lights.new(name, "AREA")
    data.color = color
    data.energy = energy
    data.shape = shape
    data.size = size
    if size_y is not None:
        data.size_y = size_y
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    point_at(obj, Vector(target))
    return obj


def add_point_light(
    name: str,
    location: tuple[float, float, float],
    color: tuple[float, float, float],
    energy: float,
    radius: float,
) -> bpy.types.Object:
    data = bpy.data.lights.new(name, "POINT")
    data.color = color
    data.energy = energy
    data.shadow_soft_size = 0.18
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    data.cutoff_distance = radius
    return obj


def point_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def create_ceiling_lights(materials: dict[str, bpy.types.Material]) -> None:
    for index, (x, y, width, depth) in enumerate(
        (
            (0.0, -1.47, 3.45, 0.035),
            (-1.72, -0.1, 0.035, 2.7),
            (1.72, -0.1, 0.035, 2.7),
        )
    ):
        rounded_box(
            f"cove-strip-{index}",
            (width, depth, 0.016),
            (x, y, 2.72),
            materials["warm-emission"],
            bevel=0.006,
        )
    add_area_light(
        "south-cove",
        (0.0, -1.35, 2.68),
        (0.0, -0.2, 0.4),
        (1.0, 0.9, 0.82),
        210,
        3.2,
        "RECTANGLE",
        0.2,
    )
    add_area_light(
        "corridor-key",
        (0.0, -2.25, 2.25),
        (0.0, 0.35, 0.9),
        (1.0, 0.94, 0.9),
        360,
        3.4,
        "RECTANGLE",
        1.2,
    )
    add_area_light(
        "stair-fill",
        (0.15, 1.15, 2.52),
        (0.3, 1.1, 0.75),
        (1.0, 0.9, 0.8),
        180,
        2.2,
    )
    for side, x, target_x in (
        ("west", -2.52, -2.96),
        ("east", 2.52, 2.96),
    ):
        add_area_light(
            f"{side}-adjacent-room-fill",
            (x, 0.55, 2.15),
            (target_x, 0.55, 1.0),
            (1.0, 0.9, 0.8),
            230,
            1.3,
            "RECTANGLE",
            1.1,
        )
    for index, (x, y) in enumerate(((-1.15, -0.55), (1.15, -0.55), (-1.15, 0.65), (1.15, 0.65))):
        cylinder(
            f"downlight-trim-{index}",
            0.052,
            0.018,
            (x, y, 2.72),
            materials["metal"],
            48,
        )
        data = bpy.data.lights.new(f"downlight-{index}", "SPOT")
        data.color = (1.0, 0.9, 0.82)
        data.energy = 46
        data.spot_size = math.radians(58)
        data.spot_blend = 0.55
        data.shadow_soft_size = 0.12
        obj = bpy.data.objects.new(data.name, data)
        bpy.context.collection.objects.link(obj)
        obj.location = (x, y, 2.68)
        point_at(obj, Vector((x, y, 0.0)))


def create_materials(asset_directory: Path) -> dict[str, bpy.types.Material]:
    materials = {
        "floor": textured_material(
            "M_Floor_4K",
            asset_directory / "materials/wood-floor/wood_floor_diff_4k.jpg",
            asset_directory / "materials/wood-floor/wood_floor_nor_gl_4k.jpg",
            asset_directory / "materials/wood-floor/wood_floor_rough_4k.jpg",
            "#D7B594",
            (2.35, 2.3, 1.0),
            0.52,
            0.88,
        ),
        "plaster": textured_material(
            "M_Painted_Plaster_4K",
            asset_directory / "materials/painted-plaster/painted_plaster_wall_diff_4k.jpg",
            asset_directory / "materials/painted-plaster/painted_plaster_wall_nor_gl_4k.jpg",
            asset_directory / "materials/painted-plaster/painted_plaster_wall_rough_4k.jpg",
            "#F3EBDD",
            (1.7, 1.7, 1.7),
            0.08,
            0.92,
            False,
        ),
        "fabric": textured_material(
            "M_Sofa_Cotton_4K",
            asset_directory / "materials/cotton-jersey/cotton_jersey_diff_4k.jpg",
            asset_directory / "materials/cotton-jersey/cotton_jersey_nor_gl_4k.jpg",
            asset_directory / "materials/cotton-jersey/cotton_jersey_rough_4k.jpg",
            "#8C7667",
            (5.0, 5.0, 5.0),
            0.38,
            0.96,
            False,
        ),
        "accent-fabric": textured_material(
            "M_Accent_Cotton_4K",
            asset_directory / "materials/cotton-jersey/cotton_jersey_diff_4k.jpg",
            asset_directory / "materials/cotton-jersey/cotton_jersey_nor_gl_4k.jpg",
            asset_directory / "materials/cotton-jersey/cotton_jersey_rough_4k.jpg",
            "#67493A",
            (5.5, 5.5, 5.5),
            0.38,
            0.96,
            False,
        ),
        "light-fabric": textured_material(
            "M_Light_Cotton_4K",
            asset_directory / "materials/cotton-jersey/cotton_jersey_diff_4k.jpg",
            asset_directory / "materials/cotton-jersey/cotton_jersey_nor_gl_4k.jpg",
            asset_directory / "materials/cotton-jersey/cotton_jersey_rough_4k.jpg",
            "#CDB9A2",
            (5.0, 5.0, 5.0),
            0.34,
            0.95,
            False,
        ),
        "throw": textured_material(
            "M_Throw_Cotton_4K",
            asset_directory / "materials/cotton-jersey/cotton_jersey_diff_4k.jpg",
            asset_directory / "materials/cotton-jersey/cotton_jersey_nor_gl_4k.jpg",
            asset_directory / "materials/cotton-jersey/cotton_jersey_rough_4k.jpg",
            "#C66F4E",
            (7.0, 7.0, 7.0),
            0.38,
            1.0,
            False,
        ),
        "rug": textured_material(
            "M_Natural_Rug_4K",
            asset_directory / "materials/natural-rug/curly_teddy_natural_diff_4k.jpg",
            asset_directory / "materials/natural-rug/curly_teddy_natural_nor_gl_4k.jpg",
            asset_directory / "materials/natural-rug/curly_teddy_natural_rough_4k.jpg",
            "#D7C4AA",
            (6.8, 4.6, 1.0),
            0.8,
            1.0,
        ),
        "oak": textured_material(
            "M_Oak_Veneer_4K",
            asset_directory / "materials/oak-veneer/oak_veneer_01_diff_4k.jpg",
            asset_directory / "materials/oak-veneer/oak_veneer_01_nor_gl_4k.jpg",
            asset_directory / "materials/oak-veneer/oak_veneer_01_rough_4k.jpg",
            "#C79C6B",
            (2.2, 2.2, 2.2),
            0.48,
            0.9,
        ),
    }
    materials.update(
        {
            "dark-oak": principled_material("M_Dark_Oak", "#3C261A", 0.32),
            "metal": principled_material("M_Brushed_Bronze", "#4A3427", 0.28, 0.82),
            "trim": principled_material("M_Warm_Trim", "#F4EBDD", 0.45),
            "shadow": principled_material("M_Shadow_Groove", "#211A16", 0.52),
            "screen": principled_material("M_TV_Screen", "#080909", 0.12, 0.18),
            "stone": principled_material("M_Travertine", "#A88A6E", 0.42),
            "ceramic": principled_material("M_Ceramic", "#D9C8AE", 0.22),
            "leaf": principled_material("M_Olive_Leaf", "#394F31", 0.62),
            "lamp-shade": principled_material("M_Linen_Shade", "#DCC7A9", 0.78),
            "book-terracotta": principled_material("M_Book_Terracotta", "#8D4430", 0.62),
            "book-cream": principled_material("M_Book_Cream", "#D6C6AD", 0.7),
            "seam": principled_material("M_Sofa_Seam", "#8C7667", 0.78),
            "art-linen": principled_material("M_Art_Linen", "#CFC0A8", 0.72),
            "art-clay": principled_material("M_Art_Clay", "#8B4A32", 0.62),
            "warm-emission": emission_material("M_Warm_Emission", "#FFD2A0", 4.0),
        }
    )
    screen_bsdf = materials["screen"].node_tree.nodes.get("Principled BSDF")
    screen_bsdf.inputs["Coat Weight"].default_value = 0.35
    stone_bsdf = materials["stone"].node_tree.nodes.get("Principled BSDF")
    stone_bsdf.inputs["Coat Weight"].default_value = 0.12
    return materials


def configure_world(asset_directory: Path) -> None:
    world = bpy.data.worlds.new("Warm Minimal World")
    world.use_nodes = True
    bpy.context.scene.world = world
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputWorld")
    environment = nodes.new("ShaderNodeTexEnvironment")
    environment.image = image(asset_directory / "environment/studio_small_09_4k.hdr")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Rotation"].default_value[2] = math.radians(32)
    coordinates = nodes.new("ShaderNodeTexCoord")
    background = nodes.new("ShaderNodeBackground")
    background.inputs["Strength"].default_value = 0.16
    visible = nodes.new("ShaderNodeBackground")
    visible.inputs["Color"].default_value = hex_color("#8A7E73")
    visible.inputs["Strength"].default_value = 0.34
    light_path = nodes.new("ShaderNodeLightPath")
    mix = nodes.new("ShaderNodeMixShader")
    links.new(coordinates.outputs["Generated"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], environment.inputs["Vector"])
    links.new(environment.outputs["Color"], background.inputs["Color"])
    links.new(light_path.outputs["Is Camera Ray"], mix.inputs["Fac"])
    links.new(background.outputs["Background"], mix.inputs[1])
    links.new(visible.outputs["Background"], mix.inputs[2])
    links.new(mix.outputs["Shader"], output.inputs["Surface"])


def configure_cycles(profile: dict[str, Any]) -> str:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = int(profile["samples"])
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.08 if profile["samples"] <= 32 else 0.008
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 10
    scene.cycles.diffuse_bounces = 5
    scene.cycles.glossy_bounces = 5
    scene.cycles.transmission_bounces = 6
    scene.cycles.transparent_max_bounces = 8
    scene.cycles.sample_clamp_indirect = 3.0
    device = "CPU"
    try:
        preferences = bpy.context.preferences.addons["cycles"].preferences
        preferences.compute_device_type = "METAL"
        preferences.refresh_devices()
        metal_devices = [item for item in preferences.devices if item.type == "METAL"]
        for item in preferences.devices:
            item.use = item.type == "METAL"
        if metal_devices:
            scene.cycles.device = "GPU"
            device = "METAL:" + ", ".join(item.name for item in metal_devices)
    except Exception:
        scene.cycles.device = "CPU"
    scene.render.resolution_x = int(profile["width"])
    scene.render.resolution_y = int(profile["height"])
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "16" if profile["width"] >= 3840 else "8"
    scene.render.film_transparent = False
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = -1.0
    scene.render.use_file_extension = True
    return device


CAMERAS = {
    "hero": {
        "location": (4.6, 1.18, 1.58),
        "target": (0.32, 0.08, 0.86),
        "lens": 42,
    },
    "seating": {
        "location": (-2.72, 1.28, 1.48),
        "target": (0.06, -0.1, 0.8),
        "lens": 40,
    },
    "wide": {
        "location": (-0.42, -3.72, 1.5),
        "target": (0.08, 0.5, 1.02),
        "lens": 34,
    },
    "layout": {
        "location": (0.0, 0.0, 8.0),
        "target": (0.0, 0.0, 0.0),
        "lens": 50,
    },
    "panorama": {
        "location": (0.22, 0.18, 1.52),
        "target": (0.0, 1.0, 1.45),
        "lens": 18,
    },
}


def configure_view_visibility(view: str) -> None:
    photographic_cut = {
        "hero": (
            "east-wall-",
            "east-door-jamb",
            "east-door-head",
            "baseboard-east",
            "east-adjacent-backdrop",
        ),
        "seating": (
            "west-wall-north",
            "west-door-jamb",
            "west-door-head",
            "baseboard-west-north",
        ),
        "layout": (
            "ceiling-",
            "corridor-ceiling",
            "upper-landing-ceiling",
            "west-adjacent-ceiling",
            "east-adjacent-ceiling",
        ),
    }
    for obj in bpy.context.scene.objects:
        obj.hide_render = False
    for prefix in photographic_cut.get(view, ()):
        for obj in bpy.context.scene.objects:
            if obj.name.startswith(prefix):
                obj.hide_render = True


def configure_camera(view: str) -> bpy.types.Object:
    settings = CAMERAS[view]
    camera_data = bpy.data.cameras.get("Cinematic Camera")
    if camera_data is None:
        camera_data = bpy.data.cameras.new("Cinematic Camera")
    camera = bpy.data.objects.get("Cinematic Camera")
    if camera is None:
        camera = bpy.data.objects.new("Cinematic Camera", camera_data)
        bpy.context.collection.objects.link(camera)
    camera.location = settings["location"]
    camera.data.lens = settings["lens"]
    camera.data.sensor_width = 36
    camera.data.dof.use_dof = view not in {"layout", "panorama"}
    camera.data.dof.focus_distance = (Vector(settings["target"]) - camera.location).length
    camera.data.dof.aperture_fstop = 5.6
    point_at(camera, Vector(settings["target"]))
    if view == "panorama":
        camera.data.type = "PANO"
        camera.data.panorama_type = "EQUIRECTANGULAR"
    else:
        camera.data.type = "PERSP"
    bpy.context.scene.camera = camera
    return camera


def build_scene(spec: dict[str, Any], asset_directory: Path) -> None:
    clear_scene()
    materials = create_materials(asset_directory)
    create_architecture(spec, materials)
    create_staircase(materials)
    create_upper_landing(materials)
    create_media_wall(materials)
    create_rug_and_table(materials, asset_directory)
    create_sofa(materials)
    create_side_elements(materials)
    create_ceiling_lights(materials)
    configure_world(asset_directory)


def main() -> None:
    started = time.monotonic()
    args = parse_arguments()
    spec = validate_inputs(args.spec, args.asset_directory)
    args.output_directory.mkdir(parents=True, exist_ok=True)
    build_scene(spec, args.asset_directory)
    profile = spec["outputs"][args.profile]
    device = configure_cycles(profile)
    panorama_profile = args.profile in {"panorama-preview", "panorama"}
    views = args.view or (["panorama"] if panorama_profile else ["hero"])
    if panorama_profile and views != ["panorama"]:
        raise ValueError("全景档只能使用 panorama 视角")
    output_blend = args.output_blend or args.output_directory / "warm-minimal-living.blend"
    output_blend.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend), check_existing=False)

    rendered: list[dict[str, Any]] = []
    for view in views:
        configure_view_visibility(view)
        configure_camera(view)
        output = args.output_directory / f"{args.profile}-{view}.png"
        bpy.context.scene.render.filepath = str(output)
        view_started = time.monotonic()
        bpy.ops.render.render(write_still=True)
        rendered.append(
            {
                "view": view,
                "path": str(output),
                "bytes": output.stat().st_size,
                "sha256": sha256(output),
                "seconds": round(time.monotonic() - view_started, 3),
            }
        )

    report = {
        "schemaVersion": "1.0",
        "sceneId": spec["id"],
        "sceneVersion": spec["version"],
        "profile": args.profile,
        "device": device,
        "blend": str(output_blend),
        "rendered": rendered,
        "totalSeconds": round(time.monotonic() - started, 3),
    }
    (args.output_directory / f"{args.profile}-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
