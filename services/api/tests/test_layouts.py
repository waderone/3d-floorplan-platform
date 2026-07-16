from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.layouts import extract_rooms, generate_layout
from app.styles import StyleCatalog


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "room-layout-scene.json"
STYLE_DIRECTORY = ROOT / "packages" / "style-schema" / "styles"


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

    assert [room.id for room in rooms] == ["zone_living", "zone_bedroom"]
    assert rooms[0].area == 56
    assert rooms[0].centroid == (-3, 0.5)


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


def test_layout_is_deterministic_and_uses_largest_fitting_room() -> None:
    style = StyleCatalog(STYLE_DIRECTORY).get("warm-minimal")
    assert style is not None

    first = generate_layout("layout-demo", 1, fixture_nodes(), style)
    second = generate_layout("layout-demo", 1, fixture_nodes(), style)

    assert first == second
    assert first.status == "ready"
    assert first.selected_room_id == "zone_living"
    assert len(first.placements) == len(style.layout.placements)
    assert {placement.room_id for placement in first.placements} == {"zone_living"}
    assert len(first.layout_id) == 64


def test_layout_identity_changes_with_revision_or_style() -> None:
    catalog = StyleCatalog(STYLE_DIRECTORY)
    warm = catalog.get("warm-minimal")
    modern = catalog.get("modern-contrast")
    assert warm is not None and modern is not None
    first = generate_layout("layout-demo", 1, fixture_nodes(), warm)
    revised = generate_layout("layout-demo", 2, fixture_nodes(), warm)
    restyled = generate_layout("layout-demo", 1, fixture_nodes(), modern)

    assert first.layout_id != revised.layout_id
    assert first.layout_id != restyled.layout_id


def test_layout_rejects_a_style_template_with_colliding_items() -> None:
    style = StyleCatalog(STYLE_DIRECTORY).get("warm-minimal")
    assert style is not None
    invalid = style.model_copy(deep=True)
    sideboard = next(
        placement for placement in invalid.layout.placements if placement.item_id == "sideboard"
    )
    sideboard.position = (0, sideboard.position[1], 1)

    with pytest.raises(ValueError, match="violates item clearance"):
        generate_layout("layout-demo", 1, fixture_nodes(), invalid)


def test_layout_fallbacks_are_explicit() -> None:
    style = StyleCatalog(STYLE_DIRECTORY).get("warm-minimal")
    assert style is not None
    missing = generate_layout("layout-demo", 1, {}, style)
    too_small = generate_layout(
        "layout-demo",
        1,
        {
            "zone_small": {
                "id": "zone_small",
                "type": "zone",
                "name": "Small",
                "polygon": [[0, 0], [3, 0], [3, 3], [0, 3]],
            }
        },
        style,
    )

    assert missing.status == "fallback"
    assert missing.fallback_reason == "no-room-polygon"
    assert missing.placements == []
    assert too_small.status == "fallback"
    assert too_small.fallback_reason == "no-room-fits"
