from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.recognition_annotation_review import (
    AnnotationReview,
    build_evaluation_sample,
    create_annotation_review,
    validate_annotation_review,
)
from app.recognition_annotation_submission import AnnotationSubmission


def _annotation_content() -> bytes:
    submission = AnnotationSubmission.model_validate(
        {
            "schemaVersion": "1.0",
            "workpackId": "a" * 64,
            "candidateId": "commons-1",
            "annotationStatus": "ready-for-review",
            "annotations": {
                "coordinateSystem": "plan-bottom-left-x-right-z-up-m",
                "walls": [
                    {
                        "id": "wall-1",
                        "start": [0, 0],
                        "end": [4, 0],
                        "thickness": 0.2,
                    }
                ],
                "rooms": [],
                "openings": [],
            },
            "annotatedBy": "annotator-a",
            "annotatedAt": "2026-07-17",
            "correctionSession": {
                "pipelineVersion": "opencv-axis-aligned-baseline-v1",
                "durationSeconds": 386.25,
            },
            "notes": "",
        }
    )
    return submission.model_dump_json(by_alias=True).encode()


def _workpack(
    image_sha256: str = "b" * 64,
    rights_status: str = "approved",
    redistribution_allowed: bool = False,
) -> SimpleNamespace:
    approved = rights_status == "approved"
    return SimpleNamespace(
        workpack_id="a" * 64,
        candidate=SimpleNamespace(
            candidate_id="commons-1",
            description_url="https://commons.wikimedia.org/wiki/File:Example",
            normalized_license_id="CC0-1.0",
            license_evidence_url=(
                "https://creativecommons.org/publicdomain/zero/1.0/"
            ),
        ),
        review=SimpleNamespace(
            candidate_id="commons-1",
            curation=SimpleNamespace(plan_width_meters=10),
            rights=SimpleNamespace(
                status=rights_status,
                commercial_use_confirmed=approved,
                redistribution_allowed_confirmed=redistribution_allowed,
                reviewed_by="rights-reviewer" if approved else None,
                reviewed_at="2026-07-17" if approved else None,
            ),
        ),
        suggestions=SimpleNamespace(
            pipeline_version="opencv-axis-aligned-baseline-v1",
            metrics=SimpleNamespace(
                plan_bounds_pixels=(0, 0, 1000, 600),
                pixels_per_meter=100,
            )
        ),
        image=SimpleNamespace(sha256=image_sha256),
    )


def test_changes_requested_review_requires_a_comment() -> None:
    with pytest.raises(ValidationError, match="requires a comment"):
        AnnotationReview.model_validate(
            {
                "schemaVersion": "1.0",
                "workpackId": "a" * 64,
                "candidateId": "commons-1",
                "submissionSha256": "b" * 64,
                "decision": "changes-requested",
                "reviewedBy": "reviewer-b",
                "reviewedAt": "2026-07-17",
                "comment": " ",
            }
        )

    with pytest.raises(ValidationError, match="reviewer must not be blank"):
        AnnotationReview.model_validate(
            {
                "schemaVersion": "1.0",
                "workpackId": "a" * 64,
                "candidateId": "commons-1",
                "submissionSha256": "b" * 64,
                "decision": "approved",
                "reviewedBy": " ",
                "reviewedAt": "2026-07-17",
            }
        )


def test_annotator_cannot_review_their_own_submission() -> None:
    with pytest.raises(ValueError, match="cannot review their own"):
        create_annotation_review(
            _workpack(),  # type: ignore[arg-type]
            _annotation_content(),
            "approved",
            "ANNOTATOR-A",
            "2026-07-17",
        )


def test_review_is_bound_to_exact_annotation_file_bytes() -> None:
    content = _annotation_content()
    review = create_annotation_review(
        _workpack(),  # type: ignore[arg-type]
        content,
        "approved",
        "reviewer-b",
        "2026-07-17",
    )

    assert review.submission_sha256 == hashlib.sha256(content).hexdigest()
    with pytest.raises(ValueError, match="does not match"):
        validate_annotation_review(
            _workpack(),  # type: ignore[arg-type]
            content + b"\n",
            review,
        )


