from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.recognition_annotation_submission import (
    AnnotationSubmission,
    validate_submission_identity,
)


def _submission(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": "1.0",
        "workpackId": "a" * 64,
        "candidateId": "commons-1",
        "annotationStatus": "draft",
        "annotations": {
            "coordinateSystem": "plan-bottom-left-x-right-z-up-m",
            "walls": [],
            "rooms": [],
            "openings": [],
        },
        "annotatedBy": None,
        "annotatedAt": None,
        "notes": "",
    }
    value.update(overrides)
    return value


def _wall(identifier: str = "wall-1") -> dict[str, object]:
    return {
        "id": identifier,
        "start": [0, 0],
        "end": [4, 0],
        "thickness": 0.2,
    }


def _workpack() -> SimpleNamespace:
    return SimpleNamespace(
        workpack_id="a" * 64,
        candidate=SimpleNamespace(candidate_id="commons-1"),
        review=SimpleNamespace(curation=SimpleNamespace(plan_width_meters=10)),
        suggestions=SimpleNamespace(
            metrics=SimpleNamespace(
                plan_bounds_pixels=(100, 100, 1100, 700),
                pixels_per_meter=100,
            )
        ),
    )


def test_draft_may_be_saved_before_geometry_or_signature() -> None:
    submission = AnnotationSubmission.model_validate(_submission())

    assert submission.annotation_status == "draft"
    assert submission.annotations.walls == []


def test_review_ready_requires_wall_annotator_and_date() -> None:
    with pytest.raises(ValidationError, match="at least one wall"):
        AnnotationSubmission.model_validate(
            _submission(
                annotationStatus="ready-for-review",
                annotatedBy="curator",
                annotatedAt="2026-07-17",
            )
        )

    annotations = _submission()["annotations"]
    assert isinstance(annotations, dict)
    annotations["walls"] = [_wall()]
    ready = AnnotationSubmission.model_validate(
        _submission(
            annotationStatus="ready-for-review",
            annotations=annotations,
            annotatedBy="curator",
            annotatedAt="2026-07-17",
        )
    )
    assert ready.annotations.walls[0].id == "wall-1"

    with pytest.raises(ValidationError, match="must not be blank"):
        AnnotationSubmission.model_validate(
            _submission(
                annotationStatus="ready-for-review",
                annotations=annotations,
                annotatedBy=" ",
                annotatedAt="2026-07-17",
            )
        )


def test_submission_rejects_duplicate_geometry_ids() -> None:
    annotations = _submission()["annotations"]
    assert isinstance(annotations, dict)
    annotations["walls"] = [_wall("duplicate")]
    annotations["openings"] = [
        {"id": "duplicate", "kind": "door", "center": [2, 0], "width": 0.9}
    ]

    with pytest.raises(ValidationError, match="ids must be unique"):
        AnnotationSubmission.model_validate(_submission(annotations=annotations))


def test_submission_identity_must_match_workpack_and_candidate() -> None:
    submission = AnnotationSubmission.model_validate(_submission())
    workpack = _workpack()

    summary = validate_submission_identity(workpack, submission)  # type: ignore[arg-type]
    assert summary["walls"] == 0

    workpack.workpack_id = "b" * 64
    with pytest.raises(ValueError, match="another workpack"):
        validate_submission_identity(workpack, submission)  # type: ignore[arg-type]


def test_submission_geometry_must_stay_inside_workpack_calibration() -> None:
    annotations = _submission()["annotations"]
    assert isinstance(annotations, dict)
    annotations["walls"] = [
        {**_wall(), "end": [10.001, 0]},
    ]
    submission = AnnotationSubmission.model_validate(
        _submission(annotations=annotations)
    )

    with pytest.raises(ValueError, match="outside the calibrated plan bounds"):
        validate_submission_identity(_workpack(), submission)  # type: ignore[arg-type]
