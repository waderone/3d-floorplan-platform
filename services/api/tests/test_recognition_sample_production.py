from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.recognition_annotation_review import (
    build_evaluation_sample,
    create_annotation_review,
)
from app.recognition_annotation_workpack import AnnotationWorkpack, CandidateReviewFile
from app.recognition_candidates import CommonsCandidateQueue
from app.recognition_evaluation import EvaluationDataset
from app.recognition_batch_release import (
    build_promoted_dataset,
    release_promoted_batch,
    write_dataset_manifest,
)
from app.recognition_sample_production import (
    build_production_report,
    prepare_selected_workpacks,
)


class FakeBackend:
    def recognize(
        self,
        image_path: Path,
        plan_width_meters: float,
        overlay_path: Path,
    ) -> dict[str, object]:
        image = cv2.imread(str(image_path))
        assert image is not None
        assert plan_width_meters == 10
        assert cv2.imwrite(str(overlay_path), image)
        return {
            "confidence": 0.5,
            "walls": [
                {
                    "id": "wall-suggestion-1",
                    "start": [0, 0],
                    "end": [10, 0],
                    "thickness": 0.2,
                    "confidence": 0.8,
                }
            ],
            "rooms": [],
            "openings": [],
            "reviewReasons": ["manual_review_required"],
            "metrics": {
                "imageWidthPixels": 120,
                "imageHeightPixels": 80,
                "planBoundsPixels": [0, 0, 119, 79],
                "pixelsPerMeter": 12,
                "otsuThreshold": 200,
                "structuralPixelRatio": 0.1,
            },
        }


def _image(path: Path) -> tuple[str, int]:
    image = np.full((80, 120, 3), 255, dtype=np.uint8)
    assert cv2.imwrite(str(path), image)
    content = path.read_bytes()
    return hashlib.sha256(content).hexdigest(), len(content)


def _queue(sha256: str, size: int) -> CommonsCandidateQueue:
    return CommonsCandidateQueue.model_validate(
        {
            "schemaVersion": "1.0",
            "provider": "wikimedia-commons",
            "category": "Category:Floor plans of houses",
            "requestedLimit": 1,
            "candidates": [
                {
                    "candidateId": "commons-1",
                    "pageId": 1,
                    "title": "Private title is not copied to the report",
                    "author": "Example author",
                    "descriptionUrl": "https://commons.wikimedia.org/wiki/File:Example",
                    "originalUrl": "https://upload.wikimedia.org/example.png",
                    "downloadUrl": "https://upload.wikimedia.org/example-thumb.png",
                    "mimeType": "image/png",
                    "sourceWidth": 120,
                    "sourceHeight": 80,
                    "providerSha1": "1" * 40,
                    "reportedLicenseLabel": "CC0",
                    "normalizedLicenseId": "CC0-1.0",
                    "licenseEvidenceUrl": (
                        "https://creativecommons.org/publicdomain/zero/1.0/"
                    ),
                    "rightsReviewStatus": "pending",
                    "commercialUseConfirmed": False,
                    "redistributionAllowedConfirmed": False,
                    "selectionStatus": "pending",
                    "downloadStatus": "downloaded",
                    "downloadFile": "commons-1.png",
                    "downloadSha256": sha256,
                    "downloadBytes": size,
                }
            ],
        }
    )


def _reviews(
    *,
    candidate_id: str = "commons-1",
    selection_status: str = "selected",
    rights_status: str = "pending",
) -> CandidateReviewFile:
    rights: dict[str, object] = {
        "status": rights_status,
        "commercialUseConfirmed": rights_status == "approved",
        "redistributionAllowedConfirmed": rights_status == "approved",
    }
    if rights_status != "pending":
        rights.update(
            basis="Human reviewed the source and license evidence.",
            reviewedBy="rights-reviewer",
            reviewedAt="2026-07-21",
        )
    return CandidateReviewFile.model_validate(
        {
            "schemaVersion": "1.0",
            "reviews": [
                {
                    "candidateId": candidate_id,
                    "curation": {
                        "contentType": "floor-plan",
                        "targetDomain": "modern-residential",
                        "selectionStatus": selection_status,
                        "selectionReasons": ["clear-single-floor-plan"],
                        "planWidthMeters": 10,
                        "scaleEvidence": "The drawing labels the outer width as 10 m.",
                        "reviewedBy": "test-curator",
                        "reviewedAt": "2026-07-21",
                    },
                    "rights": rights,
                }
            ],
        }
    )


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(value, "model_dump"):
        value = value.model_dump(by_alias=True, mode="json")  # type: ignore[union-attr]
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _ready_annotation(workpack_id: str) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "workpackId": workpack_id,
        "candidateId": "commons-1",
        "annotationStatus": "ready-for-review",
        "annotations": {
            "coordinateSystem": "plan-bottom-left-x-right-z-up-m",
            "walls": [
                {
                    "id": "wall-1",
                    "start": [0, 0],
                    "end": [5, 0],
                    "thickness": 0.2,
                }
            ],
            "rooms": [],
            "openings": [],
        },
        "annotatedBy": "annotator-a",
        "annotatedAt": "2026-07-21",
        "correctionSession": {
            "pipelineVersion": "opencv-axis-aligned-baseline-v1",
            "durationSeconds": 180,
        },
        "notes": "",
    }


