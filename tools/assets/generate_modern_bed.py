from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector


ASSET_ID = "project-modern-upholstered-bed"
GENERATOR_VERSION = "modern-upholstered-bed-v2"
TEXTURE_SIZE = 512
COTTON_JERSEY_PAGE = "https://polyhaven.com/a/cotton_jersey"
COTTON_JERSEY_FILES = {
    "diffuse": (
        "cotton_jersey_diff_1k.jpg",
        581360,
        "d2f4493fdd48634b50d40f810ce9deb7",
        "https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/cotton_jersey/cotton_jersey_diff_1k.jpg",
    ),
    "normal": (
        "cotton_jersey_nor_gl_1k.jpg",
        678670,
        "2dcc9dda3b726477f607c808e52f1833",
        "https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/cotton_jersey/cotton_jersey_nor_gl_1k.jpg",
    ),
    "roughness": (
        "cotton_jersey_rough_1k.jpg",
        865264,
        "ac691d215d3aca34dcd6ea2d03937286",
        "https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/cotton_jersey/cotton_jersey_rough_1k.jpg",
    ),
}


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


def download_textures(directory: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for role, (filename, expected_bytes, expected_md5, url) in COTTON_JERSEY_FILES.items():
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "3d-floorplan-platform/0.1 (asset-generator)"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()
        if len(content) != expected_bytes or hashlib.md5(content).hexdigest() != expected_md5:
            raise RuntimeError(f"cotton jersey source integrity failed: {filename}")
        path = directory / filename
        path.write_bytes(content)
        result[role] = path
    return result


def textile_material(name: str, paths: dict[str, Path]) -> bpy.types.Material:
    value = material(name, (0.78, 0.67, 0.59, 1), 0.82)
    value.use_backface_culling = False
    nodes = value.node_tree.nodes
    links = value.node_tree.links
    principled = nodes.get("Principled BSDF")
    if principled is None:
        raise RuntimeError("Blender Principled BSDF is unavailable")

    diffuse = bpy.data.images.load(str(paths["diffuse"]), check_existing=False)
    normal = bpy.data.images.load(str(paths["normal"]), check_existing=False)
    roughness = bpy.data.images.load(str(paths["roughness"]), check_existing=False)
    for image in (diffuse, normal, roughness):
        image.scale(TEXTURE_SIZE, TEXTURE_SIZE)
        image.pack()
    normal.colorspace_settings.name = "Non-Color"
    roughness.colorspace_settings.name = "Non-Color"

    diffuse_node = nodes.new("ShaderNodeTexImage")
    diffuse_node.name = "cotton-jersey-diffuse"
    diffuse_node.image = diffuse
    normal_node = nodes.new("ShaderNodeTexImage")
    normal_node.name = "cotton-jersey-normal"
    normal_node.image = normal
    roughness_node = nodes.new("ShaderNodeTexImage")
    roughness_node.name = "cotton-jersey-roughness"
    roughness_node.image = roughness
    normal_map = nodes.new("ShaderNodeNormalMap")
    normal_map.inputs["Strength"].default_value = 0.56
    links.new(diffuse_node.outputs["Color"], principled.inputs["Base Color"])
    links.new(roughness_node.outputs["Color"], principled.inputs["Roughness"])
    links.new(normal_node.outputs["Color"], normal_map.inputs["Color"])
    links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])
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


def smooth_step(value: float) -> float:
    clamped = max(0.0, min(1.0, value))
    return clamped * clamped * (3 - 2 * clamped)


