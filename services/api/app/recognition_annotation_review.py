from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .recognition_annotation_submission import (
    AnnotationSubmission,
    validate_submission_identity,
)
from .recognition_annotation_workpack import (
    AnnotationWorkpack,
    CandidateReviewFile,
    CandidateReviewRecord,
)
from .recognition_evaluation import EvaluationSample


class AnnotationReview(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    workpack_id: str = Field(alias="workpackId", pattern=r"^[0-9a-f]{64}$")
    candidate_id: str = Field(alias="candidateId", pattern=r"^commons-[1-9][0-9]*$")
    submission_sha256: str = Field(
        alias="submissionSha256",
        pattern=r"^[0-9a-f]{64}$",
    )
    decision: Literal["approved", "changes-requested"]
    reviewed_by: str = Field(alias="reviewedBy", min_length=1, max_length=100)
    reviewed_at: str = Field(
        alias="reviewedAt",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    comment: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_decision_comment(self) -> "AnnotationReview":
        if not self.reviewed_by.strip():
            raise ValueError("reviewer must not be blank")
        if self.decision == "changes-requested" and not (self.comment or "").strip():
            raise ValueError("changes-requested review requires a comment")
        return self


def _annotation_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def validate_annotation_review(
    workpack: AnnotationWorkpack,
    annotation_content: bytes,
    review: AnnotationReview,
) -> AnnotationSubmission:
    submission = AnnotationSubmission.model_validate_json(annotation_content)
    validate_submission_identity(workpack, submission)
    if submission.annotation_status != "ready-for-review":
        raise ValueError("only ready-for-review annotations can be reviewed")
    if review.workpack_id != workpack.workpack_id:
        raise ValueError("review belongs to another workpack")
    if review.candidate_id != workpack.candidate.candidate_id:
        raise ValueError("review belongs to another candidate")
    if review.submission_sha256 != _annotation_sha256(annotation_content):
        raise ValueError("review does not match the annotation file content")
    if submission.annotated_by is None:
        raise ValueError("review-ready annotation must identify its annotator")
    if review.reviewed_by.strip().casefold() == submission.annotated_by.strip().casefold():
        raise ValueError("annotator cannot review their own annotation")
    return submission


def create_annotation_review(
    workpack: AnnotationWorkpack,
    annotation_content: bytes,
    decision: Literal["approved", "changes-requested"],
    reviewed_by: str,
    reviewed_at: str,
    comment: str | None = None,
) -> AnnotationReview:
    review = AnnotationReview(
        schemaVersion="1.0",
        workpackId=workpack.workpack_id,
        candidateId=workpack.candidate.candidate_id,
        submissionSha256=_annotation_sha256(annotation_content),
        decision=decision,
        reviewedBy=reviewed_by.strip(),
        reviewedAt=reviewed_at,
        comment=comment.strip() if comment and comment.strip() else None,
    )
    validate_annotation_review(workpack, annotation_content, review)
    return review


def build_evaluation_sample(
    workpack: AnnotationWorkpack,
    annotation_content: bytes,
    review: AnnotationReview,
    dataset_root: Path,
    sample_id: str,
    image_path: str,
    split: Literal["calibration", "validation", "test"],
    storage_mode: Literal["repository", "local-only"],
    source_title: str,
    source_author: str,
    candidate_review: CandidateReviewRecord | None = None,
) -> EvaluationSample:
    submission = validate_annotation_review(workpack, annotation_content, review)
    if review.decision != "approved":
        raise ValueError("changes-requested annotation cannot be promoted")
    promotion_review = candidate_review or workpack.review
    if promotion_review.candidate_id != workpack.candidate.candidate_id:
        raise ValueError("promotion review belongs to another candidate")
    if promotion_review.curation != workpack.review.curation:
        raise ValueError("curation changed after the annotation workpack was created")
    rights = promotion_review.rights
    if rights.status != "approved" or not rights.commercial_use_confirmed:
        raise ValueError("promotion requires approved commercial evaluation rights")
    if rights.reviewed_by is None or rights.reviewed_at is None:
        raise ValueError("approved rights review must identify its reviewer and date")

    relative_image_path = Path(image_path)
    if relative_image_path.is_absolute() or ".." in relative_image_path.parts:
        raise ValueError("imagePath must stay inside the dataset directory")
    expected_directory = "images" if storage_mode == "repository" else "private"
    if not relative_image_path.parts or relative_image_path.parts[0] != expected_directory:
        raise ValueError(f"{storage_mode} samples must use the {expected_directory}/ directory")
    image_file = dataset_root / relative_image_path
    if not image_file.is_file():
        raise FileNotFoundError(f"promoted image is missing: {image_path}")
    if hashlib.sha256(image_file.read_bytes()).hexdigest() != workpack.image.sha256:
        raise ValueError("promoted image SHA-256 does not match the workpack")

    candidate = workpack.candidate
    curation = promotion_review.curation
    if curation.plan_width_meters is None:
        raise ValueError("workpack does not contain a calibrated plan width")
    if submission.annotated_by is None or submission.annotated_at is None:
        raise ValueError("review-ready annotation must identify its annotator and date")
    if submission.correction_session is None:
        raise ValueError("promotion requires a recorded correction session")
    normalized_title = source_title.strip()
    normalized_author = source_author.strip()
    if not normalized_title or not normalized_author:
        raise ValueError("promoted source title and author must not be blank")

    return EvaluationSample(
        sampleId=sample_id,
        imagePath=relative_image_path.as_posix(),
        imageSha256=workpack.image.sha256,
        planWidthMeters=curation.plan_width_meters,
        split=split,
        annotationStatus="complete",
        source={
            "sourceType": "public-domain",
            "title": normalized_title,
            "author": normalized_author,
            "sourceUrl": candidate.description_url,
            "licenseId": candidate.normalized_license_id,
            "licenseUrl": candidate.license_evidence_url,
            "rightsEvidenceUrl": candidate.description_url,
            "commercialUseConfirmed": rights.commercial_use_confirmed,
            "redistributionAllowed": rights.redistribution_allowed_confirmed,
            "storageMode": storage_mode,
            "reviewedBy": rights.reviewed_by,
            "reviewedAt": rights.reviewed_at,
        },
        annotations=submission.annotations,
        annotationProvenance={
            "workpackId": workpack.workpack_id,
            "submissionSha256": review.submission_sha256,
            "annotatedBy": submission.annotated_by,
            "annotatedAt": submission.annotated_at,
            "reviewedBy": review.reviewed_by,
            "reviewedAt": review.reviewed_at,
        },
        correctionSessions=[
            {
                "pipelineVersion": submission.correction_session.pipeline_version,
                "durationSeconds": submission.correction_session.duration_seconds,
                "reviewer": submission.annotated_by,
                "completedAt": submission.annotated_at,
            }
        ],
    )


def _write_json(path: Path, value: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(value.model_dump(by_alias=True, mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_workpack(path: Path) -> AnnotationWorkpack:
    return AnnotationWorkpack.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Review a ground-truth annotation and promote approved data"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    review_parser = commands.add_parser("review", help="create a bound review record")
    review_parser.add_argument("--workpack", type=Path, required=True)
    review_parser.add_argument("--annotation", type=Path, required=True)
    review_parser.add_argument(
        "--decision",
        choices=["approved", "changes-requested"],
        required=True,
    )
    review_parser.add_argument("--reviewed-by", required=True)
    review_parser.add_argument("--reviewed-at", required=True)
    review_parser.add_argument("--comment")
    review_parser.add_argument("--output", type=Path, required=True)

    promote_parser = commands.add_parser(
        "promote",
        help="create an evaluation sample from an approved review",
    )
    promote_parser.add_argument("--workpack", type=Path, required=True)
    promote_parser.add_argument("--annotation", type=Path, required=True)
    promote_parser.add_argument("--review", type=Path, required=True)
    promote_parser.add_argument("--candidate-reviews", type=Path, required=True)
    promote_parser.add_argument("--dataset-root", type=Path, required=True)
    promote_parser.add_argument("--sample-id", required=True)
    promote_parser.add_argument("--image-path", required=True)
    promote_parser.add_argument(
        "--split",
        choices=["calibration", "validation", "test"],
        required=True,
    )
    promote_parser.add_argument(
        "--storage-mode",
        choices=["repository", "local-only"],
        required=True,
    )
    promote_parser.add_argument("--source-title", required=True)
    promote_parser.add_argument("--source-author", required=True)
    promote_parser.add_argument("--output", type=Path, required=True)

    arguments = parser.parse_args()
    workpack = _load_workpack(arguments.workpack)
    annotation_content = arguments.annotation.read_bytes()
    if arguments.command == "review":
        review = create_annotation_review(
            workpack,
            annotation_content,
            arguments.decision,
            arguments.reviewed_by,
            arguments.reviewed_at,
            arguments.comment,
        )
        _write_json(arguments.output, review)
        return

    review = AnnotationReview.model_validate_json(
        arguments.review.read_text(encoding="utf-8")
    )
    candidate_reviews = CandidateReviewFile.model_validate_json(
        arguments.candidate_reviews.read_text(encoding="utf-8")
    )
    candidate_review = next(
        (
            item
            for item in candidate_reviews.reviews
            if item.candidate_id == workpack.candidate.candidate_id
        ),
        None,
    )
    if candidate_review is None:
        raise ValueError("candidate review is missing for promotion")
    sample = build_evaluation_sample(
        workpack,
        annotation_content,
        review,
        arguments.dataset_root,
        arguments.sample_id,
        arguments.image_path,
        arguments.split,
        arguments.storage_mode,
        arguments.source_title,
        arguments.source_author,
        candidate_review,
    )
    _write_json(arguments.output, sample)


if __name__ == "__main__":
    main()
