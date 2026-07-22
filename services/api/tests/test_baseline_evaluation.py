from __future__ import annotations

import hashlib
import json
import shutil
import struct
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.baseline_evaluation import evaluate_baseline_dataset


class CopyOptimizer:
    def optimize(self, source: Path, output: Path) -> dict[str, Any]:
        shutil.copyfile(source, output)
        content = source.read_bytes()
        json_length, chunk_type = struct.unpack("<I4s", content[12:20])
        assert chunk_type == b"JSON"
        document = json.loads(content[20 : 20 + json_length].decode().rstrip())
        metrics = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            "nodes": len(document.get("nodes", [])),
            "meshes": len(document.get("meshes", [])),
            "materials": len(document.get("materials", [])),
            "primitives": sum(
                len(mesh.get("primitives", [])) for mesh in document.get("meshes", [])
            ),
        }
        return {"source": metrics, "optimized": metrics}


class FailingOptimizer:
    def optimize(self, source: Path, output: Path) -> dict[str, Any]:
        raise RuntimeError("synthetic artifact failure")


class RoomBackend:
    def __init__(self, include_room: bool) -> None:
        self.include_room = include_room

    def recognize(
        self,
        image_path: Path,
        plan_width_meters: float,
        overlay_path: Path,
    ) -> dict[str, Any]:
        image = cv2.imread(str(image_path))
        assert image is not None
        assert cv2.imwrite(str(overlay_path), image)
        rooms: list[dict[str, Any]] = []
        if self.include_room:
            rooms.append(
                {
                    "id": "tiny-room",
                    "name": "Room 1",
                    "roomType": "unknown",
                    "polygon": [[0.05, 0.05], [0.45, 0.05], [0.45, 0.45], [0.05, 0.45]],
                    "approximateAreaSqM": 0.16,
                    "confidence": 0.8,
                }
            )
        return {
            "confidence": 0.8,
            "walls": [
                {
                    "id": "wall-1",
                    "start": [0, 0],
                    "end": [1, 0],
                    "thickness": 0.1,
                    "confidence": 0.8,
                }
            ],
            "rooms": rooms,
            "openings": [],
            "reviewReasons": [],
            "metrics": {
                "imageWidthPixels": image.shape[1],
                "imageHeightPixels": image.shape[0],
                "planBoundsPixels": [0, 0, image.shape[1] - 1, image.shape[0] - 1],
                "pixelsPerMeter": image.shape[1] / plan_width_meters,
                "otsuThreshold": 127,
                "structuralPixelRatio": 0.1,
            },
        }


def _source() -> dict[str, object]:
    return {
        "sourceType": "project-owned",
        "title": "Project-owned mainline evaluation fixture",
        "author": "3D Floorplan Platform",
        "sourceUrl": "https://example.com/project-owned-mainline-fixture",
        "licenseId": "Proprietary-Evaluation",
        "licenseUrl": "https://example.com/project-owned-mainline-fixture/license",
        "rightsEvidenceUrl": "https://example.com/project-owned-mainline-fixture/evidence",
        "commercialUseConfirmed": True,
        "redistributionAllowed": True,
        "storageMode": "repository",
        "reviewedBy": "test-owner",
        "reviewedAt": "2026-07-22",
    }


def _annotations() -> dict[str, object]:
    return {
        "coordinateSystem": "plan-bottom-left-x-right-z-up-m",
        "walls": [
            {"id": "top", "start": [0, 7.5], "end": [10, 7.5], "thickness": 0.3},
            {"id": "bottom", "start": [0, 0], "end": [10, 0], "thickness": 0.3},
            {"id": "left", "start": [0, 0], "end": [0, 7.5], "thickness": 0.3},
            {"id": "right", "start": [10, 0], "end": [10, 7.5], "thickness": 0.3},
            {"id": "middle", "start": [5, 0], "end": [5, 7.5], "thickness": 0.24},
        ],
        "rooms": [
            {
                "id": "left-room",
                "roomType": "living",
                "polygon": [[0.2, 0.2], [4.8, 0.2], [4.8, 7.3], [0.2, 7.3]],
            },
            {
                "id": "right-room",
                "roomType": "bedroom",
                "polygon": [[5.2, 0.2], [9.8, 0.2], [9.8, 7.3], [5.2, 7.3]],
            },
        ],
        "openings": [],
    }