def draped_textile(
    name: str,
    size: tuple[float, float],
    location: tuple[float, float, float],
    assigned_material: bpy.types.Material,
    *,
    segments: tuple[int, int] = (36, 42),
    side_drop: float = 0.1,
    foot_drop: float = 0.08,
    fold_height: float = 0.025,
) -> bpy.types.Object:
    width, depth = size
    x_segments, y_segments = segments
    vertices: list[tuple[float, float, float]] = []
    texture_coordinates: list[tuple[float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for y_index in range(y_segments + 1):
        v = y_index / y_segments
        y = (v - 0.5) * depth
        for x_index in range(x_segments + 1):
            u = x_index / x_segments
            x = (u - 0.5) * width
            side = smooth_step((abs(u - 0.5) - 0.4) / 0.1)
            foot = smooth_step((0.16 - v) / 0.16)
            crown = math.sin(math.pi * u) * math.sin(math.pi * v) * 0.035
            long_folds = math.sin(u * math.pi * 10 + v * 1.7) * fold_height
            cross_folds = math.sin(v * math.pi * 7 + u * 2.1) * fold_height * 0.34
            z = crown + long_folds + cross_folds - side * side_drop - foot * foot_drop
            vertices.append((x, y, z))
            texture_coordinates.append((u * 3.2, v * 3.6))
    stride = x_segments + 1
    for y_index in range(y_segments):
        for x_index in range(x_segments):
            lower_left = y_index * stride + x_index
            faces.append(
                (
                    lower_left,
                    lower_left + 1,
                    lower_left + stride + 1,
                    lower_left + stride,
                )
            )
    mesh = bpy.data.meshes.new(f"{name}-mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        polygon.use_smooth = True
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            uv_layer.data[loop_index].uv = texture_coordinates[vertex_index]
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    obj.data.materials.append(assigned_material)
    solidify = obj.modifiers.new(name="textile-thickness", type="SOLIDIFY")
    solidify.thickness = 0.022
    solidify.offset = -0.25
    bevel = obj.modifiers.new(name="soft-cloth-edge", type="BEVEL")
    bevel.width = 0.012
    bevel.segments = 2
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    return obj


def quantize_mesh(obj: bpy.types.Object, steps_per_unit: int = 4096) -> None:
    """Remove sub-micron modifier noise so repeated GLB exports are byte-stable."""
    if obj.type != "MESH":
        return
    for vertex in obj.data.vertices:
        vertex.co = tuple(round(value * steps_per_unit) / steps_per_unit for value in vertex.co)
    for uv_layer in obj.data.uv_layers:
        for entry in uv_layer.data:
            entry.uv = tuple(round(value * steps_per_unit) / steps_per_unit for value in entry.uv)
    obj.data.update()


def bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    if not points:
        raise RuntimeError("generated bed has no bounds")
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def generate(texture_paths: dict[str, Path]) -> list[bpy.types.Object]:
    upholstery = textile_material("cotton-jersey-upholstery", texture_paths)
    linen = material("soft-ivory-mattress", (0.83, 0.79, 0.7, 1), 0.82)
    accent = material("clay-woven-throw", (0.36, 0.16, 0.085, 1), 0.86)
    accent.use_backface_culling = False
    wood = material("dark-oak-legs", (0.09, 0.045, 0.024, 1), 0.5)
    gap = material("headboard-shadow-gap", (0.045, 0.025, 0.018, 1), 0.58)
    objects: list[bpy.types.Object] = []

    objects.append(rounded_box("platform", (2.02, 2.18, 0.28), (0, -0.04, 0.26), upholstery, 0.09))
    objects.append(rounded_box("mattress", (1.88, 1.98, 0.26), (0, -0.08, 0.5), linen, 0.11))
    objects.append(
        draped_textile(
            "sculpted-duvet",
            (1.92, 1.58),
            (0, -0.25, 0.72),
            upholstery,
            side_drop=0.12,
            foot_drop=0.1,
            fold_height=0.023,
        )
    )
    objects.append(
        draped_textile(
            "folded-clay-throw",
            (1.94, 0.47),
            (0, -0.75, 0.81),
            accent,
            segments=(36, 14),
            side_drop=0.09,
            foot_drop=0.035,
            fold_height=0.032,
        )
    )

    objects.append(rounded_box("headboard-core", (2.1, 0.15, 1.22), (0, 1.02, 0.77), upholstery, 0.1))
    for index, x in enumerate((-0.84, -0.42, 0, 0.42, 0.84)):
        objects.append(
            rounded_box(
                f"headboard-channel-{index + 1}",
                (0.355, 0.075, 1.04),
                (x, 0.91, 0.79),
                upholstery,
                0.075,
            )
        )
    for index, x in enumerate((-0.63, -0.21, 0.21, 0.63), start=1):
        objects.append(
            rounded_box(
                f"headboard-gap-{index}",
                (0.018, 0.018, 0.94),
                (x, 0.865, 0.79),
                gap,
                0.006,
            )
        )

    pillow_specs = (
        ("back-pillow-left", (0.8, 0.46, 0.19), (-0.43, 0.61, 0.83), (-10, 2, -6)),
        ("back-pillow-right", (0.8, 0.46, 0.19), (0.43, 0.61, 0.83), (-10, -2, 6)),
        ("front-pillow-left", (0.6, 0.38, 0.17), (-0.31, 0.35, 0.88), (-4, 3, -4)),
        ("front-pillow-right", (0.6, 0.38, 0.17), (0.31, 0.35, 0.88), (-4, -3, 4)),
    )
    for name, size, location, degrees in pillow_specs:
        objects.append(
            rounded_box(
                name,
                size,
                location,
                upholstery,
                0.12,
                rotation=tuple(math.radians(value) for value in degrees),
            )
        )
    objects.append(
        rounded_box(
            "lumbar-cushion",
            (0.78, 0.24, 0.2),
            (0, 0.18, 0.93),
            accent,
            0.095,
            rotation=(math.radians(-3), 0, 0),
        )
    )
    for x in (-0.82, 0.82):
        for y in (-0.9, 0.77):
            objects.append(rounded_box(f"leg-{x}-{y}", (0.1, 0.1, 0.18), (x, y, 0.09), wood, 0.02))

    for obj in objects:
        quantize_mesh(obj)
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
    with tempfile.TemporaryDirectory(prefix="project-modern-bed-") as temporary:
        texture_paths = download_textures(Path(temporary))
        objects = generate(texture_paths)
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
        "textureSourcePage": COTTON_JERSEY_PAGE,
        "textureSize": TEXTURE_SIZE,
        "textureSources": [
            {
                "role": role,
                "file": filename,
                "bytes": expected_bytes,
                "md5": expected_md5,
                "url": url,
            }
            for role, (filename, expected_bytes, expected_md5, url) in COTTON_JERSEY_FILES.items()
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
