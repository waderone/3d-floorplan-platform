from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.styles import StyleCatalog, StylePack


STYLE_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "style-schema"
    / "styles"
    / "warm-minimal-v1.json"
)


def style_payload() -> dict[str, object]:
    return json.loads(STYLE_PATH.read_text(encoding="utf-8"))


def test_canonical_style_pack_is_valid_and_catalogued() -> None:
    style = StylePack.model_validate(style_payload())
    catalog = StyleCatalog(STYLE_PATH.parent)

    assert style.id == "warm-minimal"
    assert style.version == 3
    assert len(style.layout.placements) == 11
    assert catalog.get("warm-minimal") == style
    assert catalog.get("../warm-minimal") is None
    assert [summary.id for summary in catalog.list()] == [
        "modern-contrast",
        "nordic-light",
        "warm-minimal",
    ]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("license"),
        lambda value: value["materials"].pop("architecture"),
        lambda value: value["layout"]["placements"][0].update(role="unknown"),
        lambda value: value["layout"]["placements"][0].update(assetId="missing"),
        lambda value: value["layout"]["placements"][0].update(size=[1, 0, 1]),
        lambda value: value["layout"]["placements"][0].update(collisionMode="unknown"),
    ],
)
def test_style_pack_rejects_invalid_contract(mutate: object) -> None:
    value = style_payload()
    mutate(value)
    with pytest.raises(ValidationError):
        StylePack.model_validate(value)


def test_style_pack_requires_a_solid_furniture_item() -> None:
    value = style_payload()
    for placement in value["layout"]["placements"]:
        placement["collisionMode"] = "surface"

    with pytest.raises(ValidationError, match="at least one solid"):
        StylePack.model_validate(value)
