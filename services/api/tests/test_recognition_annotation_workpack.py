from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from app.recognition_annotation_workpack import (
    CandidateReviewFile,
    build_annotation_workpack,
)
from app.recognition_candidates import CommonsCandidateQueue


def _image(path: Path) -> tuple[str, int]:
    image = np.full((80, 120, 3), 255, dtype=np.uint8)
    assert cv2.imwrite(str(path), image)
    content = path.read_bytes()
    return hashlib.sha256(content).hexdigest(), len(content)


def _queue(sha256: str, download_bytes: int) -> CommonsCandidateQueue:
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
                    "title": "Example floor plan",
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
                    "downloadBytes": download_bytes,
                }
            ],
        }
    )


def _reviews(**rights_overrides: object) -> CandidateReviewFile:
    rights: dict[str, object] = {
        "status": "pending",
        "commercialUseConfirmed": False,
        "redistributionAllowedConfirmed": False,
    }
    rights.update(rights_overrides)
    return CandidateReviewFile.model_validate(
        {
            "schemaVersion": "1.0",
            "reviews": [
                {
                    "candidateId": "commons-1",
                    "curation": {
                        "contentType": "floor-plan",
                        "targetDomain": "modern-residential",
                        "selectionStatus": "selected",
                        "selectionReasons": ["clear-single-floor-plan"],
                        "planWidthMeters": 10,
                        "scaleEvidence": "The drawing labels the outer width as 10 m.",
                        "reviewedBy": "test-curator",
                        "reviewedAt": "2026-07-16",
                    },
                    "rights": rights,
                }
            ],
        }
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


def test_review_contract_separates_selection_and_rights_decisions() -> None:
    with pytest.raises(ValidationError, match="must be floor plans"):
        payload = _reviews().model_dump(by_alias=True)
        payload["reviews"][0]["curation"]["contentType"] = "elevation"
        CandidateReviewFile.model_validate(payload)

    with pytest.raises(ValidationError, match="must confirm commercial use"):
        _reviews(
            status="approved",
            basis="Reviewed source page",
            reviewedBy="rights-owner",
            reviewedAt="2026-07-16",
        )

    with pytest.raises(ValidationError, match="cannot contain an approval"):
        _reviews(commercialUseConfirmed=True)

    approved = _reviews(
        status="approved",
        commercialUseConfirmed=True,
        redistributionAllowedConfirmed=True,
        basis="Reviewed the source page and license evidence.",
        reviewedBy="rights-owner",
        reviewedAt="2026-07-16",
    )
    assert approved.reviews[0].rights.status == "approved"


def test_documented_review_example_matches_runtime_contract() -> None:
    example = (
        Path(__file__).parents[3]
        / "datasets/recognition/candidate-reviews.example.json"
    )

    reviews = CandidateReviewFile.model_validate_json(example.read_text(encoding="utf-8"))

    assert reviews.reviews[0].curation.selection_status == "selected"
    assert reviews.reviews[0].rights.status == "pending"


def test_workpack_keeps_predictions_separate_from_ground_truth(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    sha256, download_bytes = _image(images / "commons-1.png")

    workpack = build_annotation_workpack(
        _queue(sha256, download_bytes),
        _reviews(),
        "commons-1",
        images,
        tmp_path / "overlay.png",
        FakeBackend(),
    )

    assert workpack.promotion_eligible is False
    assert workpack.blocking_reasons == ["rights_review_pending", "ground_truth_pending"]
    assert workpack.ground_truth.walls == []
    assert workpack.suggestions.is_ground_truth is False
    assert len(workpack.suggestions.walls) == 1
    assert workpack.suggestions.overlay is not None
    assert workpack.suggestions.overlay.sha256 == sha256
    assert len(workpack.workpack_id) == 64


def test_workpack_rejects_unselected_or_rights_rejected_candidate(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    sha256, download_bytes = _image(images / "commons-1.png")
    rejected = _reviews().model_dump(by_alias=True)
    rejected["reviews"][0]["curation"]["selectionStatus"] = "rejected"

    with pytest.raises(ValueError, match="rejected candidate"):
        build_annotation_workpack(
            _queue(sha256, download_bytes),
            CandidateReviewFile.model_validate(rejected),
            "commons-1",
            images,
            tmp_path / "overlay.png",
            FakeBackend(),
        )

    with pytest.raises(ValueError, match="rights-rejected"):
        build_annotation_workpack(
            _queue(sha256, download_bytes),
            _reviews(
                status="rejected",
                basis="Rights evidence was insufficient",
                reviewedBy="rights-owner",
                reviewedAt="2026-07-16",
            ),
            "commons-1",
            images,
            tmp_path / "overlay.png",
            FakeBackend(),
        )


def test_workpack_rejects_image_integrity_mismatch(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    _, download_bytes = _image(images / "commons-1.png")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        build_annotation_workpack(
            _queue("0" * 64, download_bytes),
            _reviews(),
            "commons-1",
            images,
            tmp_path / "overlay.png",
            FakeBackend(),
        )
