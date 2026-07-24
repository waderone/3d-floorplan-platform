from __future__ import annotations

from app.assets import AssetCatalog
from app.baselines import BaselineInputAsset
from app.layouts import extract_openings, extract_rooms, generate_layout
from app.recognition_evaluation import EvaluationSample
from app.reviewed_showrooms import (
    REVIEWED_SHOWROOM_PIPELINE_VERSION,
    build_reviewed_showroom_scene,
)
from app.styles import StyleCatalog


def reviewed_sample() -> EvaluationSample:
    return EvaluationSample.model_validate(
        {
            "sampleId": "reviewed-home",
            "imagePath": "private/reviewed-home.png",
            "imageSha256": "a" * 64,
            "planWidthMeters": 4,
            "split": "calibration",
            "annotationStatus": "complete",
            "source": {
                "sourceType": "project-owned",
                "title": "Reviewed home",
                "author": "Test owner",
                "sourceUrl": "https://example.com/source",
                "licenseId": "project-owned",
                "licenseUrl": "https://example.com/license",
                "rightsEvidenceUrl": "https://example.com/evidence",
                "commercialUseConfirmed": True,
                "redistributionAllowed": False,
                "storageMode": "local-only",
                "reviewedBy": "rights-reviewer",
                "reviewedAt": "2026-07-22",
            },
            "annotations": {
                "walls": [
                    {
                        "id": "wall-left",
                        "start": [0, 0],
                        "end": [1.5, 0],
                        "thickness": 0.2,
                    },
                    {
                        "id": "wall-right",
                        "start": [2.5, 0],
                        "end": [4, 0],
                        "thickness": 0.2,
                    },
                ],
                "rooms": [
                    {
                        "id": "living-room",
                        "roomType": "living",
                        "polygon": [[0, 0], [4, 0], [4, 4], [0, 4]],
                    },
                    {
                        "id": "kitchen-room",
                        "roomType": "kitchen",
                        "polygon": [[5, 0], [8, 0], [8, 3], [5, 3]],
                    },
                    {
                        "id": "bathroom-room",
                        "roomType": "bathroom",
                        "polygon": [[9, 0], [11.5, 0], [11.5, 2], [9, 2]],
                    },
                    {
                        "id": "compact-bedroom",
                        "roomType": "bedroom",
                        "polygon": [[12, 0], [15, 0], [15, 3], [12, 3]],
                    },
                ],
                "openings": [
                    {
                        "id": "door-gap",
                        "kind": "door",
                        "center": [2, 0],
                        "width": 0.9,
                    }
                ],
            },
            "annotationProvenance": {
                "workpackId": "b" * 64,
                "submissionSha256": "c" * 64,
                "annotatedBy": "annotator",
                "annotatedAt": "2026-07-22",
                "reviewedBy": "second-reviewer",
                "reviewedAt": "2026-07-22",
            },
            "correctionSessions": [],
        }
    )


def test_reviewed_scene_preserves_room_semantics_and_review_provenance() -> None:
    scene = build_reviewed_showroom_scene(
        reviewed_sample(),
        BaselineInputAsset(
            assetId="a" * 64,
            url=f"/assets/{'a' * 64}.png",
            mediaType="image/png",
            size=100,
        ),
    )

    rooms = extract_rooms(scene["nodes"])
    by_name = {room.name: room for room in rooms}
    assert by_name["客厅"].room_type == "living"
    assert by_name["厨房"].room_type == "kitchen"
    assert by_name["卫生间"].room_type == "bathroom"
    assert by_name["卫生间"].area == 5
    kitchen_node = next(
        node for node in scene["nodes"].values() if node.get("name") == "厨房"
    )
    assert kitchen_node["metadata"]["originalRoomType"] == "kitchen"
    level = next(node for node in scene["nodes"].values() if node.get("type") == "level")
    provenance = level["metadata"]["reviewedGroundTruth"]
    assert provenance["reviewedBy"] == "second-reviewer"
    assert provenance["pipelineVersion"] == REVIEWED_SHOWROOM_PIPELINE_VERSION


def test_reviewed_opening_in_segment_gap_uses_authoritative_plan_center() -> None:
    scene = build_reviewed_showroom_scene(
        reviewed_sample(),
        BaselineInputAsset(
            assetId="a" * 64,
            url=f"/assets/{'a' * 64}.png",
            mediaType="image/png",
            size=100,
        ),
    )

    rooms = extract_rooms(scene["nodes"])
    openings, ignored = extract_openings(scene["nodes"], rooms)

    assert ignored == []
    assert len(openings) == 1
    assert openings[0].center == (2.0, 0.0)
    assert openings[0].width == 0.9
    assert openings[0].clearance_type == "swing"
    assert openings[0].room_ids


def test_reviewed_compact_bedroom_uses_core_furnishing_variant() -> None:
    scene = build_reviewed_showroom_scene(
        reviewed_sample(),
        BaselineInputAsset(
            assetId="a" * 64,
            url=f"/assets/{'a' * 64}.png",
            mediaType="image/png",
            size=100,
        ),
    )
    style = StyleCatalog().get("warm-minimal")
    assert style is not None
    layout = generate_layout(
        "reviewed-home",
        1,
        scene["nodes"],
        style,
        AssetCatalog(),
    )
    bedroom = next(room for room in layout.rooms if room.name == "卧室")
    item_ids = {
        placement.item_id
        for placement in layout.placements
        if placement.room_id == bedroom.id
    }

    assert bedroom.id in layout.furnished_room_ids
    assert item_ids == {
        "bedroom-bed",
        "bedroom-nightstand-west",
        "bedroom-rug",
        "bedroom-pendant",
    }
    for name, asset_id in (
        ("厨房", "project-warm-minimal-kitchen"),
        ("卫生间", "project-warm-minimal-bathroom"),
    ):
        room = next(candidate for candidate in layout.rooms if candidate.name == name)
        assert room.id in layout.furnished_room_ids
        assert {
            placement.asset_id
            for placement in layout.placements
            if placement.room_id == room.id
        } == {asset_id}
