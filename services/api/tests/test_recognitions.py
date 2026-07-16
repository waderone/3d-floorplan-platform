from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.main import create_app


def floorplan_png(with_walls: bool = True) -> bytes:
    image = np.full((400, 500, 3), 255, dtype=np.uint8)
    if with_walls:
        cv2.rectangle(image, (50, 50), (450, 350), (15, 15, 15), 12)
        cv2.line(image, (250, 50), (250, 350), (15, 15, 15), 10)
    success, encoded = cv2.imencode(".png", image)
    assert success
    return encoded.tobytes()


def create_scene(client: TestClient, project_id: str, image: bytes) -> dict[str, object]:
    uploaded = client.post(
        "/api/assets",
        files={"file": ("floorplan.png", image, "image/png")},
    )
    assert uploaded.status_code == 201
    asset = uploaded.json()
    saved = client.put(
        f"/api/projects/{project_id}/scene",
        json={
            "schemaVersion": "1.0",
            "revision": 0,
            "expectedRevision": None,
            "units": "m",
            "scene": {
                "nodes": {},
                "rootNodeIds": [],
                "collections": {},
                "materials": {},
            },
            "assets": [asset],
        },
    )
    assert saved.status_code == 201
    return asset


def test_recognition_produces_reviewable_walls_rooms_and_overlay(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        asset = create_scene(client, "recognition-golden", floorplan_png())
        accepted = client.post(
            "/api/projects/recognition-golden/recognitions",
            json={
                "sceneRevision": 1,
                "assetId": asset["assetId"],
                "planWidthMeters": 10,
            },
        )
        latest = client.get("/api/projects/recognition-golden/recognitions/latest")

        assert accepted.status_code == 202
        assert accepted.json()["status"] == "processing"
        assert latest.status_code == 200
        payload = latest.json()
        assert payload["status"] == "review_required"
        assert payload["pipelineVersion"] == "opencv-axis-aligned-baseline-v1"
        assert payload["coordinateSystem"] == {
            "units": "m",
            "origin": "plan-bottom-left",
            "axes": "x-right-z-up",
        }
        assert len(payload["walls"]) == 5
        assert len(payload["rooms"]) == 2
        assert payload["openings"] == []
        assert payload["confidence"] == 0.78
        assert "doors_windows_not_detected" in payload["reviewReasons"]
        assert 40 < payload["metrics"]["pixelsPerMeter"] < 42
        assert all(room["roomType"] == "unknown" for room in payload["rooms"])
        assert 60 < sum(room["approximateAreaSqM"] for room in payload["rooms"]) < 66

        overlay = client.get(payload["overlay"]["url"])
        assert overlay.status_code == 200
        assert len(overlay.content) == payload["overlay"]["bytes"]
        assert hashlib.sha256(overlay.content).hexdigest() == payload["overlay"]["sha256"]

        duplicate = client.post(
            "/api/projects/recognition-golden/recognitions",
            json={
                "sceneRevision": 1,
                "assetId": asset["assetId"],
                "planWidthMeters": 10,
            },
        )
        assert duplicate.json()["recognitionId"] == payload["recognitionId"]
        assert duplicate.json()["status"] == "review_required"


def test_recognition_validates_scene_revision_asset_and_scale(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        asset = create_scene(client, "recognition-inputs", floorplan_png())
        mismatch = client.post(
            "/api/projects/recognition-inputs/recognitions",
            json={
                "sceneRevision": 2,
                "assetId": asset["assetId"],
                "planWidthMeters": 10,
            },
        )
        missing_asset = client.post(
            "/api/projects/recognition-inputs/recognitions",
            json={
                "sceneRevision": 1,
                "assetId": "0" * 64,
                "planWidthMeters": 10,
            },
        )
        invalid_scale = client.post(
            "/api/projects/recognition-inputs/recognitions",
            json={
                "sceneRevision": 1,
                "assetId": asset["assetId"],
                "planWidthMeters": 0,
            },
        )

    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == "scene_revision_mismatch"
    assert missing_asset.status_code == 422
    assert missing_asset.json()["detail"]["code"] == "asset_not_in_scene"
    assert invalid_scale.status_code == 422


def test_recognition_failure_is_explicit_and_does_not_publish_suggestions(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        asset = create_scene(client, "recognition-failure", floorplan_png(with_walls=False))
        client.post(
            "/api/projects/recognition-failure/recognitions",
            json={
                "sceneRevision": 1,
                "assetId": asset["assetId"],
                "planWidthMeters": 10,
            },
        )
        latest = client.get("/api/projects/recognition-failure/recognitions/latest")

    assert latest.status_code == 200
    payload = latest.json()
    assert payload["status"] == "failed"
    assert payload["walls"] == []
    assert payload["rooms"] == []
    assert payload["overlay"] is None
    assert payload["error"] == "no axis-aligned wall candidates were detected"
