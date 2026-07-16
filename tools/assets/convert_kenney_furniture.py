from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector


SOURCE_PACKAGE_SHA256 = "e67652d0932cee41683f74711c03d3e192a2af9979ef8e6b237711f5482d46b0"
ASSETS = {
    "kenney-bed-double": "bedDouble",
    "kenney-dining-chair": "chair",
    "kenney-dining-table-round": "tableRound",
    "kenney-lounge-sofa": "loungeDesignSofa",
    "kenney-coffee-table": "tableCoffee",
}


def parse_arguments() -> argparse.Namespace:
    arguments = __import__("sys").argv
    values = arguments[arguments.index("--") + 1 :] if "--" in arguments else []
    parser = argparse.ArgumentParser(description="Convert audited Kenney OBJ furniture to GLB")
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args(values)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    if not points:
        raise RuntimeError("source OBJ contains no mesh bounds")
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def convert(asset_id: str, source_name: str, source_root: Path, output: Path) -> dict[str, Any]:
    source = source_root / f"{source_name}.obj"
    material = source_root / f"{source_name}.mtl"
    if not source.is_file() or not material.is_file():
        raise FileNotFoundError(f"missing audited source files for {source_name}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.obj_import(filepath=str(source), forward_axis="NEGATIVE_Z", up_axis="Y")
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"{source_name} imported without meshes")

    for obj in meshes:
        obj.scale *= 2
    bpy.context.view_layer.update()
    minimum, maximum = bounds(meshes)
    offset = Vector((-(minimum.x + maximum.x) / 2, -(minimum.y + maximum.y) / 2, -minimum.z))
    for obj in meshes:
        obj.location += offset
        obj["catalogAssetId"] = asset_id
        obj["licenseSpdx"] = "CC0-1.0"
        obj["sourcePackageSha256"] = SOURCE_PACKAGE_SHA256
        obj.select_set(True)
    bpy.context.view_layer.update()
    normalized_minimum, normalized_maximum = bounds(meshes)

    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(output),
        export_format="GLB",
        export_yup=True,
        export_apply=True,
        use_selection=True,
        export_extras=True,
    )
    size = normalized_maximum - normalized_minimum
    return {
        "id": asset_id,
        "sourceEntry": f"Models/OBJ format/{source_name}.obj",
        "sourceSha256": sha256(source),
        "sourceMaterialSha256": sha256(material),
        "deliveryFile": output.name,
        "deliverySha256": sha256(output),
        "deliveryBytes": output.stat().st_size,
        "canonicalSize": [round(size.x, 6), round(size.z, 6), round(size.y, 6)],
        "meshes": len(meshes),
    }


def main() -> None:
    args = parse_arguments()
    reports = [
        convert(asset_id, source_name, args.source_root, args.output_directory / f"{asset_id}.glb")
        for asset_id, source_name in ASSETS.items()
    ]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps({"sourcePackageSha256": SOURCE_PACKAGE_SHA256, "assets": reports}, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
