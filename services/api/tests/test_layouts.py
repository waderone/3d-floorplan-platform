from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.assets import AssetCatalog
from app.layouts import extract_openings, extract_rooms, generate_layout
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


def test_authoritative_openings_follow_diagonal_wall_coordinates() -> None:
    nodes = {
        "zone_room": {
            "id": "zone_room",
            "type": "zone",
            "name": "卧室",
            "roomType": "bedroom",
            "parentId": "level",
            "polygon": [[0, 0], [4, 0], [4, 4], [0, 4]],
        },
        "wall_diagonal": {
            "id": "wall_diagonal",
            "type": "wall",
            "parentId": "level",
            "start": [0, 0],
            "end": [4, 4],
        },
        "door_diagonal": {
            "id": "door_diagonal",
            "type": "door",
            "parentId": "wall_diagonal",
            "wallId": "wall_diagonal",
            "position": [2**1.5, 1.05, 0],
            "width": 0.9,
            "height": 2.1,
            "doorType": "hinged",
        },
    }

    openings, ignored = extract_openings(nodes, extract_rooms(nodes))

    assert ignored == []
    assert len(openings) == 1
    assert openings[0].center == pytest.approx((2, 2))
    assert openings[0].clearance_type == "swing"
    assert openings[0].room_ids == ["zone_room"]
    assert len(openings[0].clearance_polygon) == 4


def test_unsupported_curved_or_orphan_openings_are_reported() -> None:
    nodes = {
        "wall_curve": {
            "id": "wall_curve",
            "type": "wall",
            "start": [0, 0],
            "end": [4, 0],
            "curveOffset": 0.5,
        },
        "window_curve": {
            "id": "window_curve",
            "type": "window",
            "wallId": "wall_curve",
            "position": [2, 1.5, 0],
        },
        "door_orphan": {"id": "door_orphan", "type": "door", "wallId": "missing"},
    }

    openings, ignored = extract_openings(nodes, [])

    assert openings == []
    assert ignored == ["door_orphan", "window_curve"]


def test_layout_is_deterministic_and_furnishes_three_room_types() -> None:
    style = StyleCatalog(STYLE_DIRECTORY).get("warm-minimal")
    assets = AssetCatalog(ASSET_CATALOG_PATH)
    assert style is not None

    first = generate_layout("layout-demo", 1, fixture_nodes(), style, assets)
    second = generate_layout("layout-demo", 1, fixture_nodes(), style, assets)

    assert first == second
    assert first.status == "ready"
    assert first.selected_room_id == "zone_living"
    assert len(first.placements) == 17
    assert set(first.furnished_room_ids) == {"zone_living", "zone_dining", "zone_bedroom"}
    assert {placement.room_id for placement in first.placements} == set(first.furnished_room_ids)
    assert first.referenced_asset_bytes == 3_888_964
    assert first.mobile_asset_budget_exceeded is False
    assert first.schema_version == "3.0"
    assert first.pipeline_version == "multiroom-opening-clearance-layout-v5"
    assert first.opening_clearance_validated is True
    assert first.openings == []
    assert len(first.layout_id) == 64


def test_layout_moves_a_room_recipe_away_from_door_clearance() -> None:
    style = StyleCatalog(STYLE_DIRECTORY).get("warm-minimal")
    assets = AssetCatalog(ASSET_CATALOG_PATH)
    assert style is not None
    nodes = {
        "zone_living": {
            "id": "zone_living",
            "type": "zone",
            "name": "客厅",
            "roomType": "living",
            "parentId": "level",
            "polygon": [[0, 0], [7, 0], [7, 7], [0, 7]],
        },
        "wall_door": {
            "id": "wall_door",
            "type": "wall",
            "parentId": "level",
            "start": [3.5, 0],
            "end": [3.5, 7],
        },
        "door_center": {
            "id": "door_center",
            "type": "door",
            "parentId": "wall_door",
            "wallId": "wall_door",
            "position": [3.5, 1.05, 0],
            "width": 0.9,
            "height": 2.1,
            "doorType": "hinged",
        },
    }

    layout = generate_layout("layout-door", 1, nodes, style, assets)

    coffee_table = next(entry for entry in layout.placements if entry.item_id == "living-coffee-table")
    assert layout.status == "ready"
    assert [opening.id for opening in layout.openings] == ["door_center"]
    assert layout.opening_blocked_room_ids == []
    assert abs(coffee_table.position[0] - 3.5) > 0.25


def test_layout_reports_when_opening_clearance_blocks_every_candidate() -> None:
    style = StyleCatalog(STYLE_DIRECTORY).get("warm-minimal")
    assets = AssetCatalog(ASSET_CATALOG_PATH)
    assert style is not None
    nodes = {
        "zone_dining": {
            "id": "zone_dining",
            "type": "zone",
            "name": "餐厅",
            "roomType": "dining",
            "parentId": "level",
            "polygon": [[0, 0], [5, 0], [5, 5], [0, 5]],
        },
        "wall_door": {
            "id": "wall_door",
            "type": "wall",
            "parentId": "level",
            "start": [2.5, 0],
            "end": [2.5, 5],
        },
        "door_center": {
            "id": "door_center",
            "type": "door",
            "wallId": "wall_door",
            "position": [2.5, 1.05, 0],
            "width": 1.8,
            "height": 2.1,
            "doorType": "double",
        },
    }

    layout = generate_layout("layout-blocked", 1, nodes, style, assets)

    assert layout.status == "fallback"
    assert layout.opening_blocked_room_ids == ["zone_dining"]
    assert layout.placements == []


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
