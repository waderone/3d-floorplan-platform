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
    "polyhaven-modern-coffee-table-01": {
        "source_id": "polyhaven-modern-coffee-table-01-1k",
        "source_name": "Modern Coffee Table 01",
        "source_page": "https://polyhaven.com/a/modern_coffee_table_01",
        "author": "Amin",
        "entry": "modern_coffee_table_01_1k.gltf",
        "max_texture_size": 1024,
        "files": {
            "modern_coffee_table_01_1k.gltf": (2771, "f1c079ab5bc307630258cf3b40910511", "https://dl.polyhaven.org/file/ph-assets/Models/gltf/1k/modern_coffee_table_01/modern_coffee_table_01_1k.gltf"),
            "modern_coffee_table_01.bin": (154864, "6e8f65bff935af308eab9eff062f6daa", "https://dl.polyhaven.org/file/ph-assets/Models/gltf/8k/modern_coffee_table_01/modern_coffee_table_01.bin"),
            "textures/modern_coffee_table_01_diff_1k.jpg": (410569, "356014e027b59c21b3c99ac112e645f9", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/modern_coffee_table_01/modern_coffee_table_01_diff_1k.jpg"),
            "textures/modern_coffee_table_01_nor_gl_1k.jpg": (359134, "d263e6131abc518760d6771390bc5066", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/modern_coffee_table_01/modern_coffee_table_01_nor_gl_1k.jpg"),
            "textures/modern_coffee_table_01_rough_1k.jpg": (403959, "6ccbc448fa0e2bed32eac52511e84e2c", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/modern_coffee_table_01/modern_coffee_table_01_rough_1k.jpg"),
        },
    },
    "polyhaven-modern-wooden-cabinet": {
        "source_id": "polyhaven-modern-wooden-cabinet-1k",
        "source_name": "Modern Wooden Cabinet",
        "source_page": "https://polyhaven.com/a/modern_wooden_cabinet",
        "author": "Patrik Pangerl",
        "entry": "modern_wooden_cabinet_1k.gltf",
        "max_texture_size": 1024,
        "files": {
            "modern_wooden_cabinet_1k.gltf": (10960, "623406579e948eb75ff52ec1498085c8", "https://dl.polyhaven.org/file/ph-assets/Models/gltf/1k/modern_wooden_cabinet/modern_wooden_cabinet_1k.gltf"),
            "modern_wooden_cabinet.bin": (1170136, "0a619e6311e6b04b92e9f226f3d0978d", "https://dl.polyhaven.org/file/ph-assets/Models/gltf/8k/modern_wooden_cabinet/modern_wooden_cabinet.bin"),
            "textures/modern_wooden_cabinet_diff_1k.jpg": (670353, "9c7e897741dd9aea6382f04e710d739b", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/modern_wooden_cabinet/modern_wooden_cabinet_diff_1k.jpg"),
            "textures/modern_wooden_cabinet_nor_gl_1k.jpg": (430053, "62477103e44ac1b2746c9bb201f89e06", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/modern_wooden_cabinet/modern_wooden_cabinet_nor_gl_1k.jpg"),
            "textures/modern_wooden_cabinet_arm_1k.jpg": (574020, "bb821c89979d89ce2421df13af67fb07", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/modern_wooden_cabinet/modern_wooden_cabinet_arm_1k.jpg"),
        },
    },
    "polyhaven-potted-plant-04": {
        "source_id": "polyhaven-potted-plant-04-1k",
        "source_name": "Potted Plant 04",
        "source_page": "https://polyhaven.com/a/potted_plant_04",
        "author": "Rico Cilliers",
        "entry": "potted_plant_04_1k.gltf",
        "max_texture_size": 512,
        "files": {
            "potted_plant_04_1k.gltf": (7081, "077d481764145f6e5e256593aab427bb", "https://dl.polyhaven.org/file/ph-assets/Models/gltf/1k/potted_plant_04/potted_plant_04_1k.gltf"),
            "potted_plant_04.bin": (241800, "03774ca8e28e2aa30fb26cb68d5e0093", "https://dl.polyhaven.org/file/ph-assets/Models/gltf/8k/potted_plant_04/potted_plant_04.bin"),
            "textures/potted_plant_04_diff_1k.jpg": (577545, "4a72fb3667fd3686ca4014f6676f59c4", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/potted_plant_04/potted_plant_04_diff_1k.jpg"),
            "textures/potted_plant_04_nor_gl_1k.jpg": (817786, "1c0b87906fd92c7b7ce5508110976474", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/potted_plant_04/potted_plant_04_nor_gl_1k.jpg"),
            "textures/potted_plant_04_arm_1k.jpg": (478413, "ed0030c6085bba45b6f63f3043b0b237", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/potted_plant_04/potted_plant_04_arm_1k.jpg"),
        },
    },
    "polyhaven-hanging-picture-frame-01": {
        "source_id": "polyhaven-hanging-picture-frame-01-1k",
        "source_name": "Hanging Picture Frame 01",
        "source_page": "https://polyhaven.com/a/hanging_picture_frame_01",
        "author": "James Ray Cock",
        "entry": "hanging_picture_frame_01_1k.gltf",
        "max_texture_size": 512,
        "files": {
            "hanging_picture_frame_01_1k.gltf": (6495, "54726d9c81e19d8745b3d26d18b89c89", "https://dl.polyhaven.org/file/ph-assets/Models/gltf/1k/hanging_picture_frame_01/hanging_picture_frame_01_1k.gltf"),
            "hanging_picture_frame_01.bin": (86448, "ed2c512ea5e3dcdcfc70c53b4de24099", "https://dl.polyhaven.org/file/ph-assets/Models/gltf/8k/hanging_picture_frame_01/hanging_picture_frame_01.bin"),
            "textures/hanging_picture_frame_01_artwork_roughness_1k.jpg": (12684, "b8e5b8431b0c53b20d83ec0bcff51747", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/hanging_picture_frame_01/hanging_picture_frame_01_artwork_roughness_1k.jpg"),
            "textures/hanging_picture_frame_01_artwork_diff_1k.jpg": (44185, "bf926c376e335ac3272564924f9d4e52", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/hanging_picture_frame_01/hanging_picture_frame_01_artwork_diff_1k.jpg"),
            "textures/hanging_picture_frame_01_artwork_nor_gl_1k.jpg": (17259, "6c3858a15263cfd9621d88c2eabe9d71", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/hanging_picture_frame_01/hanging_picture_frame_01_artwork_nor_gl_1k.jpg"),
            "textures/hanging_picture_frame_01_arm_1k.jpg": (101751, "8d9dd625ec0705f3ac0a2ec2b402844e", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/hanging_picture_frame_01/hanging_picture_frame_01_arm_1k.jpg"),
            "textures/hanging_picture_frame_01_nor_gl_1k.jpg": (40281, "2ff7cca9a9b2918b5476d39c13592214", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/hanging_picture_frame_01/hanging_picture_frame_01_nor_gl_1k.jpg"),
            "textures/hanging_picture_frame_01_diff_1k.jpg": (88363, "4311cd03620cafa59976f9e8b7b26f88", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/hanging_picture_frame_01/hanging_picture_frame_01_diff_1k.jpg"),
        },
    },
    "polyhaven-ceramic-vase-01": {
        "source_id": "polyhaven-ceramic-vase-01-1k",
        "source_name": "Ceramic Vase 01",
        "source_page": "https://polyhaven.com/a/ceramic_vase_01",
        "author": "James Ray Cock",
        "entry": "ceramic_vase_01_1k.gltf",
        "max_texture_size": 512,
        "files": {
            "ceramic_vase_01_1k.gltf": (2706, "8f11b5472424578c2c505dee271a0868", "https://dl.polyhaven.org/file/ph-assets/Models/gltf/1k/ceramic_vase_01/ceramic_vase_01_1k.gltf"),
            "ceramic_vase_01.bin": (272656, "73f8a0f911f2d377e3b925b0ae9c7d4c", "https://dl.polyhaven.org/file/ph-assets/Models/gltf/8k/ceramic_vase_01/ceramic_vase_01.bin"),
            "textures/ceramic_vase_01_nor_gl_1k.jpg": (36504, "46081f52a4e9bb58d706477318627a22", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/ceramic_vase_01/ceramic_vase_01_nor_gl_1k.jpg"),
            "textures/ceramic_vase_01_diff_1k.jpg": (32351, "52337c4fedc46490476d46a8950e1d6b", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/ceramic_vase_01/ceramic_vase_01_diff_1k.jpg"),
            "textures/ceramic_vase_01_arm_1k.jpg": (74240, "14e56f6d0f810525ddcf9305fa09f495", "https://dl.polyhaven.org/file/ph-assets/Models/jpg/1k/ceramic_vase_01/ceramic_vase_01_arm_1k.jpg"),
        },
    },
}


def parse_arguments() -> argparse.Namespace:
    arguments = __import__("sys").argv
    values = arguments[arguments.index("--") + 1 :] if "--" in arguments else []
    parser = argparse.ArgumentParser(description="Import audited Poly Haven 1K glTF models")
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--asset", action="append", choices=sorted(ASSETS))
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
        max_texture_size = asset.get("max_texture_size")
        if max_texture_size:
            for image in bpy.data.images:
                if image.source == "FILE" and max(image.size) > max_texture_size:
                    image.scale(max_texture_size, max_texture_size)
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
    selected = args.asset or list(ASSETS)
    reports = [
        convert(asset_id, asset, args.output_directory / f"{asset_id}.glb")
        for asset_id, asset in ASSETS.items()
        if asset_id in selected
    ]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"assets": reports}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