def test_approved_review_promotes_a_complete_sample_with_provenance(tmp_path) -> None:
    image = tmp_path / "private" / "commons-1.png"
    image.parent.mkdir()
    image.write_bytes(b"audited image")
    image_sha256 = hashlib.sha256(image.read_bytes()).hexdigest()
    workpack = _workpack(image_sha256)
    content = _annotation_content()
    review = create_annotation_review(
        workpack,  # type: ignore[arg-type]
        content,
        "approved",
        "reviewer-b",
        "2026-07-17",
    )

    sample = build_evaluation_sample(
        workpack,  # type: ignore[arg-type]
        content,
        review,
        tmp_path,
        "commons-1",
        "private/commons-1.png",
        "calibration",
        "local-only",
        "Sanitized example floor plan",
        "Example author",
    )

    assert sample.annotation_status == "complete"
    assert sample.annotation_provenance is not None
    assert sample.annotation_provenance.annotated_by == "annotator-a"
    assert sample.annotation_provenance.reviewed_by == "reviewer-b"
    assert sample.annotations.walls[0].id == "wall-1"
    assert len(sample.correction_sessions) == 1
    assert sample.correction_sessions[0].pipeline_version == (
        "opencv-axis-aligned-baseline-v1"
    )
    assert sample.correction_sessions[0].duration_seconds == 386.25
    assert sample.correction_sessions[0].reviewer == "annotator-a"


def test_promotion_rejects_unapproved_rights_or_geometry_review(tmp_path) -> None:
    image = tmp_path / "private" / "commons-1.png"
    image.parent.mkdir()
    image.write_bytes(b"audited image")
    image_sha256 = hashlib.sha256(image.read_bytes()).hexdigest()
    content = _annotation_content()
    pending_workpack = _workpack(image_sha256, rights_status="pending")
    approved_review = create_annotation_review(
        pending_workpack,  # type: ignore[arg-type]
        content,
        "approved",
        "reviewer-b",
        "2026-07-17",
    )
    arguments = (
        tmp_path,
        "commons-1",
        "private/commons-1.png",
        "calibration",
        "local-only",
        "Sanitized example floor plan",
        "Example author",
    )

    with pytest.raises(ValueError, match="approved commercial"):
        build_evaluation_sample(
            pending_workpack,  # type: ignore[arg-type]
            content,
            approved_review,
            *arguments,
        )

    approved_candidate_review = _workpack(image_sha256).review
    promoted_after_rights_approval = build_evaluation_sample(
        pending_workpack,  # type: ignore[arg-type]
        content,
        approved_review,
        *arguments,
        candidate_review=approved_candidate_review,  # type: ignore[arg-type]
    )
    assert promoted_after_rights_approval.source.commercial_use_confirmed is True

    changed_curation = _workpack(image_sha256).review
    changed_curation.curation.plan_width_meters = 11
    with pytest.raises(ValueError, match="curation changed"):
        build_evaluation_sample(
            pending_workpack,  # type: ignore[arg-type]
            content,
            approved_review,
            *arguments,
            candidate_review=changed_curation,  # type: ignore[arg-type]
        )

    approved_workpack = _workpack(image_sha256)
    returned_review = create_annotation_review(
        approved_workpack,  # type: ignore[arg-type]
        content,
        "changes-requested",
        "reviewer-b",
        "2026-07-17",
        "Please correct the wall endpoint.",
    )
    with pytest.raises(ValueError, match="cannot be promoted"):
        build_evaluation_sample(
            approved_workpack,  # type: ignore[arg-type]
            content,
            returned_review,
            *arguments,
        )


def test_repository_promotion_requires_repository_path_and_redistribution(tmp_path) -> None:
    image = tmp_path / "private" / "commons-1.png"
    image.parent.mkdir()
    image.write_bytes(b"audited image")
    image_sha256 = hashlib.sha256(image.read_bytes()).hexdigest()
    workpack = _workpack(image_sha256, redistribution_allowed=False)
    content = _annotation_content()
    review = create_annotation_review(
        workpack,  # type: ignore[arg-type]
        content,
        "approved",
        "reviewer-b",
        "2026-07-17",
    )

    with pytest.raises(ValueError, match="repository samples must use"):
        build_evaluation_sample(
            workpack,  # type: ignore[arg-type]
            content,
            review,
            tmp_path,
            "commons-1",
            "private/commons-1.png",
            "test",
            "repository",
            "Sanitized example floor plan",
            "Example author",
        )


def test_promotion_requires_recorded_correction_time(tmp_path) -> None:
    image = tmp_path / "private" / "commons-1.png"
    image.parent.mkdir()
    image.write_bytes(b"audited image")
    workpack = _workpack(hashlib.sha256(image.read_bytes()).hexdigest())
    payload = AnnotationSubmission.model_validate_json(_annotation_content()).model_dump(
        by_alias=True,
        mode="json",
    )
    payload["correctionSession"] = None
    content = AnnotationSubmission.model_validate(payload).model_dump_json(
        by_alias=True
    ).encode()
    review = create_annotation_review(
        workpack,  # type: ignore[arg-type]
        content,
        "approved",
        "reviewer-b",
        "2026-07-17",
    )

    with pytest.raises(ValueError, match="recorded correction session"):
        build_evaluation_sample(
            workpack,  # type: ignore[arg-type]
            content,
            review,
            tmp_path,
            "commons-1",
            "private/commons-1.png",
            "calibration",
            "local-only",
            "Sanitized example floor plan",
            "Example author",
        )
