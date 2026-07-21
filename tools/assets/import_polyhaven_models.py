from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector


ASSETS: dict[str, dict[str, Any]] = {
    "polyhaven-modern-arm-chair-01": {
        "source_id": "polyhaven-modern-arm-chair-01-1k",
        "source_name": "Modern Arm Chair 01",
        "source_page": "https://polyhaven.com/a/modern_arm_chair_01",
        "author": "Vibrant Nordic",
        "entry": "modern_arm_chair_01_1k.gltf",
        "files": {
            "modern_arm_chair_01_1k.gltf": (5121, "a5ce303bc2962fe98b733fcdfa5a842b", "https://dl.polyhaven.org/file/ph-assets/Models/gltf/1k/modern_arm_chair_01/modern_arm_chair_01_1k.gltf"),
            "modern_arm_chair_01.bin": (240728, "5a8f2ea1c79ea484140e484b2a621670", "https://dl.polyhaven.org/file/ph-assets/Models/gltf/8k/modern_arm_chair_01/modern_arm_chair_01.bin"),
            "textures/modern_arm_chair_01_legs_diff_1k.jpg": (460937, "778f1897e07ff81b2bc338f3d463ad1f", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/modern_arm_chair_01/modern_arm_chair_01_legs_diff_1k.jpg"),
            "textures/modern_arm_chair_01_legs_nor_gl_1k.jpg": (560864, "7cece7eccf75588af5b5df9b095d2c97", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/modern_arm_chair_01/modern_arm_chair_01_legs_nor_gl_1k.jpg"),
            "textures/modern_arm_chair_01_legs_arm_1k.jpg": (577931, "9c69cb001df175bddf6d1c2436567fb7", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/modern_arm_chair_01/modern_arm_chair_01_legs_arm_1k.jpg"),
            "textures/modern_arm_chair_01_pillow_diff_1k.jpg": (228851, "2e4f64c633c3cb1656ad3eabdb3f0607", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/modern_arm_chair_01/modern_arm_chair_01_pillow_diff_1k.jpg"),
            "textures/modern_arm_chair_01_pillow_nor_gl_1k.jpg": (302377, "6804f34108fcc755f0c84dd3c638270c", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/modern_arm_chair_01/modern_arm_chair_01_pillow_nor_gl_1k.jpg"),
            "textures/modern_arm_chair_01_pillow_arm_1k.jpg": (321223, "772495ddbf26ca3de4b31298f10113b9", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/modern_arm_chair_01/modern_arm_chair_01_pillow_arm_1k.jpg"),
        },
    },
    "polyhaven-sofa-01": {
        "source_id": "polyhaven-sofa-01-1k",
        "source_name": "Sofa 01",
        "source_page": "https://polyhaven.com/a/Sofa_01",
        "author": "Kirill Sannikov",
        "entry": "Sofa_01_1k.gltf",
        "files": {
            "Sofa_01_1k.gltf": (2636, "b5f8106d38a9e8dcb52b883663bbeed1", "https://dl.polyhaven.org/file/ph-assets/Models/gltf/1k/Sofa_01/Sofa_01_1k.gltf"),
            "Sofa_01.bin": (111264, "77b6d42bd17eed825d5d65c769c71f0c", "https://dl.polyhaven.org/file/ph-assets/Models/gltf/4k/Sofa_01/Sofa_01.bin"),
            "textures/Sofa_01_diff_1k.jpg": (134925, "a4d07c6c0fd696cb6fa4bd5bad1debc3", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/Sofa_01/Sofa_01_diff_1k.jpg"),
            "textures/Sofa_01_nor_gl_1k.jpg": (154517, "7e4aca2b86e09375d25182c7bd4580db", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/Sofa_01/Sofa_01_nor_gl_1k.jpg"),
            "textures/Sofa_01_arm_1k.jpg": (114593, "c7b757edd1f5fb506341be0063b9a3eb", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/Sofa_01/Sofa_01_arm_1k.jpg"),
        },
    },
    "polyhaven-modern-ceiling-lamp-01": {
        "source_id": "polyhaven-modern-ceiling-lamp-01-1k",
        "source_name": "Modern Ceiling Lamp 01",
        "source_page": "https://polyhaven.com/a/modern_ceiling_lamp_01",
        "author": "James Ray Cock",
        "entry": "modern_ceiling_lamp_01_1k.gltf",
        "files": {
            "modern_ceiling_lamp_01_1k.gltf": (6177, "b85c212ffcc2cb9c74b9e68f314fec3b", "https://dl.polyhaven.org/file/ph-assets/Models/gltf/1k/modern_ceiling_lamp_01/modern_ceiling_lamp_01_1k.gltf"),
            "modern_ceiling_lamp_01.bin": (146828, "48b86e7e6db78e6d3dfd85b765c3ab68", "https://dl.polyhaven.org/file/ph-assets/Models/gltf/8k/modern_ceiling_lamp_01/modern_ceiling_lamp_01.bin"),
            "textures/modern_ceiling_lamp_01_arm_1k.jpg": (124022, "6667aa4091a273a041715dccd3b83bc8", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/modern_ceiling_lamp_01/modern_ceiling_lamp_01_arm_1k.jpg"),
            "textures/modern_ceiling_lamp_01_diff_1k.jpg": (79705, "7197acc141761c4c417023b9fb58db95", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/modern_ceiling_lamp_01/modern_ceiling_lamp_01_diff_1k.jpg"),
            "textures/modern_ceiling_lamp_01_nor_gl_1k.jpg": (79333, "f3ebd90aa565968ce1faf25a03b1f912", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/modern_ceiling_lamp_01/modern_ceiling_lamp_01_nor_gl_1k.jpg"),
        },
    },
}


def parse_arguments() -> argparse.Namespace:
    arguments = __import__("sys").argv
    values = arguments[arguments.index("--") + 1 :] if "--" in arguments else []
    parser = argparse.ArgumentParser(description="Import audited Poly Haven 1K glTF models")
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args(values)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_files(asset: dict[str, Any], directory: Path) -> list[dict[str, Any]]:
    report: list[dict[str, Any]] = []
    for relative, (expected_bytes, expected_md5, url) in asset["files"].items():
        destination = directory / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=60) as response:
            content = response.read()
        if len(content) != expected_bytes or hashlib.md5(content).hexdigest() != expected_md5:
            raise RuntimeError(f"Poly Haven source integrity failed: {relative}")
        destination.write_bytes(content)
        report.append(
            {
                "path": relative,
                "url": url,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    return sorted(report, key=lambda item: item["path"])


def bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    if not points:
        raise RuntimeError("source glTF contains no mesh bounds")
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def convert(asset_id: str, asset: dict[str, Any], output: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"{asset_id}-") as temporary:
        source_directory = Path(temporary)
        source_files = download_files(asset, source_directory)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(source_directory / asset["entry"]), import_shading="NORMALS")
        imported = list(bpy.context.scene.objects)
        meshes = [obj for obj in imported if obj.type == "MESH"]
        if not meshes:
            raise RuntimeError(f"{asset_id} imported without meshes")
        minimum, maximum = bounds(meshes)
        offset = Vector((-(minimum.x + maximum.x) / 2, -(minimum.y + maximum.y) / 2, -minimum.z))
        roots = [obj for obj in imported if obj.parent not in imported]
        for root in roots:
            root.location += offset
        for obj in imported:
            obj["catalogAssetId"] = asset_id
            obj["licenseSpdx"] = "CC0-1.0"
            obj["sourceId"] = asset["source_id"]
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
            "sourceId": asset["source_id"],
            "sourceName": asset["source_name"],
            "sourcePage": asset["source_page"],
            "author": asset["author"],
            "sourceEntry": f"1k/{asset['entry']}",
            "sourceFiles": source_files,
            "deliveryFile": output.name,
            "deliverySha256": sha256(output),
            "deliveryBytes": output.stat().st_size,
            "canonicalSize": [round(size.x, 6), round(size.z, 6), round(size.y, 6)],
            "meshes": len(meshes),
            "materials": len(bpy.data.materials),
        }


def main() -> None:
    args = parse_arguments()
    reports = [
        convert(asset_id, asset, args.output_directory / f"{asset_id}.glb")
        for asset_id, asset in ASSETS.items()
    ]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"assets": reports}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
