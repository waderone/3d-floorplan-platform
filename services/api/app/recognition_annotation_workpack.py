from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .recognition_candidates import CommonsCandidate, CommonsCandidateQueue
from .recognition_evaluation import EvaluationAnnotations
from .recognitions import (
    RECOGNITION_PIPELINE_VERSION,
    OpenCvRecognitionBackend,
    RecognitionBackend,
    RecognitionMetrics,
    RecognitionOpening,
    RecognitionRoom,
    RecognitionWall,
)
from .renders import validate_png


class CandidateCurationReview(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    content_type: Literal["floor-plan", "elevation", "section", "mixed-sheet", "other"] = (
        Field(alias="contentType")
    )
    target_domain: Literal[
        "modern-residential",
        "historical-residential",
        "non-residential",
        "unknown",
    ] = Field(alias="targetDomain")
    selection_status: Literal["selected", "rejected"] = Field(alias="selectionStatus")
    selection_reasons: list[str] = Field(
        alias="selectionReasons",
        min_length=1,
        max_length=20,
    )
    plan_width_meters: float | None = Field(
        alias="planWidthMeters",
        default=None,
        gt=0,
        le=500,
    )
    scale_evidence: str | None = Field(
        alias="scaleEvidence",
        default=None,
        max_length=500,
    )
    reviewed_by: str = Field(alias="reviewedBy", min_length=1, max_length=100)
    reviewed_at: str = Field(alias="reviewedAt", pattern=r"^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def validate_selected_candidate(self) -> "CandidateCurationReview":
        if self.selection_status == "selected":
            if self.content_type != "floor-plan":
                raise ValueError("selected candidates must be floor plans")
            if self.plan_width_meters is None or not self.scale_evidence:
                raise ValueError("selected candidates require scale evidence")
        return self


class CandidateRightsReview(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    status: Literal["pending", "approved", "rejected"]
    commercial_use_confirmed: bool = Field(alias="commercialUseConfirmed", default=False)
    redistribution_allowed_confirmed: bool = Field(
        alias="redistributionAllowedConfirmed",
        default=False,
    )
    basis: str | None = Field(default=None, min_length=1, max_length=1000)
    reviewed_by: str | None = Field(
        alias="reviewedBy",
        default=None,
        min_length=1,
        max_length=100,
    )
    reviewed_at: str | None = Field(
        alias="reviewedAt",
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )

    @model_validator(mode="after")
    def validate_explicit_rights_decision(self) -> "CandidateRightsReview":
        if self.status == "pending":
            if (
                self.commercial_use_confirmed
                or self.redistribution_allowed_confirmed
                or self.basis is not None
                or self.reviewed_by is not None
                or self.reviewed_at is not None
            ):
                raise ValueError("pending rights review cannot contain an approval")
            return self
        if not self.basis or not self.reviewed_by or not self.reviewed_at:
            raise ValueError("decided rights review requires basis, reviewer, and date")
        if self.status == "approved" and not self.commercial_use_confirmed:
            raise ValueError("approved rights review must confirm commercial use")
        if self.status == "rejected" and (
            self.commercial_use_confirmed or self.redistribution_allowed_confirmed
        ):
            raise ValueError("rejected rights review cannot confirm usage rights")
        return self


class CandidateReviewRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    candidate_id: str = Field(alias="candidateId", pattern=r"^commons-[1-9][0-9]*$")
    curation: CandidateCurationReview
    rights: CandidateRightsReview


class CandidateReviewFile(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    reviews: list[CandidateReviewRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_candidates(self) -> "CandidateReviewFile":
        candidate_ids = [review.candidate_id for review in self.reviews]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate review ids must be unique")
        return self


class WorkpackImage(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    file: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0)
    width_pixels: int = Field(alias="widthPixels", gt=0)
    height_pixels: int = Field(alias="heightPixels", gt=0)


class WorkpackOverlay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class BaselineSuggestions(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    pipeline_version: str = Field(alias="pipelineVersion")
    is_ground_truth: Literal[False] = Field(alias="isGroundTruth", default=False)
    status: Literal["review_required", "failed"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    walls: list[RecognitionWall] = Field(default_factory=list)
    rooms: list[RecognitionRoom] = Field(default_factory=list)
    openings: list[RecognitionOpening] = Field(default_factory=list)
    review_reasons: list[str] = Field(alias="reviewReasons", default_factory=list)
    metrics: RecognitionMetrics | None = None
    overlay: WorkpackOverlay | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> "BaselineSuggestions":
        if self.status == "review_required":
            if (
                not self.walls
                or self.confidence is None
                or self.metrics is None
                or not self.overlay
            ):
                raise ValueError("reviewable suggestions require walls, metrics, and overlay")
            if self.error:
                raise ValueError("reviewable suggestions cannot contain an error")
        elif not self.error or self.walls or self.rooms or self.openings or self.overlay:
            raise ValueError("failed suggestions must only contain an error")
        return self


class AnnotationWorkpack(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    workpack_id: str = Field(alias="workpackId", pattern=r"^[0-9a-f]{64}$")
    candidate: CommonsCandidate
    review: CandidateReviewRecord
    image: WorkpackImage
    annotation_status: Literal["pending"] = Field(alias="annotationStatus")
    ground_truth: EvaluationAnnotations = Field(alias="groundTruth")
    suggestions: BaselineSuggestions
    promotion_eligible: Literal[False] = Field(alias="promotionEligible")
    blocking_reasons: list[str] = Field(alias="blockingReasons", min_length=1)


def _load_image(candidate: CommonsCandidate, image_directory: Path) -> tuple[Path, WorkpackImage]:
    filename = candidate.download_file
    if (
        candidate.download_status != "downloaded"
        or not filename
        or Path(filename).name != filename
        or not candidate.download_sha256
    ):
        raise ValueError("candidate must have a safe downloaded image")
    image_path = image_directory / filename
    if not image_path.is_file():
        raise FileNotFoundError(f"candidate image is missing: {filename}")
    content = image_path.read_bytes()
    sha256 = hashlib.sha256(content).hexdigest()
    if sha256 != candidate.download_sha256:
        raise ValueError(f"candidate image SHA-256 mismatch: {candidate.candidate_id}")
    if candidate.download_bytes is not None and len(content) != candidate.download_bytes:
        raise ValueError(f"candidate image byte count mismatch: {candidate.candidate_id}")
    decoded = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None:
        raise ValueError(f"candidate image cannot be decoded: {candidate.candidate_id}")
    return image_path, WorkpackImage(
        file=filename,
        sha256=sha256,
        bytes=len(content),
        widthPixels=decoded.shape[1],
        heightPixels=decoded.shape[0],
    )


def _run_baseline(
    image_path: Path,
    plan_width_meters: float,
    overlay_path: Path,
    backend: RecognitionBackend,
) -> BaselineSuggestions:
    temporary_overlay = overlay_path.with_name(f".{overlay_path.name}.tmp.png")
    temporary_overlay.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = backend.recognize(image_path, plan_width_meters, temporary_overlay)
        width, height, size, sha256 = validate_png(temporary_overlay)
        temporary_overlay.replace(overlay_path)
        return BaselineSuggestions(
            pipelineVersion=RECOGNITION_PIPELINE_VERSION,
            status="review_required",
            confidence=result["confidence"],
            walls=result["walls"],
            rooms=result["rooms"],
            openings=result["openings"],
            reviewReasons=result["reviewReasons"],
            metrics=result["metrics"],
            overlay=WorkpackOverlay(
                file=overlay_path.name,
                sha256=sha256,
                bytes=size,
                width=width,
                height=height,
            ),
        )
    except Exception as error:
        temporary_overlay.unlink(missing_ok=True)
        overlay_path.unlink(missing_ok=True)
        return BaselineSuggestions(
            pipelineVersion=RECOGNITION_PIPELINE_VERSION,
            status="failed",
            error=(str(error) or error.__class__.__name__)[:1000],
        )


def build_annotation_workpack(
    queue: CommonsCandidateQueue,
    reviews: CandidateReviewFile,
    candidate_id: str,
    image_directory: Path,
    overlay_path: Path,
    backend: RecognitionBackend | None = None,
) -> AnnotationWorkpack:
    candidate = next(
        (item for item in queue.candidates if item.candidate_id == candidate_id),
        None,
    )
    review = next(
        (item for item in reviews.reviews if item.candidate_id == candidate_id),
        None,
    )
    if candidate is None or review is None:
        raise ValueError(f"candidate and review are both required: {candidate_id}")
    if review.curation.selection_status != "selected":
        raise ValueError("rejected candidate cannot produce an annotation workpack")
    if review.rights.status == "rejected":
        raise ValueError("rights-rejected candidate cannot produce an annotation workpack")
    image_path, image = _load_image(candidate, image_directory)
    plan_width_meters = review.curation.plan_width_meters
    if plan_width_meters is None:
        raise ValueError("selected candidate must have a plan width")
    suggestions = _run_baseline(
        image_path,
        plan_width_meters,
        overlay_path,
        backend or OpenCvRecognitionBackend(),
    )
    blocking_reasons = ["ground_truth_pending"]
    if review.rights.status != "approved":
        blocking_reasons.insert(0, "rights_review_pending")
    identity = {
        "candidateId": candidate_id,
        "imageSha256": image.sha256,
        "review": review.model_dump(by_alias=True, mode="json"),
        "pipelineVersion": suggestions.pipeline_version,
    }
    workpack_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return AnnotationWorkpack(
        schemaVersion="1.0",
        workpackId=workpack_id,
        candidate=candidate,
        review=review,
        image=image,
        annotationStatus="pending",
        groundTruth=EvaluationAnnotations(),
        suggestions=suggestions,
        promotionEligible=False,
        blockingReasons=blocking_reasons,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a review-gated floor-plan annotation workpack"
    )
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overlay", type=Path)
    arguments = parser.parse_args()

    queue = CommonsCandidateQueue.model_validate_json(
        arguments.queue.read_text(encoding="utf-8")
    )
    reviews = CandidateReviewFile.model_validate_json(
        arguments.reviews.read_text(encoding="utf-8")
    )
    overlay_path = arguments.overlay or arguments.output.with_name("overlay.png")
    workpack = build_annotation_workpack(
        queue,
        reviews,
        arguments.candidate_id,
        arguments.image_dir,
        overlay_path,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_suffix(f"{arguments.output.suffix}.tmp")
    temporary.write_text(
        json.dumps(workpack.model_dump(by_alias=True, mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(arguments.output)


if __name__ == "__main__":
    main()
