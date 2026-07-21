from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.assets import AssetCatalog, AssetCatalogManifest


ROOT = Path(__file__).resolve().parents[3]
CATALOG_DIRECTORY = ROOT / "packages" / "asset-catalog"


def test_asset_catalog_is_audited_and_within_mobile_budget() -> None:
    catalog = AssetCatalog(CATALOG_DIRECTORY / "catalog.json")

    assert {source.id for source in catalog.manifest.sources} == {
        "kenney-furniture-kit",
        "polyhaven-modern-arm-chair-01-1k",
        "polyhaven-sofa-01-1k",
        "project-modern-upholstered-bed-v1",
        "polyhaven-modern-ceiling-lamp-01-1k",
    }
    assert {source.license.spdx for source in catalog.manifest.sources} == {"CC0-1.0"}
    assert set(catalog.manifest.room_recipes) == {"living", "dining", "bedroom"}
    model_bytes = sum(
        asset.delivery.bytes for asset in catalog.manifest.assets if asset.delivery is not None
    )
    assert model_bytes == 3_817_512
    assert model_bytes < catalog.manifest.mobile_budget_bytes
    assert catalog.assets["polyhaven-sofa-01"].material_mode == "tint"
    assert catalog.assets["polyhaven-modern-arm-chair-01"].material_mode == "tint"
    assert catalog.assets["polyhaven-modern-ceiling-lamp-01"].material_mode == "preserve"
    assert catalog.assets["project-modern-upholstered-bed"].material_mode == "preserve"
    assert catalog.recipe("living")[-1].size == (0.32, 0.7, 0.32)


def test_catalog_rejects_missing_recipe_asset() -> None:
    value = json.loads((CATALOG_DIRECTORY / "catalog.json").read_text(encoding="utf-8"))
    value["roomRecipes"]["living"][0]["assetId"] = "missing"

    with pytest.raises(ValueError, match="missing asset"):
        AssetCatalogManifest.model_validate(value)


def test_catalog_rejects_missing_asset_source() -> None:
    value = json.loads((CATALOG_DIRECTORY / "catalog.json").read_text(encoding="utf-8"))
    value["assets"][0]["sourceId"] = "missing"

    with pytest.raises(ValueError, match="missing source"):
        AssetCatalogManifest.model_validate(value)


def test_catalog_rejects_tampered_model(tmp_path: Path) -> None:
    copied = tmp_path / "asset-catalog"
    shutil.copytree(CATALOG_DIRECTORY, copied)
    model = copied / "models" / "kenney-lounge-sofa.glb"
    model.write_bytes(model.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="byte count changed"):
        AssetCatalog(copied / "catalog.json")


def test_catalog_rejects_missing_license_notice(tmp_path: Path) -> None:
    copied = tmp_path / "asset-catalog"
    shutil.copytree(CATALOG_DIRECTORY, copied)
    (copied / "LICENSE-POLY-HAVEN.txt").unlink()

    with pytest.raises(ValueError, match="license notice is missing"):
        AssetCatalog(copied / "catalog.json")
