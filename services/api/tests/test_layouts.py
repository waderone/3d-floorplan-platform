from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.assets import AssetCatalog
from app.layouts import extract_rooms, generate_layout
from app.styles import StyleCatalog


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "room-layout-scene.json"
STYLE_DIRECTORY = ROOT / "packages" / "style-schema" / "styles"
ASSET_CATALOG_PATH = ROOT / "packages" / "asset-catalog" / "catalog.json"


def fixture_nodes() -> dict[str, dict[str, object]]:
    value = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return value["scene"]["nodes"]


def test_zone_rooms_are_preferred_and_sorted_by_area() -> None:
    nodes = fixture_nodes()
    nodes["slab_larger"] = {
        "id": "slab_larger",
        "type": "slab",
        "name": "Floor",
        "polygon": [[-10, -10], [10, -10], [10, 10], [-10, 10]],
    }

    rooms = extract_rooms(nodes)

    assert [room.id for room in rooms] == ["zone_living", "zone_bedroom", "zone_dining"]
    assert rooms[0].area == 42
    assert rooms[0].centroid == (-5, -0.5)
    assert {room.room_type for room in rooms} == {"living", "dining", "bedroom"}


def test_slab_is_used_only_as_explicit_room_fallback() -> None:
    rooms = extract_rooms(
        {
            "slab_room": {
                "id": "slab_room",
                "type": "slab",
                "name": "Fallback Room",
                "parentId": "level",
                "polygon": [[0, 0], [6, 0], [6, 5], [0, 5]],
            }
        }
    )

    assert len(rooms) == 1
    assert rooms[0].source == "slab"


def test_layout_is_deterministic_and_furnishes_three_room_types() -> None:
    style = StyleCatalog(STYLE_DIRECTORY).get("warm-minimal")
    assets = AssetCatalog(ASSET_CATALOG_PATH)
    assert style is not None

    first = generate_layout("layout-demo", 1, fixture_nodes(), style, assets)
    second = generate_layout("layout-demo", 1, fixture_nodes(), style, assets)

    assert first == second
    assert first.status == "ready"
    assert first.selected_room_id == "zone_living"
    assert len(first.placements) == 16
    assert set(first.furnished_room_ids) == {"zone_living", "zone_dining", "zone_bedroom"}
    assert {placement.room_id for placement in first.placements} == set(first.furnished_room_ids)
    assert first.referenced_asset_bytes == 4_318_976
    assert first.mobile_asset_budget_exceeded is False
    assert len(first.layout_id) == 64


def test_layout_identity_changes_with_revision_or_style() -> None:
    catalog = StyleCatalog(STYLE_DIRECTORY)
    warm = catalog.get("warm-minimal")
    modern = catalog.get("modern-contrast")
    assets = AssetCatalog(ASSET_CATALOG_PATH)
    assert warm is not None and modern is not None
    first = generate_layout("layout-demo", 1, fixture_nodes(), warm, assets)
    revised = generate_layout("layout-demo", 2, fixture_nodes(), warm, assets)
    restyled = generate_layout("layout-demo", 1, fixture_nodes(), modern, assets)

    assert first.layout_id != revised.layout_id
    assert first.layout_id != restyled.layout_id


def test_layout_rejects_a_catalog_recipe_with_colliding_items() -> None:
    style = StyleCatalog(STYLE_DIRECTORY).get("warm-minimal")
    assets = AssetCatalog(ASSET_CATALOG_PATH)
    assert style is not None
    sideboard = next(
        placement
        for placement in assets.manifest.room_recipes["living"]
        if placement.item_id == "living-sideboard"
    )
    sideboard.position = (0, sideboard.position[1], 1.2)

    with pytest.raises(ValueError, match="recipe violates item clearance"):
        generate_layout("layout-demo", 1, fixture_nodes(), style, assets)


def test_layout_fallbacks_are_explicit() -> None:
    style = StyleCatalog(STYLE_DIRECTORY).get("warm-minimal")
    assets = AssetCatalog(ASSET_CATALOG_PATH)
    assert style is not None
    missing = generate_layout("layout-demo", 1, {}, style, assets)
    too_small = generate_layout(
        "layout-demo",
        1,
        {
            "zone_small": {
                "id": "zone_small",
                "type": "zone",
                "name": "小客厅",
                "roomType": "living",
                "polygon": [[0, 0], [3, 0], [3, 3], [0, 3]],
            }
        },
        style,
        assets,
    )

    assert missing.status == "fallback"
    assert missing.fallback_reason == "no-room-polygon"
    assert missing.placements == []
    assert too_small.status == "fallback"
    assert too_small.fallback_reason == "no-room-fits"


def test_unknown_room_is_reported_as_partial() -> None:
    style = StyleCatalog(STYLE_DIRECTORY).get("warm-minimal")
    assets = AssetCatalog(ASSET_CATALOG_PATH)
    assert style is not None
    nodes = fixture_nodes()
    nodes["zone_storage"] = {
        "id": "zone_storage",
        "type": "zone",
        "name": "储藏室",
        "parentId": "level_layout",
        "polygon": [[4, 1], [8, 1], [8, 5], [4, 5]],
    }

    layout = generate_layout("layout-demo", 1, nodes, style, assets)

    assert layout.status == "partial"
    assert layout.unfurnished_room_ids == ["zone_storage"]
