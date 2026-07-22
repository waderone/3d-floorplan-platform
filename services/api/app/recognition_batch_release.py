from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from .artifacts import GlbOptimizer
from .baseline_evaluation import evaluate_baseline_dataset
from .recognition_annotation_workpack import CandidateReviewFile
from .recognition_candidates import CommonsCandidateQueue
from .recognition_evaluation import (
    EvaluationDataset,
    EvaluationSample,
    _verified_image_path,
    evaluate_dataset,
)
from .recognition_sample_production import (
    ProductionReport,
    build_production_report,
)


def _canonical_payload(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_promoted_dataset(
    production_report: ProductionReport,
    production_root: Path,
    dataset_root: Path,
    dataset_id: str,
    dataset_version: int,
) -> EvaluationDataset:
    invalid_promotions = [
        item.candidate_id
        for item in production_report.candidates
        if item.artifacts.sample and item.stage != "promoted"
    ]
    if invalid_promotions:
        raise ValueError(
            "invalid promoted sample artifacts: " + ", ".join(invalid_promotions)
        )

    promoted = [
        item for item in production_report.candidates if item.stage == "promoted"
    ]
    if not promoted:
        raise ValueError("no promoted samples are ready for a dataset release")

    samples: list[EvaluationSample] = []
    for item in promoted:
        sample_path = production_root / item.candidate_id / "sample.json"
        sample = EvaluationSample.model_validate_json(
            sample_path.read_text(encoding="utf-8")
        )
        _verified_image_path(dataset_root, sample)
        samples.append(sample)

    return EvaluationDataset(
        schemaVersion="1.0",
        datasetId=dataset_id,
        datasetVersion=dataset_version,
        samples=sorted(samples, key=lambda sample: sample.sample_id),
    )


def write_dataset_manifest(
    manifest_path: Path,
    dataset: EvaluationDataset,
) -> Literal["created", "existing"]:
    payload = dataset.model_dump(by_alias=True, mode="json")
    if manifest_path.is_file():
        existing = EvaluationDataset.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        if existing != dataset:
            raise ValueError(
                "manifest already exists with different content; increment datasetVersion"
            )
        return "existing"
    _write_json(manifest_path, payload)
    return "created"


def release_promoted_batch(
    queue: CommonsCandidateQueue,
    reviews: CandidateReviewFile,
    image_directory: Path,
    production_root: Path,
    dataset_root: Path,
    dataset_id: str,
    dataset_version: int,
    manifest_path: Path,
    reports_directory: Path,
    optimizer: GlbOptimizer | None = None,
) -> dict[str, Any]:
    if manifest_path.parent.resolve() != dataset_root.resolve():
        raise ValueError("manifest must be written directly inside dataset-root")
    production_report = build_production_report(
        queue,
        reviews,
        image_directory,
        production_root,
    )
    dataset = build_promoted_dataset(
        production_report,
        production_root,
        dataset_root,
        dataset_id,
        dataset_version,
    )
    manifest_result = write_dataset_manifest(manifest_path, dataset)
    manifest_payload = dataset.model_dump(by_alias=True, mode="json")
    manifest_sha256 = hashlib.sha256(_canonical_payload(manifest_payload)).hexdigest()

    recognition_report = evaluate_dataset(manifest_path.resolve())
    mainline_report = evaluate_baseline_dataset(
        manifest_path.resolve(),
        optimizer=optimizer,
    )
    identity = {
        "datasetManifestSha256": manifest_sha256,
        "productionReportId": production_report.report_id,
        "recognitionReportId": recognition_report["reportId"],
        "mainlineReportId": mainline_report["reportId"],
    }
    summary = {
        "schemaVersion": "1.0",
        "batchId": hashlib.sha256(_canonical_payload(identity)).hexdigest(),
        "dataset": {
            "id": dataset.dataset_id,
            "version": dataset.dataset_version,
            "sampleCount": len(dataset.samples),
            "manifestSha256": manifest_sha256,
            "manifestResult": manifest_result,
        },
        "production": {
            "reportId": production_report.report_id,
            "stageCounts": production_report.stage_counts,
        },
        "recognition": {
            "reportId": recognition_report["reportId"],
            "aggregate": recognition_report["aggregate"],
        },
        "mainline": {
            "reportId": mainline_report["reportId"],
            "aggregate": mainline_report["aggregate"],
        },
    }

    _write_json(
        reports_directory / "production-report.json",
        production_report.model_dump(by_alias=True, mode="json"),
    )
    _write_json(reports_directory / "recognition-report.json", recognition_report)
    _write_json(reports_directory / "mainline-report.json", mainline_report)
    _write_json(reports_directory / "batch-summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Release promoted floor-plan samples and run both evaluation gates"
    )
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--production-root", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-version", type=int, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--reports-dir", type=Path, required=True)
    arguments = parser.parse_args()

    queue = CommonsCandidateQueue.model_validate_json(
        arguments.queue.read_text(encoding="utf-8")
    )
    reviews = CandidateReviewFile.model_validate_json(
        arguments.reviews.read_text(encoding="utf-8")
    )
    summary = release_promoted_batch(
        queue,
        reviews,
        arguments.image_dir,
        arguments.production_root,
        arguments.dataset_root,
        arguments.dataset_id,
        arguments.dataset_version,
        arguments.manifest,
        arguments.reports_dir,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
