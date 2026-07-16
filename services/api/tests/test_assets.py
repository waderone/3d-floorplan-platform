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

    assert catalog.manifest.source_package.license.spdx == "CC0-1.0"
    assert catalog.manifest.source_package.site_version == "1.0"
    assert catalog.manifest.source_package.embedded_version == "2.0"
    assert set(catalog.manifest.room_recipes) == {"living", "dining", "bedroom"}
    model_bytes = sum(
        asset.delivery.bytes for asset in catalog.manifest.assets if asset.delivery is not None
    )
    assert model_bytes == 55_668
    assert model_bytes < catalog.manifest.mobile_budget_bytes


def test_catalog_rejects_missing_recipe_asset() -> None:
    value = json.loads((CATALOG_DIRECTORY / "catalog.json").read_text(encoding="utf-8"))
    value["roomRecipes"]["living"][0]["assetId"] = "missing"

    with pytest.raises(ValueError, match="missing asset"):
        AssetCatalogManifest.model_validate(value)


def test_catalog_rejects_tampered_model(tmp_path: Path) -> None:
    copied = tmp_path / "asset-catalog"
    shutil.copytree(CATALOG_DIRECTORY, copied)
    model = copied / "models" / "kenney-lounge-sofa.glb"
    model.write_bytes(model.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="byte count changed"):
        AssetCatalog(copied / "catalog.json")
