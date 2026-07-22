from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifacts import PIPELINE_VERSION as ARTIFACT_PIPELINE_VERSION
from .artifacts import ArtifactStore, GlbOptimizer, NodeGlbOptimizer
from .assets import AssetCatalog
from .baselines import BASELINE_PIPELINE_VERSION, BaselineInputAsset, build_baseline_scene
from .baselines import build_structural_glb
from .layouts import LAYOUT_PIPELINE_VERSION, generate_layout
from .recognition_evaluation import EvaluationDataset, EvaluationSample, _verified_image_path
from .recognitions import (
    RECOGNITION_PIPELINE_VERSION,
    OpenCvRecognitionBackend,
    RecognitionBackend,
    RecognitionCoordinateSystem,
    RecognitionManifest,
)
from .renders import RenderImageMetadata, validate_png
from .styles import StyleCatalog


BASELINE_EVALUATION_PIPELINE_VERSION = "floorplan-mainline-reliability-v1"


def _error_text(error: Exception) -> str:
    return (str(error) or error.__class__.__name__)[:1000]


def _input_asset(sample: EvaluationSample, image_path: Path) -> BaselineInputAsset:
    is_png = image_path.suffix.lower() == ".png"
    extension = "png" if is_png else "jpg"
    return BaselineInputAsset(
        assetId=sample.image_sha256,
        url=f"/assets/{sample.image_sha256}.{extension}",
        mediaType="image/png" if is_png else "image/jpeg",
        size=image_path.stat().st_size,
    )


def _recognition_manifest(
    sample: EvaluationSample,
    result: dict[str, Any],
    overlay_path: Path,
) -> RecognitionManifest:
    width, height, size, overlay_sha256 = validate_png(overlay_path)
    identity = (
        f"{sample.sample_id}:{sample.image_sha256}:{sample.plan_width_meters:.6f}:"
        f"{RECOGNITION_PIPELINE_VERSION}"
    ).encode()
    recognition_id = hashlib.sha256(identity).hexdigest()
    now = datetime.now(timezone.utc)
    return RecognitionManifest(
        recognitionId=recognition_id,
        projectId=sample.sample_id,
        sceneRevision=1,
        assetId=sample.image_sha256,
        pipelineVersion=RECOGNITION_PIPELINE_VERSION,
        status="review_required",
        coordinateSystem=RecognitionCoordinateSystem(),
        planWidthMeters=sample.plan_width_meters,
        confidence=result.get("confidence"),
        walls=result.get("walls", []),
        rooms=result.get("rooms", []),
        openings=result.get("openings", []),
        reviewReasons=result.get("reviewReasons", []),
        metrics=result.get("metrics"),
        overlay=RenderImageMetadata(
            sha256=overlay_sha256,
            bytes=size,
            width=width,
            height=height,
            url=f"/recognitions/{recognition_id}/overlay.png",
        ),
        createdAt=now,
        updatedAt=now,
    )


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = (
        "pending",
        "invalid",
        "recognition_failed",
        "scene_failed",
        "artifact_failed",
        "layout_failed",
        "publishable",
    )
    counts = {status: sum(result["status"] == status for result in results) for status in statuses}
    complete_samples = len(results) - counts["pending"]
    durations = [
        result["durationMilliseconds"]
        for result in results
        if result.get("durationMilliseconds") is not None
    ]
    return {
        "totalSamples": len(results),
        "completeSamples": complete_samples,
        "pendingSamples": counts["pending"],
        "invalidSamples": counts["invalid"],
        "recognitionFailedSamples": counts["recognition_failed"],
        "sceneFailedSamples": counts["scene_failed"],
        "artifactFailedSamples": counts["artifact_failed"],
        "layoutFailedSamples": counts["layout_failed"],
        "publishableSamples": counts["publishable"],
        "partialLayoutSamples": sum(
            result["status"] == "publishable"
            and any(layout["status"] != "ready" for layout in result["layouts"])
            for result in results
        ),
        "publishableRate": round(counts["publishable"] / complete_samples, 6)
        if complete_samples
        else None,
        "medianDurationMilliseconds": round(statistics.median(durations), 3)
        if durations
        else None,
    }


