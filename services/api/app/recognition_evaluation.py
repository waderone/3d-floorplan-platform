from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .recognitions import (
    RECOGNITION_PIPELINE_VERSION,
    OpenCvRecognitionBackend,
    RecognitionOpening,
    RecognitionRoom,
    RecognitionWall,
)


def _segments_intersect(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> bool:
    def cross(
        origin: tuple[float, float],
        first: tuple[float, float],
        second: tuple[float, float],
    ) -> float:
        return (first[0] - origin[0]) * (second[1] - origin[1]) - (
            first[1] - origin[1]
        ) * (second[0] - origin[0])

    first_side = cross(first_start, first_end, second_start)
    second_side = cross(first_start, first_end, second_end)
    third_side = cross(second_start, second_end, first_start)
    fourth_side = cross(second_start, second_end, first_end)
    return first_side * second_side < 0 and third_side * fourth_side < 0


class EvaluationSource(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    source_type: Literal[
        "project-owned",
        "commissioned",
        "public-domain",
        "open-license",
    ] = Field(alias="sourceType")
    title: str = Field(min_length=1, max_length=300)
    author: str = Field(min_length=1, max_length=200)
    source_url: str = Field(alias="sourceUrl", pattern=r"^https://")
    license_id: str = Field(alias="licenseId", min_length=1, max_length=100)
    license_url: str = Field(alias="licenseUrl", pattern=r"^https://")
    rights_evidence_url: str = Field(alias="rightsEvidenceUrl", pattern=r"^https://")
    commercial_use_confirmed: bool = Field(alias="commercialUseConfirmed")
    redistribution_allowed: bool = Field(alias="redistributionAllowed")
    storage_mode: Literal["repository", "local-only"] = Field(alias="storageMode")
    reviewed_by: str = Field(alias="reviewedBy", min_length=1, max_length=100)
    reviewed_at: str = Field(
        alias="reviewedAt",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )

    @model_validator(mode="after")
    def validate_rights(self) -> "EvaluationSource":
        if not self.commercial_use_confirmed:
            raise ValueError("sample must have confirmed commercial evaluation rights")
        if self.storage_mode == "repository" and not self.redistribution_allowed:
            raise ValueError("repository samples must allow redistribution")
        return self


class EvaluationWall(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    id: str = Field(min_length=1, max_length=100)
    start: tuple[float, float]
    end: tuple[float, float]
    thickness: float = Field(gt=0, le=2)

    @model_validator(mode="after")
    def validate_length(self) -> "EvaluationWall":
        if self.start == self.end:
            raise ValueError("wall start and end must differ")
        return self


class EvaluationRoom(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", allow_inf_nan=False)

    id: str = Field(min_length=1, max_length=100)
    room_type: str = Field(alias="roomType", min_length=1, max_length=50)
    polygon: list[tuple[float, float]] = Field(min_length=3)

    @model_validator(mode="after")
    def validate_polygon(self) -> "EvaluationRoom":
        if len(set(self.polygon)) < 3:
            raise ValueError("room polygon must contain three distinct points")
        edges = list(zip(self.polygon, self.polygon[1:] + self.polygon[:1]))
        for first_index, first_edge in enumerate(edges):
            for second_index in range(first_index + 1, len(edges)):
                if second_index == first_index + 1 or {
                    first_index,
                    second_index,
                } == {0, len(edges) - 1}:
                    continue
                if _segments_intersect(*first_edge, *edges[second_index]):
                    raise ValueError("room polygon must not self-intersect")
        signed_double_area = sum(
            first[0] * second[1] - second[0] * first[1] for first, second in edges
        )
        if abs(signed_double_area) < 1e-8:
            raise ValueError("room polygon must have a non-zero area")
        return self


class EvaluationOpening(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    id: str = Field(min_length=1, max_length=100)
    kind: Literal["door", "window"]
    center: tuple[float, float]
    width: float = Field(gt=0, le=20)


class EvaluationCorrectionSession(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", allow_inf_nan=False)

    pipeline_version: str = Field(alias="pipelineVersion", min_length=1, max_length=100)
    duration_seconds: float = Field(alias="durationSeconds", gt=0, le=7200)
    reviewer: str = Field(min_length=1, max_length=100)
    completed_at: str = Field(
        alias="completedAt",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )


class EvaluationAnnotations(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    coordinate_system: Literal["plan-bottom-left-x-right-z-up-m"] = Field(
        alias="coordinateSystem",
        default="plan-bottom-left-x-right-z-up-m",
    )
    walls: list[EvaluationWall] = Field(default_factory=list)
    rooms: list[EvaluationRoom] = Field(default_factory=list)
    openings: list[EvaluationOpening] = Field(default_factory=list)


class EvaluationSample(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    sample_id: str = Field(alias="sampleId", pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    image_path: str = Field(alias="imagePath")
    image_sha256: str = Field(alias="imageSha256", pattern=r"^[0-9a-f]{64}$")
    plan_width_meters: float = Field(alias="planWidthMeters", gt=0, le=500)
    split: Literal["calibration", "validation", "test"]
    annotation_status: Literal["pending", "complete"] = Field(alias="annotationStatus")
    source: EvaluationSource
    annotations: EvaluationAnnotations
    correction_sessions: list[EvaluationCorrectionSession] = Field(
        alias="correctionSessions",
        default_factory=list,
    )

    @model_validator(mode="after")
    def validate_sample(self) -> "EvaluationSample":
        path = Path(self.image_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("imagePath must stay inside the dataset directory")
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            raise ValueError("imagePath must reference a JPG or PNG image")
        if self.annotation_status == "complete" and not self.annotations.walls:
            raise ValueError("complete annotations must include at least one wall")
        if self.annotation_status == "pending" and self.correction_sessions:
            raise ValueError("pending annotations cannot include correction sessions")
        return self


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    dataset_id: str = Field(alias="datasetId", pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    dataset_version: int = Field(alias="datasetVersion", ge=1)
    samples: list[EvaluationSample] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_samples(self) -> "EvaluationDataset":
        sample_ids = [sample.sample_id for sample in self.samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("sampleId values must be unique")
        return self


class EvaluationThresholds(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    wall_endpoint_tolerance_meters: float = Field(
        alias="wallEndpointToleranceMeters",
        default=0.25,
        gt=0,
    )
    room_iou_threshold: float = Field(alias="roomIouThreshold", default=0.5, gt=0, le=1)
    opening_center_tolerance_meters: float = Field(
        alias="openingCenterToleranceMeters",
        default=0.3,
        gt=0,
    )
    opening_width_tolerance_meters: float = Field(
        alias="openingWidthToleranceMeters",
        default=0.2,
        gt=0,
    )


def _distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def _wall_error(reference: EvaluationWall, prediction: RecognitionWall) -> tuple[float, float]:
    direct = (
        _distance(reference.start, prediction.start),
        _distance(reference.end, prediction.end),
    )
    reversed_ = (
        _distance(reference.start, prediction.end),
        _distance(reference.end, prediction.start),
    )
    return min(direct, reversed_, key=lambda errors: (max(errors), sum(errors)))


def _match_walls(
    references: list[EvaluationWall],
    predictions: list[RecognitionWall],
    tolerance: float,
) -> tuple[int, list[float]]:
    candidates: list[tuple[float, float, int, int]] = []
    for reference_index, reference in enumerate(references):
        for prediction_index, prediction in enumerate(predictions):
            errors = _wall_error(reference, prediction)
            if max(errors) <= tolerance:
                candidates.append(
                    (max(errors), sum(errors) / 2, reference_index, prediction_index)
                )
    matched_references: set[int] = set()
    matched_predictions: set[int] = set()
    endpoint_errors: list[float] = []
    for _, mean_error, reference_index, prediction_index in sorted(candidates):
        if reference_index in matched_references or prediction_index in matched_predictions:
            continue
        matched_references.add(reference_index)
        matched_predictions.add(prediction_index)
        endpoint_errors.append(mean_error)
    return len(matched_references), endpoint_errors


def _polygon_iou(
    reference: list[tuple[float, float]],
    prediction: list[tuple[float, float]],
) -> float:
    points = reference + prediction
    min_x = min(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_x = max(point[0] for point in points)
    max_y = max(point[1] for point in points)
    max_extent = max(max_x - min_x, max_y - min_y, 0.01)
    pixels_per_meter = min(100.0, 2048.0 / max_extent)
    width = max(3, math.ceil((max_x - min_x) * pixels_per_meter) + 3)
    height = max(3, math.ceil((max_y - min_y) * pixels_per_meter) + 3)

    def rasterize(polygon: list[tuple[float, float]]) -> np.ndarray:
        mask = np.zeros((height, width), dtype=np.uint8)
        pixels = np.array(
            [
                [
                    round((x - min_x) * pixels_per_meter) + 1,
                    round((max_y - y) * pixels_per_meter) + 1,
                ]
                for x, y in polygon
            ],
            dtype=np.int32,
        )
        cv2.fillPoly(mask, [pixels], 1)
        return mask

    reference_mask = rasterize(reference)
    prediction_mask = rasterize(prediction)
    intersection = int(np.count_nonzero(reference_mask & prediction_mask))
    union = int(np.count_nonzero(reference_mask | prediction_mask))
    return intersection / union if union else 0.0


def _match_rooms(
    references: list[EvaluationRoom],
    predictions: list[RecognitionRoom],
    threshold: float,
) -> tuple[int, list[float], int]:
    candidates: list[tuple[float, int, int]] = []
    for reference_index, reference in enumerate(references):
        for prediction_index, prediction in enumerate(predictions):
            iou = _polygon_iou(reference.polygon, prediction.polygon)
            if iou >= threshold:
                candidates.append((-iou, reference_index, prediction_index))
    matched_references: set[int] = set()
    matched_predictions: set[int] = set()
    ious: list[float] = []
    semantic_matches = 0
    for negative_iou, reference_index, prediction_index in sorted(candidates):
        if reference_index in matched_references or prediction_index in matched_predictions:
            continue
        matched_references.add(reference_index)
        matched_predictions.add(prediction_index)
        ious.append(-negative_iou)
        if references[reference_index].room_type == predictions[prediction_index].room_type:
            semantic_matches += 1
    return len(matched_references), ious, semantic_matches


def _match_openings(
    references: list[EvaluationOpening],
    predictions: list[RecognitionOpening],
    center_tolerance: float,
    width_tolerance: float,
) -> int:
    candidates: list[tuple[float, float, int, int]] = []
    for reference_index, reference in enumerate(references):
        for prediction_index, prediction in enumerate(predictions):
            center_error = _distance(reference.center, prediction.center)
            width_error = abs(reference.width - prediction.width)
            if (
                reference.kind == prediction.kind
                and center_error <= center_tolerance
                and width_error <= width_tolerance
            ):
                candidates.append(
                    (center_error, width_error, reference_index, prediction_index)
                )
    matched_references: set[int] = set()
    matched_predictions: set[int] = set()
    for _, _, reference_index, prediction_index in sorted(candidates):
        if reference_index in matched_references or prediction_index in matched_predictions:
            continue
        matched_references.add(reference_index)
        matched_predictions.add(prediction_index)
    return len(matched_references)


def _counts(matched: int, predicted: int, reference: int) -> dict[str, int | float | None]:
    if predicted == 0 and reference == 0:
        return {
            "matched": 0,
            "predicted": 0,
            "reference": 0,
            "precision": None,
            "recall": None,
            "f1": None,
        }
    precision = matched / predicted if predicted else 0.0
    recall = matched / reference if reference else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "matched": matched,
        "predicted": predicted,
        "reference": reference,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def evaluate_predictions(
    annotations: EvaluationAnnotations,
    raw_predictions: dict[str, Any],
    thresholds: EvaluationThresholds | None = None,
) -> dict[str, Any]:
    limits = thresholds or EvaluationThresholds()
    walls = [RecognitionWall.model_validate(item) for item in raw_predictions.get("walls", [])]
    rooms = [RecognitionRoom.model_validate(item) for item in raw_predictions.get("rooms", [])]
    openings = [
        RecognitionOpening.model_validate(item) for item in raw_predictions.get("openings", [])
    ]

    wall_matches, endpoint_errors = _match_walls(
        annotations.walls,
        walls,
        limits.wall_endpoint_tolerance_meters,
    )
    room_matches, room_ious, semantic_matches = _match_rooms(
        annotations.rooms,
        rooms,
        limits.room_iou_threshold,
    )
    opening_matches = _match_openings(
        annotations.openings,
        openings,
        limits.opening_center_tolerance_meters,
        limits.opening_width_tolerance_meters,
    )
    return {
        "walls": {
            **_counts(wall_matches, len(walls), len(annotations.walls)),
            "meanEndpointErrorMeters": round(sum(endpoint_errors) / len(endpoint_errors), 6)
            if endpoint_errors
            else None,
        },
        "rooms": {
            **_counts(room_matches, len(rooms), len(annotations.rooms)),
            "meanIoU": round(sum(room_ious) / len(room_ious), 6) if room_ious else None,
            "semanticAccuracy": round(semantic_matches / room_matches, 6)
            if room_matches
            else None,
        },
        "openings": _counts(
            opening_matches,
            len(openings),
            len(annotations.openings),
        ),
    }


def _verified_image_path(root: Path, sample: EvaluationSample) -> Path:
    resolved_root = root.resolve()
    image_path = (resolved_root / sample.image_path).resolve()
    if not image_path.is_relative_to(resolved_root) or not image_path.is_file():
        raise ValueError(f"sample image is missing or outside dataset: {sample.sample_id}")
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    if digest != sample.image_sha256:
        raise ValueError(f"sample image SHA-256 mismatch: {sample.sample_id}")
    return image_path


def _aggregate(sample_results: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [result for result in sample_results if result["status"] == "evaluated"]
    scored = [
        result
        for result in sample_results
        if result["status"] in {"evaluated", "recognition_failed"}
    ]
    aggregate: dict[str, Any] = {
        "totalSamples": len(sample_results),
        "evaluatedSamples": len(evaluated),
        "scoredSamples": len(scored),
        "pendingSamples": sum(result["status"] == "pending" for result in sample_results),
        "recognitionFailedSamples": sum(
            result["status"] == "recognition_failed" for result in sample_results
        ),
        "invalidSamples": sum(result["status"] == "invalid" for result in sample_results),
    }
    for category in ("walls", "rooms", "openings"):
        matched = sum(result["metrics"][category]["matched"] for result in scored)
        predicted = sum(result["metrics"][category]["predicted"] for result in scored)
        reference = sum(result["metrics"][category]["reference"] for result in scored)
        aggregate[category] = _counts(matched, predicted, reference)
    endpoint_errors = [
        result["metrics"]["walls"]["meanEndpointErrorMeters"]
        for result in evaluated
        if result["metrics"]["walls"]["meanEndpointErrorMeters"] is not None
    ]
    room_ious = [
        result["metrics"]["rooms"]["meanIoU"]
        for result in evaluated
        if result["metrics"]["rooms"]["meanIoU"] is not None
    ]
    aggregate["walls"]["meanSampleEndpointErrorMeters"] = (
        round(statistics.fmean(endpoint_errors), 6) if endpoint_errors else None
    )
    aggregate["rooms"]["meanSampleIoU"] = (
        round(statistics.fmean(room_ious), 6) if room_ious else None
    )
    return aggregate


def evaluate_dataset(
    manifest_path: Path,
    thresholds: EvaluationThresholds | None = None,
) -> dict[str, Any]:
    dataset = EvaluationDataset.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    limits = thresholds or EvaluationThresholds()
    backend = OpenCvRecognitionBackend()
    sample_results: list[dict[str, Any]] = []
    correction_seconds = [
        session.duration_seconds
        for sample in dataset.samples
        for session in sample.correction_sessions
        if session.pipeline_version == RECOGNITION_PIPELINE_VERSION
    ]
    with tempfile.TemporaryDirectory(prefix="floorplan-evaluation-") as temporary_directory:
        overlay_root = Path(temporary_directory)
        for sample in dataset.samples:
            if sample.annotation_status == "pending":
                sample_results.append({"sampleId": sample.sample_id, "status": "pending"})
                continue
            started = time.perf_counter()
            try:
                image_path = _verified_image_path(manifest_path.parent, sample)
            except Exception as error:
                sample_results.append(
                    {
                        "sampleId": sample.sample_id,
                        "status": "invalid",
                        "durationMilliseconds": round((time.perf_counter() - started) * 1000, 3),
                        "error": (str(error) or error.__class__.__name__)[:1000],
                    }
                )
                continue
            try:
                predictions = backend.recognize(
                    image_path,
                    sample.plan_width_meters,
                    overlay_root / f"{sample.sample_id}.png",
                )
                sample_results.append(
                    {
                        "sampleId": sample.sample_id,
                        "status": "evaluated",
                        "durationMilliseconds": round((time.perf_counter() - started) * 1000, 3),
                        "metrics": evaluate_predictions(
                            sample.annotations,
                            predictions,
                            limits,
                        ),
                    }
                )
            except Exception as error:
                sample_results.append(
                    {
                        "sampleId": sample.sample_id,
                        "status": "recognition_failed",
                        "durationMilliseconds": round((time.perf_counter() - started) * 1000, 3),
                        "error": (str(error) or error.__class__.__name__)[:1000],
                        "metrics": evaluate_predictions(
                            sample.annotations,
                            {"walls": [], "rooms": [], "openings": []},
                            limits,
                        ),
                    }
                )
    manifest_digest = hashlib.sha256(
        json.dumps(
            dataset.model_dump(by_alias=True, mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    identity_payload = {
        "datasetId": dataset.dataset_id,
        "datasetVersion": dataset.dataset_version,
        "datasetManifestSha256": manifest_digest,
        "pipelineVersion": RECOGNITION_PIPELINE_VERSION,
        "thresholds": limits.model_dump(by_alias=True),
        "samples": [
            {"sampleId": sample.sample_id, "imageSha256": sample.image_sha256}
            for sample in dataset.samples
        ],
    }
    report_id = hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schemaVersion": "1.0",
        "reportId": report_id,
        **identity_payload,
        "aggregate": {
            **_aggregate(sample_results),
            "correctionSessionCount": len(correction_seconds),
            "medianCorrectionSeconds": round(statistics.median(correction_seconds), 3)
            if correction_seconds
            else None,
        },
        "results": sample_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate floor-plan recognition dataset")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = evaluate_dataset(arguments.manifest.resolve())
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if arguments.output:
        arguments.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