def _floorplan(path: Path, *, blank: bool = False) -> str:
    image = np.full((400, 500, 3), 255, dtype=np.uint8)
    if not blank:
        cv2.rectangle(image, (50, 50), (450, 350), (15, 15, 15), 12)
        cv2.line(image, (250, 50), (250, 350), (15, 15, 15), 10)
    assert cv2.imwrite(str(path), image)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sample(image_sha256: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "sampleId": "two-room-fixture",
        "imagePath": "images/two-room.png",
        "imageSha256": image_sha256,
        "planWidthMeters": 10,
        "split": "test",
        "annotationStatus": "complete",
        "source": _source(),
        "annotations": _annotations(),
        "correctionSessions": [],
    }
    value.update(overrides)
    return value


def _write_manifest(path: Path, samples: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "datasetId": "mainline-reliability-test",
                "datasetVersion": 1,
                "samples": samples,
            }
        ),
        encoding="utf-8",
    )


def test_report_marks_three_style_result_publishable_and_deterministic(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    image_sha256 = _floorplan(images / "two-room.png")
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, [_sample(image_sha256)])

    first = evaluate_baseline_dataset(manifest_path, optimizer=CopyOptimizer())
    second = evaluate_baseline_dataset(manifest_path, optimizer=CopyOptimizer())

    assert first["reportId"] == second["reportId"]
    assert first["pipelineVersion"] == "floorplan-mainline-reliability-v1"
    assert first["aggregate"]["publishableSamples"] == 1
    assert first["aggregate"]["publishableRate"] == 1
    result = first["results"][0]
    assert result["status"] == "publishable"
    assert result["recognition"]["walls"] == 5
    assert result["recognition"]["rooms"] == 2
    assert result["scene"]["walls"] == 5
    assert result["scene"]["zones"] == 2
    assert len(result["layouts"]) == 3
    assert all(layout["furnishedRoomCount"] == 2 for layout in result["layouts"])
    assert result["artifact"]["pipelineVersion"] == "gltf-transform-4.4.1-pascal-v4"


def test_report_keeps_pending_invalid_and_recognition_failure_explicit(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    blank_sha256 = _floorplan(images / "two-room.png", blank=True)
    pending = _sample(
        "0" * 64,
        sampleId="pending-sample",
        imagePath="images/missing.png",
        annotationStatus="pending",
        annotations={"walls": [], "rooms": [], "openings": []},
    )
    invalid = _sample("f" * 64, sampleId="invalid-sample")
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, [pending, invalid, _sample(blank_sha256)])

    report = evaluate_baseline_dataset(manifest_path, optimizer=CopyOptimizer())

    assert report["aggregate"]["pendingSamples"] == 1
    assert report["aggregate"]["invalidSamples"] == 1
    assert report["aggregate"]["recognitionFailedSamples"] == 1
    assert report["aggregate"]["publishableRate"] == 0
    assert [result["status"] for result in report["results"]] == [
        "pending",
        "invalid",
        "recognition_failed",
    ]


def test_report_distinguishes_scene_artifact_and_layout_failures(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    image_sha256 = _floorplan(images / "two-room.png")
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, [_sample(image_sha256)])

    scene = evaluate_baseline_dataset(
        manifest_path,
        optimizer=CopyOptimizer(),
        recognition_backend=RoomBackend(include_room=False),
    )
    artifact = evaluate_baseline_dataset(manifest_path, optimizer=FailingOptimizer())
    layout = evaluate_baseline_dataset(
        manifest_path,
        optimizer=CopyOptimizer(),
        recognition_backend=RoomBackend(include_room=True),
    )

    assert scene["results"][0]["status"] == "scene_failed"
    assert artifact["results"][0]["status"] == "artifact_failed"
    assert layout["results"][0]["status"] == "layout_failed"
    assert layout["results"][0]["failedStyleId"] == "modern-contrast"
