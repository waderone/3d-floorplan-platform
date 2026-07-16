from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from app.recognition_evaluation import (
    EvaluationAnnotations,
    EvaluationDataset,
    evaluate_dataset,
    evaluate_predictions,
)


def _source(**overrides: object) -> dict[str, object]:
    source: dict[str, object] = {
        "sourceType": "project-owned",
        "title": "Project-owned evaluation fixture",
        "author": "3D Floorplan Platform",
        "sourceUrl": "https://example.com/project-owned-fixture",
        "licenseId": "Proprietary-Evaluation",
        "licenseUrl": "https://example.com/project-owned-fixture/license",
        "rightsEvidenceUrl": "https://example.com/project-owned-fixture/evidence",
        "commercialUseConfirmed": True,
        "redistributionAllowed": True,
        "storageMode": "repository",
        "reviewedBy": "test-owner",
        "reviewedAt": "2026-07-16",
    }
    source.update(overrides)
    return source


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
        "openings": [
            {"id": "door-1", "kind": "door", "center": [5, 2], "width": 0.9}
        ],
    }


def _floorplan_png(path: Path) -> str:
    image = np.full((400, 500, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (50, 50), (450, 350), (15, 15, 15), 12)
    cv2.line(image, (250, 50), (250, 350), (15, 15, 15), 10)
    assert cv2.imwrite(str(path), image)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _blank_png(path: Path) -> str:
    image = np.full((400, 500, 3), 255, dtype=np.uint8)
    assert cv2.imwrite(str(path), image)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(image_sha256: str, **sample_overrides: object) -> dict[str, object]:
    sample: dict[str, object] = {
        "sampleId": "two-room-fixture",
        "imagePath": "images/two-room.png",
        "imageSha256": image_sha256,
        "planWidthMeters": 10,
        "split": "test",
        "annotationStatus": "complete",
        "source": _source(),
        "annotations": _annotations(),
        "correctionSessions": [
            {
                "pipelineVersion": "opencv-axis-aligned-baseline-v1",
                "durationSeconds": 240,
                "reviewer": "test-owner",
                "completedAt": "2026-07-16",
            }
        ],
    }
    sample.update(sample_overrides)
    return {
        "schemaVersion": "1.0",
        "datasetId": "recognition-evaluation-test",
        "datasetVersion": 1,
        "samples": [sample],
    }


def test_dataset_contract_requires_audited_commercial_rights() -> None:
    payload = _manifest("0" * 64)
    payload["samples"][0]["source"] = _source(commercialUseConfirmed=False)  # type: ignore[index]

    with pytest.raises(ValidationError, match="commercial evaluation rights"):
        EvaluationDataset.model_validate(payload)

    payload = _manifest("0" * 64)
    payload["samples"][0]["source"] = _source(  # type: ignore[index]
        redistributionAllowed=False,
        storageMode="repository",
    )
    with pytest.raises(ValidationError, match="must allow redistribution"):
        EvaluationDataset.model_validate(payload)


def test_documented_example_matches_runtime_contract() -> None:
    repository_root = Path(__file__).parents[3]
    example = repository_root / "datasets/recognition/manifest.example.json"
    schema = repository_root / "datasets/recognition/evaluation-dataset.schema.json"

    dataset = EvaluationDataset.model_validate_json(example.read_text(encoding="utf-8"))

    assert dataset.samples[0].annotation_status == "pending"
    assert json.loads(schema.read_text(encoding="utf-8"))["$schema"].endswith("2020-12/schema")


def test_prediction_metrics_match_directionless_walls_rooms_and_openings() -> None:
    annotations = EvaluationAnnotations.model_validate(
        {
            "walls": [
                {"id": "wall", "start": [0, 0], "end": [4, 0], "thickness": 0.2}
            ],
            "rooms": [
                {
                    "id": "room",
                    "roomType": "living",
                    "polygon": [[0, 0], [4, 0], [4, 3], [0, 3]],
                }
            ],
            "openings": [
                {"id": "door", "kind": "door", "center": [2, 0], "width": 0.9}
            ],
        }
    )
    metrics = evaluate_predictions(
        annotations,
        {
            "walls": [
                {
                    "id": "prediction-wall",
                    "start": [4.05, 0.02],
                    "end": [0.03, -0.01],
                    "thickness": 0.2,
                    "confidence": 0.9,
                }
            ],
            "rooms": [
                {
                    "id": "prediction-room",
                    "name": "Living",
                    "roomType": "unknown",
                    "polygon": [[0.05, 0.05], [3.95, 0.05], [3.95, 2.95], [0.05, 2.95]],
                    "approximateAreaSqM": 11.31,
                    "confidence": 0.8,
                }
            ],
            "openings": [
                {
                    "id": "prediction-door",
                    "kind": "door",
                    "center": [2.1, 0.02],
                    "width": 0.85,
                    "confidence": 0.75,
                }
            ],
        },
    )

    assert metrics["walls"]["f1"] == 1
    assert metrics["walls"]["meanEndpointErrorMeters"] < 0.06
    assert metrics["rooms"]["f1"] == 1
    assert metrics["rooms"]["meanIoU"] > 0.9
    assert metrics["rooms"]["semanticAccuracy"] == 0
    assert metrics["openings"]["f1"] == 1


def test_annotation_contract_rejects_self_intersecting_room() -> None:
    with pytest.raises(ValidationError, match="must not self-intersect"):
        EvaluationAnnotations.model_validate(
            {
                "walls": [],
                "rooms": [
                    {
                        "id": "bow-tie",
                        "roomType": "unknown",
                        "polygon": [[0, 0], [3, 3], [0, 3], [3, 0]],
                    }
                ],
                "openings": [],
            }
        )


def test_evaluation_runs_baseline_and_exposes_unsupported_openings(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    images = dataset_root / "images"
    images.mkdir(parents=True)
    image_sha256 = _floorplan_png(images / "two-room.png")
    manifest_path = dataset_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(_manifest(image_sha256)),
        encoding="utf-8",
    )

    first = evaluate_dataset(manifest_path)
    second = evaluate_dataset(manifest_path)
    changed_manifest = _manifest(image_sha256)
    changed_sample = changed_manifest["samples"][0]  # type: ignore[index]
    changed_sample["correctionSessions"][0]["durationSeconds"] = 241  # type: ignore[index]
    manifest_path.write_text(json.dumps(changed_manifest), encoding="utf-8")
    changed = evaluate_dataset(manifest_path)

    assert first["reportId"] == second["reportId"]
    assert first["reportId"] != changed["reportId"]
    assert first["pipelineVersion"] == "opencv-axis-aligned-baseline-v1"
    assert first["aggregate"]["evaluatedSamples"] == 1
    assert first["aggregate"]["recognitionFailedSamples"] == 0
    assert first["aggregate"]["invalidSamples"] == 0
    assert first["aggregate"]["walls"]["recall"] == 1
    assert first["aggregate"]["rooms"]["recall"] == 1
    assert first["aggregate"]["openings"]["recall"] == 0
    assert first["aggregate"]["correctionSessionCount"] == 1
    assert first["aggregate"]["medianCorrectionSeconds"] == 240


def test_evaluation_reports_pending_and_integrity_failures(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    images = dataset_root / "images"
    images.mkdir(parents=True)
    image_sha256 = _floorplan_png(images / "two-room.png")
    manifest = _manifest("f" * 64)
    pending = _manifest(image_sha256)["samples"][0]  # type: ignore[index]
    pending["sampleId"] = "pending-sample"  # type: ignore[index]
    pending["imagePath"] = "images/not-downloaded.png"  # type: ignore[index]
    pending["annotationStatus"] = "pending"  # type: ignore[index]
    pending["annotations"] = {  # type: ignore[index]
        "coordinateSystem": "plan-bottom-left-x-right-z-up-m",
        "walls": [],
        "rooms": [],
        "openings": [],
    }
    pending["correctionSessions"] = []  # type: ignore[index]
    manifest["samples"].append(pending)  # type: ignore[union-attr]
    manifest_path = dataset_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = evaluate_dataset(manifest_path)

    assert report["aggregate"]["evaluatedSamples"] == 0
    assert report["aggregate"]["invalidSamples"] == 1
    assert report["aggregate"]["pendingSamples"] == 1
    assert "SHA-256 mismatch" in report["results"][0]["error"]
    assert report["results"][0]["status"] == "invalid"
    assert report["results"][1]["status"] == "pending"


def test_recognition_failure_counts_as_zero_recall(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    images = dataset_root / "images"
    images.mkdir(parents=True)
    image_sha256 = _blank_png(images / "two-room.png")
    manifest_path = dataset_root / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest(image_sha256)), encoding="utf-8")

    report = evaluate_dataset(manifest_path)

    assert report["aggregate"]["evaluatedSamples"] == 0
    assert report["aggregate"]["scoredSamples"] == 1
    assert report["aggregate"]["recognitionFailedSamples"] == 1
    assert report["aggregate"]["walls"]["recall"] == 0
    assert report["results"][0]["status"] == "recognition_failed"
