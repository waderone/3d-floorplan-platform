from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .recognition_annotation_workpack import AnnotationWorkpack
from .recognition_evaluation import EvaluationAnnotations


class AnnotationSubmission(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    workpack_id: str = Field(alias="workpackId", pattern=r"^[0-9a-f]{64}$")
    candidate_id: str = Field(alias="candidateId", pattern=r"^commons-[1-9][0-9]*$")
    annotation_status: Literal["draft", "ready-for-review"] = Field(
        alias="annotationStatus"
    )
    annotations: EvaluationAnnotations
    annotated_by: str | None = Field(
        alias="annotatedBy",
        default=None,
        min_length=1,
        max_length=100,
    )
    annotated_at: str | None = Field(
        alias="annotatedAt",
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_annotation_state(self) -> "AnnotationSubmission":
        ids = [item.id for item in self.annotations.walls]
        ids.extend(item.id for item in self.annotations.rooms)
        ids.extend(item.id for item in self.annotations.openings)
        if len(ids) != len(set(ids)):
            raise ValueError("annotation ids must be unique")
        if self.annotation_status == "ready-for-review":
            if not self.annotations.walls:
                raise ValueError("review-ready annotation must include at least one wall")
            if not self.annotated_by or not self.annotated_at:
                raise ValueError("review-ready annotation requires annotator and date")
        return self


def validate_submission_identity(
    workpack: AnnotationWorkpack,
    submission: AnnotationSubmission,
) -> dict[str, object]:
    if submission.workpack_id != workpack.workpack_id:
        raise ValueError("annotation belongs to another workpack")
    if submission.candidate_id != workpack.candidate.candidate_id:
        raise ValueError("annotation belongs to another candidate")
    plan_width = workpack.review.curation.plan_width_meters
    metrics = workpack.suggestions.metrics
    points = [
        point
        for wall in submission.annotations.walls
        for point in (wall.start, wall.end)
    ]
    points.extend(
        point for room in submission.annotations.rooms for point in room.polygon
    )
    points.extend(opening.center for opening in submission.annotations.openings)
    if points:
        if plan_width is None or metrics is None:
            raise ValueError("workpack lacks calibration for annotation geometry")
        bounds = metrics.plan_bounds_pixels
        plan_height = (bounds[3] - bounds[1]) / metrics.pixels_per_meter
        epsilon = 1e-6
        if any(
            point[0] < -epsilon
            or point[0] > plan_width + epsilon
            or point[1] < -epsilon
            or point[1] > plan_height + epsilon
            for point in points
        ):
            raise ValueError("annotation geometry is outside the calibrated plan bounds")
    return {
        "candidateId": submission.candidate_id,
        "workpackId": submission.workpack_id,
        "annotationStatus": submission.annotation_status,
        "walls": len(submission.annotations.walls),
        "rooms": len(submission.annotations.rooms),
        "openings": len(submission.annotations.openings),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate an exported ground-truth annotation submission"
    )
    parser.add_argument("--workpack", type=Path, required=True)
    parser.add_argument("--annotation", type=Path, required=True)
    arguments = parser.parse_args()

    workpack = AnnotationWorkpack.model_validate_json(
        arguments.workpack.read_text(encoding="utf-8")
    )
    submission = AnnotationSubmission.model_validate_json(
        arguments.annotation.read_text(encoding="utf-8")
    )
    summary = validate_submission_identity(workpack, submission)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
