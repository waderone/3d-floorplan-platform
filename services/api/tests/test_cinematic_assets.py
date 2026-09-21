from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = REPOSITORY_ROOT / "packages" / "cinematic-assets" / "catalog.json"
SCENE_SPEC_PATH = (
    REPOSITORY_ROOT / "packages" / "cinematic-scenes" / "warm-minimal-living-v1.json"
)
SCENE_BUILDER_PATH = REPOSITORY_ROOT / "tools" / "cinematic" / "build_warm_living.py"
DATASET_MANIFEST_PATH = REPOSITORY_ROOT / "datasets" / "recognition" / "manifest.json"


def test_cinematic_asset_catalog_is_frozen_and_unique() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    assert catalog["schemaVersion"] == "1.0"
    assert catalog["scope"] == "audited-candidate-pool"
    assert catalog["license"]["spdx"] == "CC0-1.0"
    resources = catalog["resources"]
    assert len(resources) == 37
    assert len({resource["id"] for resource in resources}) == len(resources)
    assert len({resource["delivery"]["path"] for resource in resources}) == len(resources)
    assert {resource["kind"] for resource in resources} == {
        "environment",
        "color",
        "normal",
        "roughness",
        "model",
        "model-data",
        "arm",
    }
    for resource in resources:
        delivery = resource["delivery"]
        assert resource["url"].startswith("https://dl.polyhaven.org/file/")
        assert resource["sourcePageUrl"].startswith("https://polyhaven.com/a/")
        assert delivery["bytes"] > 0
        assert len(delivery["md5"]) == 32
        int(delivery["md5"], 16)


def test_cinematic_license_notice_is_tracked() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    notice_path = CATALOG_PATH.parent / catalog["license"]["localNotice"]

    assert notice_path.is_file()
    assert hashlib.sha256(notice_path.read_bytes()).hexdigest()


def test_warm_minimal_living_scene_spec_references_frozen_sources() -> None:
    spec = json.loads(SCENE_SPEC_PATH.read_text(encoding="utf-8"))

    assert spec["schemaVersion"] == "1.0"
    assert spec["source"]["roomId"] == "zone_truth_366965e3b2c3_room_7"
    assert spec["designIntent"]["inventWindows"] is False
    assert spec["envelope"]["openSide"] == "south"
    assert {
        feature["id"]: feature["confidence"] for feature in spec["derivedFeatures"]
    } == {
        "north-wall-stair": "reviewed-inferred",
        "upper-stair-landing": "reviewed-inferred",
    }
    assert spec["layoutAudit"]["crossPassage"] == {
        "axis": "x",
        "centerY": 0.55,
        "clearDepth": 0.9,
        "connects": ["west-door", "east-door"],
    }
    assert spec["layoutAudit"]["excludedCandidateAssetIds"] == [
        "modern_arm_chair_01",
        "potted_plant_02",
    ]
    builder = SCENE_BUILDER_PATH.read_text(encoding="utf-8")
    assert "accent-chair-" not in builder
    assert "potted-plant-02-root" not in builder
    assert spec["outputs"]["preview"] == {
        "width": 1600,
        "height": 900,
        "samples": 128,
    }
    assert spec["outputs"]["panorama-preview"] == {
        "width": 2048,
        "height": 1024,
        "samples": 64,
    }
    assert spec["outputs"]["hero"] == {"width": 3840, "height": 2160, "samples": 384}
    assert spec["outputs"]["panorama"] == {
        "width": 8192,
        "height": 4096,
        "samples": 256,
    }
    for key in ("scene", "image"):
        relative_path = Path(spec["source"][f"{key}Path"])
        digest = spec["source"][f"{key}Sha256"]
        assert not relative_path.is_absolute()
        assert len(digest) == 64
        int(digest, 16)

    dataset = json.loads(DATASET_MANIFEST_PATH.read_text(encoding="utf-8"))
    sample = next(
        value for value in dataset["samples"] if value["sampleId"] == "commons-190205778"
    )
    assert sample["imagePath"] == spec["source"]["imagePath"].removeprefix(
        "datasets/recognition/"
    )
    assert sample["imageSha256"] == spec["source"]["imageSha256"]
    assert sample["source"]["storageMode"] == "local-only"
    assert sample["source"]["redistributionAllowed"] is True