def evaluate_baseline_dataset(
    manifest_path: Path,
    *,
    optimizer: GlbOptimizer | None = None,
    recognition_backend: RecognitionBackend | None = None,
    style_directory: Path | None = None,
    asset_catalog_path: Path | None = None,
) -> dict[str, Any]:
    dataset = EvaluationDataset.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    recognizer = recognition_backend or OpenCvRecognitionBackend()
    artifact_optimizer = optimizer or NodeGlbOptimizer()
    style_catalog = StyleCatalog(style_directory)
    asset_catalog = AssetCatalog(asset_catalog_path)
    styles = style_catalog.list()
    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="floorplan-mainline-evaluation-") as temporary:
        work_root = Path(temporary)
        artifact_store = ArtifactStore(work_root / "artifacts")
        for sample in dataset.samples:
            if sample.annotation_status == "pending":
                results.append({"sampleId": sample.sample_id, "status": "pending"})
                continue
            started = time.perf_counter()
            try:
                image_path = _verified_image_path(manifest_path.parent, sample)
            except Exception as error:
                results.append(
                    {
                        "sampleId": sample.sample_id,
                        "status": "invalid",
                        "durationMilliseconds": round((time.perf_counter() - started) * 1000, 3),
                        "error": _error_text(error),
                    }
                )
                continue

            overlay_path = work_root / f"{sample.sample_id}-overlay.png"
            try:
                recognition_result = recognizer.recognize(
                    image_path,
                    sample.plan_width_meters,
                    overlay_path,
                )
                recognition = _recognition_manifest(sample, recognition_result, overlay_path)
            except Exception as error:
                results.append(
                    {
                        "sampleId": sample.sample_id,
                        "status": "recognition_failed",
                        "durationMilliseconds": round((time.perf_counter() - started) * 1000, 3),
                        "error": _error_text(error),
                    }
                )
                continue

            try:
                scene, room_types = build_baseline_scene(
                    recognition,
                    _input_asset(sample, image_path),
                )
            except Exception as error:
                results.append(
                    {
                        "sampleId": sample.sample_id,
                        "status": "scene_failed",
                        "durationMilliseconds": round((time.perf_counter() - started) * 1000, 3),
                        "recognition": {
                            "confidence": recognition.confidence,
                            "walls": len(recognition.walls),
                            "rooms": len(recognition.rooms),
                            "openings": len(recognition.openings),
                        },
                        "error": _error_text(error),
                    }
                )
                continue

            try:
                source_glb = build_structural_glb(scene["nodes"])
                artifact, should_optimize = artifact_store.begin(sample.sample_id, 2, source_glb)
                if should_optimize:
                    artifact_store.process(artifact.artifact_id, artifact_optimizer)
                artifact = artifact_store.load(artifact.artifact_id)
                if artifact is None or artifact.status != "ready" or artifact.optimized is None:
                    message = artifact.error if artifact is not None else "artifact disappeared"
                    raise RuntimeError(message or "artifact optimization failed")
            except Exception as error:
                results.append(
                    {
                        "sampleId": sample.sample_id,
                        "status": "artifact_failed",
                        "durationMilliseconds": round((time.perf_counter() - started) * 1000, 3),
                        "recognition": {
                            "confidence": recognition.confidence,
                            "walls": len(recognition.walls),
                            "rooms": len(recognition.rooms),
                            "openings": len(recognition.openings),
                        },
                        "error": _error_text(error),
                    }
                )
                continue

            layout_results: list[dict[str, Any]] = []
            failed_style_id: str | None = None
            layout_error: Exception | None = None
            for summary in styles:
                try:
                    style = style_catalog.get(summary.id)
                    if style is None:
                        raise RuntimeError(f"style disappeared: {summary.id}")
                    layout = generate_layout(
                        sample.sample_id,
                        2,
                        scene["nodes"],
                        style,
                        asset_catalog,
                    )
                    if not layout.furnished_room_ids:
                        raise RuntimeError("layout contains no furnished rooms")
                    layout_results.append(
                        {
                            "styleId": style.id,
                            "styleVersion": style.version,
                            "status": layout.status,
                            "roomCount": len(layout.rooms),
                            "furnishedRoomCount": len(layout.furnished_room_ids),
                            "placementCount": len(layout.placements),
                        }
                    )
                except Exception as error:
                    failed_style_id = summary.id
                    layout_error = error
                    break
            if layout_error is not None:
                results.append(
                    {
                        "sampleId": sample.sample_id,
                        "status": "layout_failed",
                        "durationMilliseconds": round((time.perf_counter() - started) * 1000, 3),
                        "failedStyleId": failed_style_id,
                        "layouts": layout_results,
                        "error": _error_text(layout_error),
                    }
                )
                continue

            results.append(
                {
                    "sampleId": sample.sample_id,
                    "status": "publishable",
                    "durationMilliseconds": round((time.perf_counter() - started) * 1000, 3),
                    "recognition": {
                        "confidence": recognition.confidence,
                        "walls": len(recognition.walls),
                        "rooms": len(recognition.rooms),
                        "openings": len(recognition.openings),
                    },
                    "scene": {
                        "walls": sum(node.get("type") == "wall" for node in scene["nodes"].values()),
                        "zones": sum(node.get("type") == "zone" for node in scene["nodes"].values()),
                        "autoRoomTypes": room_types,
                    },
                    "artifact": {
                        "pipelineVersion": artifact.pipeline_version,
                        "sourceBytes": artifact.source.bytes,
                        "optimizedBytes": artifact.optimized.bytes,
                    },
                    "layouts": layout_results,
                }
            )

    manifest_digest = hashlib.sha256(
        json.dumps(
            dataset.model_dump(by_alias=True, mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    identity = {
        "datasetId": dataset.dataset_id,
        "datasetVersion": dataset.dataset_version,
        "datasetManifestSha256": manifest_digest,
        "pipelineVersion": BASELINE_EVALUATION_PIPELINE_VERSION,
        "recognitionPipelineVersion": RECOGNITION_PIPELINE_VERSION,
        "baselinePipelineVersion": BASELINE_PIPELINE_VERSION,
        "artifactPipelineVersion": ARTIFACT_PIPELINE_VERSION,
        "layoutPipelineVersion": LAYOUT_PIPELINE_VERSION,
        "styles": [summary.model_dump() for summary in styles],
        "assetCatalog": {
            "id": asset_catalog.manifest.id,
            "version": asset_catalog.manifest.version,
        },
        "samples": [
            {"sampleId": sample.sample_id, "imageSha256": sample.image_sha256}
            for sample in dataset.samples
        ],
    }
    report_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schemaVersion": "1.0",
        "reportId": report_id,
        **identity,
        "aggregate": _aggregate(results),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate floor-plan recognition through the realtime 3D mainline"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = evaluate_baseline_dataset(arguments.manifest.resolve())
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if arguments.output:
        arguments.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
