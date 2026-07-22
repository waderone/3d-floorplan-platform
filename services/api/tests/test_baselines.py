from __future__ import annotations

import hashlib
import json
import shutil
import struct
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.artifacts import validate_glb
from app.baselines import build_structural_glb
from app.main import create_app


class CopyOptimizer:
    def optimize(self, source: Path, output: Path) -> dict[str, Any]:
        shutil.copyfile(source, output)
        content = source.read_bytes()
        metrics = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            "nodes": 5,
            "meshes": 1,
            "materials": 1,
            "primitives": 1,
        }
        return {"source": metrics, "optimized": metrics}


def floorplan_png(with_walls: bool = True) -> bytes:
    image = np.full((400, 500, 3), 255, dtype=np.uint8)
    if with_walls:
        cv2.rectangle(image, (50, 50), (450, 350), (15, 15, 15), 12)
        cv2.line(image, (250, 50), (250, 350), (15, 15, 15), 10)
    success, encoded = cv2.imencode(".png", image)
    assert success
    return encoded.tobytes()


def parse_glb_json(content: bytes) -> dict[str, Any]:
    json_length, chunk_type = struct.unpack("<I4s", content[12:20])
    assert chunk_type == b"JSON"
    return json.loads(content[20 : 20 + json_length].decode().rstrip())


def test_structural_glb_is_deterministic_and_keeps_wall_identity() -> None:
    nodes = {
        "wall-b": {
            "id": "wall-b",
            "type": "wall",
            "start": [4, 0],
            "end": [4, 3],
            "thickness": 0.2,
            "height": 2.8,
        },
        "wall-a": {
            "id": "wall-a",
            "type": "wall",
            "start": [0, 0],
            "end": [4, 0],
            "thickness": 0.18,
            "height": 2.8,
        },
        "zone": {"id": "zone", "type": "zone", "polygon": [[0, 0], [4, 0], [4, 3]]},
    }

    first = build_structural_glb(nodes)
    second = build_structural_glb(nodes)

    validate_glb(first)
    assert first == second
    document = parse_glb_json(first)
    assert [node["extras"]["pascalId"] for node in document["nodes"]] == ["wall-a", "wall-b"]
    vertical_wall = document["nodes"][1]
    assert vertical_wall["matrix"][2] == 3
    assert vertical_wall["matrix"][8] == -0.2
    assert vertical_wall["matrix"][12] == 4
    assert vertical_wall["matrix"][14] == 1.5
    assert len(document["meshes"]) == 1
    assert document["asset"]["generator"] == "floorplan-to-showroom-baseline-v1"


def test_one_upload_builds_a_ready_three_style_showroom(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path, optimizer=CopyOptimizer())) as client:
        accepted = client.post(
            "/api/projects/customer-baseline/baselines",
            data={"planWidthMeters": "10"},
            files={"file": ("floorplan.png", floorplan_png(), "image/png")},
        )
        latest = client.get("/api/projects/customer-baseline/baselines/latest")

        assert accepted.status_code == 202
        assert accepted.json()["status"] == "processing"
        assert latest.status_code == 200
        manifest = latest.json()
        assert manifest["status"] == "ready"
        assert manifest["stage"] == "ready"
        assert manifest["recognitionConfidence"] == 0.78
        assert set(manifest["autoRoomTypes"].values()) == {"living", "bedroom"}
        assert manifest["sceneRevision"] == 2
        assert len(manifest["layouts"]) == 3
        assert {layout["status"] for layout in manifest["layouts"]} == {"ready"}
        assert manifest["viewerUrl"] == "/?project=customer-baseline&style=warm-minimal"
        assert "baseline_auto_accept_without_human_review" in manifest["warnings"]

        scene = client.get("/api/projects/customer-baseline/scene").json()
        assert scene["revision"] == 2
        assert sum(node["type"] == "wall" for node in scene["scene"]["nodes"].values()) == 5
        assert sum(node["type"] == "zone" for node in scene["scene"]["nodes"].values()) == 2
        artifact = client.get("/api/projects/customer-baseline/artifacts/latest").json()
        assert artifact["status"] == "ready"
        assert artifact["sceneRevision"] == 2
        assert client.get(artifact["optimized"]["url"]).status_code == 200

        duplicate = client.post(
            "/api/projects/customer-baseline/baselines",
            data={"planWidthMeters": "10"},
            files={"file": ("floorplan.png", floorplan_png(), "image/png")},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "baseline_project_exists"


def test_baseline_failure_is_explicit_and_keeps_input_scene(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path, optimizer=CopyOptimizer())) as client:
        accepted = client.post(
            "/api/projects/customer-failed/baselines",
            data={"planWidthMeters": "10"},
            files={"file": ("floorplan.png", floorplan_png(with_walls=False), "image/png")},
        )
        latest = client.get("/api/projects/customer-failed/baselines/latest")

        assert accepted.status_code == 202
        assert latest.status_code == 200
        assert latest.json()["status"] == "failed"
        assert latest.json()["stage"] == "failed"
        assert latest.json()["error"] == "no axis-aligned wall candidates were detected"
        assert latest.json()["viewerUrl"] is None
        assert client.get("/api/projects/customer-failed/scene").json()["revision"] == 1