def test_report_tracks_unreviewed_rejected_and_invalid_candidates(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    sha256, size = _image(images / "commons-1.png")
    queue = _queue(sha256, size)

    unreviewed = build_production_report(
        queue,
        _reviews(candidate_id="commons-2"),
        images,
        tmp_path / "production",
    )
    assert unreviewed.candidates[0].stage == "curation-required"
    assert unreviewed.candidates[0].model_dump_json().find("Private title") == -1

    rejected = build_production_report(
        queue,
        _reviews(selection_status="rejected"),
        images,
        tmp_path / "production",
    )
    assert rejected.candidates[0].stage == "curation-rejected"

    (images / "commons-1.png").write_bytes(b"damaged")
    invalid = build_production_report(
        queue,
        _reviews(),
        images,
        tmp_path / "production",
    )
    assert invalid.candidates[0].stage == "invalid"
    assert invalid.candidates[0].blockers == ["candidate_image_invalid"]


def test_prepare_is_idempotent_and_report_tracks_annotation_workflow(
    tmp_path: Path,
) -> None:
    images = tmp_path / "images"
    images.mkdir()
    sha256, size = _image(images / "commons-1.png")
    queue = _queue(sha256, size)
    reviews = _reviews()
    production = tmp_path / "production"

    assert build_production_report(queue, reviews, images, production).candidates[0].stage == (
        "workpack-required"
    )
    created = prepare_selected_workpacks(
        queue,
        reviews,
        images,
        production,
        FakeBackend(),
    )
    assert created[0].result == "created"
    existing = prepare_selected_workpacks(
        queue,
        reviews,
        images,
        production,
        FakeBackend(),
    )
    assert existing[0].result == "existing"
    report = build_production_report(queue, reviews, images, production)
    assert report.candidates[0].stage == "annotation-required"
    assert report.candidates[0].artifacts.workpack_sha256 is not None
    assert report.candidates[0].artifacts.annotation_sha256 is None
    assert report.report_id == build_production_report(
        queue, reviews, images, production
    ).report_id

    candidate_root = production / "commons-1"
    workpack = json.loads((candidate_root / "workpack.json").read_text())
    draft = _ready_annotation(workpack["workpackId"])
    draft["annotationStatus"] = "draft"
    draft["annotatedBy"] = None
    draft["annotatedAt"] = None
    draft["correctionSession"] = None
    _write(candidate_root / "annotation.json", draft)
    draft_report = build_production_report(queue, reviews, images, production)
    assert draft_report.candidates[0].stage == "annotation-in-progress"
    draft["notes"] = "A changed draft must change the report identity."
    _write(candidate_root / "annotation.json", draft)
    assert build_production_report(
        queue, reviews, images, production
    ).report_id != draft_report.report_id

    _write(candidate_root / "annotation.json", _ready_annotation(workpack["workpackId"]))
    assert build_production_report(queue, reviews, images, production).candidates[0].stage == (
        "geometry-review-required"
    )

    untimed = _ready_annotation(workpack["workpackId"])
    untimed["correctionSession"] = None
    _write(candidate_root / "annotation.json", untimed)
    invalid = build_production_report(queue, reviews, images, production).candidates[0]
    assert invalid.stage == "invalid"
    assert invalid.blockers == ["correction_session_missing"]

    stale_workpack = json.loads((candidate_root / "workpack.json").read_text())
    stale_workpack["candidate"]["candidateId"] = "commons-2"
    _write(candidate_root / "workpack.json", stale_workpack)
    invalid = build_production_report(queue, reviews, images, production).candidates[0]
    assert invalid.stage == "invalid"
    assert invalid.blockers == ["workpack_invalid"]


def test_report_tracks_review_rights_promotion_and_complete_sample(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    sha256, size = _image(images / "commons-1.png")
    queue = _queue(sha256, size)
    pending_reviews = _reviews()
    production = tmp_path / "production"
    prepare_selected_workpacks(
        queue,
        pending_reviews,
        images,
        production,
        FakeBackend(),
    )
    candidate_root = production / "commons-1"
    workpack = AnnotationWorkpack.model_validate_json(
        (candidate_root / "workpack.json").read_text()
    )
    _write(candidate_root / "annotation.json", _ready_annotation(workpack.workpack_id))
    annotation_content = (candidate_root / "annotation.json").read_bytes()

    returned = create_annotation_review(
        workpack,
        annotation_content,
        "changes-requested",
        "reviewer-b",
        "2026-07-21",
        "Correct the wall endpoint.",
    )
    _write(candidate_root / "review.json", returned)
    assert build_production_report(
        queue, pending_reviews, images, production
    ).candidates[0].stage == "changes-requested"

    approved = create_annotation_review(
        workpack,
        annotation_content,
        "approved",
        "reviewer-b",
        "2026-07-21",
    )
    _write(candidate_root / "review.json", approved)
    assert build_production_report(
        queue, pending_reviews, images, production
    ).candidates[0].stage == "rights-review-required"

    approved_reviews = _reviews(rights_status="approved")
    assert build_production_report(
        queue, approved_reviews, images, production
    ).candidates[0].stage == "promotion-required"

    dataset_image = tmp_path / "private" / "commons-1.png"
    dataset_image.parent.mkdir()
    dataset_image.write_bytes((images / "commons-1.png").read_bytes())
    sample = build_evaluation_sample(
        workpack,
        annotation_content,
        approved,
        tmp_path,
        "commons-1",
        "private/commons-1.png",
        "calibration",
        "local-only",
        "Sanitized floor plan",
        "Verified author",
        candidate_review=approved_reviews.reviews[0],
    )
    _write(candidate_root / "sample.json", sample)
    complete = build_production_report(queue, approved_reviews, images, production)
    assert complete.candidates[0].stage == "promoted"
    assert complete.stage_counts == {"promoted": 1}

    dataset = build_promoted_dataset(
        complete,
        production,
        tmp_path,
        "commercial-floorplans",
        1,
    )
    assert [sample.sample_id for sample in dataset.samples] == ["commons-1"]
    manifest = tmp_path / "manifest.json"
    assert write_dataset_manifest(manifest, dataset) == "created"
    assert write_dataset_manifest(manifest, dataset) == "existing"

    summary = release_promoted_batch(
        queue,
        approved_reviews,
        images,
        production,
        tmp_path,
        "commercial-floorplans",
        1,
        manifest,
        tmp_path / "reports",
    )
    assert summary["dataset"] == {
        "id": "commercial-floorplans",
        "version": 1,
        "sampleCount": 1,
        "manifestSha256": summary["dataset"]["manifestSha256"],
        "manifestResult": "existing",
    }
    assert len(summary["dataset"]["manifestSha256"]) == 64
    assert summary["production"]["stageCounts"] == {"promoted": 1}
    assert summary["mainline"]["aggregate"]["completeSamples"] == 1
    assert {path.name for path in (tmp_path / "reports").iterdir()} == {
        "batch-summary.json",
        "mainline-report.json",
        "production-report.json",
        "recognition-report.json",
    }
    repeated = release_promoted_batch(
        queue,
        approved_reviews,
        images,
        production,
        tmp_path,
        "commercial-floorplans",
        1,
        manifest,
        tmp_path / "reports",
    )
    assert repeated["batchId"] == summary["batchId"]


def test_batch_release_refuses_unpromoted_or_changed_manifest(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    sha256, size = _image(images / "commons-1.png")
    queue = _queue(sha256, size)
    report = build_production_report(
        queue,
        _reviews(),
        images,
        tmp_path / "production",
    )
    with pytest.raises(ValueError, match="no promoted samples"):
        build_promoted_dataset(
            report,
            tmp_path / "production",
            tmp_path,
            "commercial-floorplans",
            1,
        )

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "datasetId": "commercial-floorplans",
                "datasetVersion": 1,
                "samples": [
                    {
                        "sampleId": "existing",
                        "imagePath": "images/existing.png",
                        "imageSha256": "a" * 64,
                        "planWidthMeters": 10,
                        "split": "test",
                        "annotationStatus": "complete",
                        "source": {
                            "sourceType": "project-owned",
                            "title": "Existing",
                            "author": "Project",
                            "sourceUrl": "https://example.com/existing",
                            "licenseId": "Project-Owned",
                            "licenseUrl": "https://example.com/license",
                            "rightsEvidenceUrl": "https://example.com/rights",
                            "commercialUseConfirmed": True,
                            "redistributionAllowed": False,
                            "storageMode": "local-only",
                            "reviewedBy": "rights-reviewer",
                            "reviewedAt": "2026-07-21",
                        },
                        "annotations": {
                            "coordinateSystem": "plan-bottom-left-x-right-z-up-m",
                            "walls": [
                                {
                                    "id": "wall-1",
                                    "start": [0, 0],
                                    "end": [1, 0],
                                    "thickness": 0.2,
                                }
                            ],
                            "rooms": [],
                            "openings": [],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    changed = json.loads(manifest.read_text(encoding="utf-8"))
    changed["samples"][0]["sampleId"] = "changed"
    with pytest.raises(ValueError, match="increment datasetVersion"):
        write_dataset_manifest(manifest, EvaluationDataset.model_validate(changed))
