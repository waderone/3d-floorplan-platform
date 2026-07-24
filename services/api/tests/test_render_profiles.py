from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.render_profiles import RenderProfileCatalog, RenderProfileManifest


ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = ROOT / "packages" / "render-assets" / "catalog.json"


def test_render_profiles_freeze_preview_and_quality_contracts() -> None:
    catalog = RenderProfileCatalog(CATALOG_PATH)

    assert set(catalog.manifest.profiles) == {"preview", "quality"}
    assert catalog.get("preview").engine == "BLENDER_EEVEE"
    assert catalog.get("quality").engine == "CYCLES"
    assert [view.id for view in catalog.get("quality").views] == [
        "overview",
        "living",
        "bedroom",
    ]
    assert sum(resource.delivery.bytes for resource in catalog.manifest.resources) == 5_224_351
    assert catalog.manifest.version == 3
    assert "natural-rug" in catalog.manifest.material_sets


def test_render_profile_rejects_invalid_environment_reference() -> None:
    value = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    value["profiles"]["quality"]["environment"]["resourceId"] = "missing"

    with pytest.raises(ValueError, match="invalid environment"):
        RenderProfileManifest.model_validate(value)


def test_render_profile_rejects_invalid_profile_id() -> None:
    value = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    value["profiles"]["PREVIEW"] = value["profiles"].pop("preview")

    with pytest.raises(ValueError, match="profile id is invalid"):
        RenderProfileManifest.model_validate(value)


def test_render_profile_rejects_tampered_resource(tmp_path: Path) -> None:
    copied = tmp_path / "render-assets"
    shutil.copytree(CATALOG_PATH.parent, copied)
    environment = copied / "environment" / "lebombo_1k.hdr"
    environment.write_bytes(environment.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="byte count changed"):
        RenderProfileCatalog(copied / "catalog.json")


def test_render_profile_rejects_missing_license_notice(tmp_path: Path) -> None:
    copied = tmp_path / "render-assets"
    shutil.copytree(CATALOG_PATH.parent, copied)
    (copied / "LICENSE-POLY-HAVEN.txt").unlink()

    with pytest.raises(ValueError, match="license notice is missing"):
        RenderProfileCatalog(copied / "catalog.json")
