from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .recognition_annotation_review import AnnotationReview, validate_annotation_review
from .recognition_annotation_submission import (
    AnnotationSubmission,
    validate_submission_identity,
)
from .recognition_annotation_workpack import (
    AnnotationWorkpack,
    CandidateReviewFile,
    CandidateReviewRecord,
    _load_image,
    build_annotation_workpack,
)
from .recognition_candidates import CommonsCandidate, CommonsCandidateQueue
from .recognition_evaluation import EvaluationSample
from .recognitions import RecognitionBackend


ProductionStage = Literal[
    "invalid",
    "curation-required",
    "curation-rejected",
    "rights-rejected",
    "workpack-required",
    "annotation-required",
    "annotation-in-progress",
    "geometry-review-required",
    "changes-requested",
    "rights-review-required",
    "promotion-required",
    "promoted",
]


class ProductionArtifacts(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    workpack: bool
    annotation: bool
    review: bool
    sample: bool
    workpack_sha256: str | None = Field(
        alias="workpackSha256", default=None, pattern=r"^[0-9a-f]{64}$"
    )
    annotation_sha256: str | None = Field(
        alias="annotationSha256", default=None, pattern=r"^[0-9a-f]{64}$"
    )
    review_sha256: str | None = Field(
        alias="reviewSha256", default=None, pattern=r"^[0-9a-f]{64}$"
    )
    sample_sha256: str | None = Field(
        alias="sampleSha256", default=None, pattern=r"^[0-9a-f]{64}$"
    )


class ProductionCandidate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    candidate_id: str = Field(alias="candidateId", pattern=r"^commons-[1-9][0-9]*$")
    stage: ProductionStage
    next_action: str = Field(alias="nextAction", min_length=1, max_length=100)
    blockers: list[str]
    curation_status: Literal["unreviewed", "selected", "rejected"] = Field(
        alias="curationStatus"
    )
    rights_status: Literal["unreviewed", "pending", "approved", "rejected"] = Field(
        alias="rightsStatus"
    )
    image_sha256: str | None = Field(
        alias="imageSha256",
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    artifacts: ProductionArtifacts


class ProductionReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    report_id: str = Field(alias="reportId", pattern=r"^[0-9a-f]{64}$")
    total_candidates: int = Field(alias="totalCandidates", ge=0)
    stage_counts: dict[str, int] = Field(alias="stageCounts")
    candidates: list[ProductionCandidate]


class PreparedWorkpack(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    candidate_id: str = Field(alias="candidateId", pattern=r"^commons-[1-9][0-9]*$")
    workpack_id: str = Field(alias="workpackId", pattern=r"^[0-9a-f]{64}$")
    result: Literal["created", "existing"]


def _artifact_paths(production_root: Path, candidate_id: str) -> dict[str, Path]:
    candidate_root = production_root / candidate_id
    return {
        "workpack": candidate_root / "workpack.json",
        "annotation": candidate_root / "annotation.json",
        "review": candidate_root / "review.json",
        "sample": candidate_root / "sample.json",
    }


def _artifacts(paths: dict[str, Path]) -> ProductionArtifacts:
    present = {name: path.is_file() for name, path in paths.items()}
    digests = {
        f"{name}Sha256": hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in paths.items()
        if present[name]
    }
    return ProductionArtifacts(**present, **digests)


def _candidate_state(
    candidate: CommonsCandidate,
    review: CandidateReviewRecord | None,
    image_directory: Path,
    production_root: Path,
) -> ProductionCandidate:
    paths = _artifact_paths(production_root, candidate.candidate_id)
    artifacts = _artifacts(paths)
    curation_status = (
        "unreviewed" if review is None else review.curation.selection_status
    )
    rights_status = "unreviewed" if review is None else review.rights.status

    def state(
        stage: ProductionStage,
        next_action: str,
        *blockers: str,
        image_sha256: str | None = None,
    ) -> ProductionCandidate:
        return ProductionCandidate(
            candidateId=candidate.candidate_id,
            stage=stage,
            nextAction=next_action,
            blockers=list(blockers),
            curationStatus=curation_status,
            rightsStatus=rights_status,
            imageSha256=image_sha256,
            artifacts=artifacts,
        )

    try:
        _, image = _load_image(candidate, image_directory)
    except Exception:
        return state("invalid", "repair-candidate-image", "candidate_image_invalid")

    image_sha256 = image.sha256
    if review is None:
        if artifacts.workpack or artifacts.annotation or artifacts.review or artifacts.sample:
            return state(
                "invalid",
                "remove-or-reconcile-orphan-artifacts",
                "artifacts_without_curation",
                image_sha256=image_sha256,
            )
        return state(
            "curation-required",
            "complete-human-curation",
            "curation_missing",
            image_sha256=image_sha256,
        )
    if review.curation.selection_status == "rejected":
        if artifacts.sample:
            return state(
                "invalid",
                "retract-promoted-sample",
                "sample_after_curation_rejection",
                image_sha256=image_sha256,
            )
        return state(
            "curation-rejected",
            "none",
            "curation_rejected",
            image_sha256=image_sha256,
        )
    if review.rights.status == "rejected":
        if artifacts.sample:
            return state(
                "invalid",
                "retract-promoted-sample",
                "sample_after_rights_rejection",
                image_sha256=image_sha256,
            )
        return state(
            "rights-rejected",
            "none",
            "rights_rejected",
            image_sha256=image_sha256,
        )
    if not artifacts.workpack:
        if artifacts.annotation or artifacts.review or artifacts.sample:
            return state(
                "invalid",
                "remove-or-reconcile-orphan-artifacts",
                "artifacts_without_workpack",
                image_sha256=image_sha256,
            )
        return state(
            "workpack-required",
            "prepare-workpack",
            "workpack_missing",
            image_sha256=image_sha256,
        )

    try:
        workpack = AnnotationWorkpack.model_validate_json(
            paths["workpack"].read_text(encoding="utf-8")
        )
        if workpack.candidate.candidate_id != candidate.candidate_id:
            raise ValueError("workpack candidate mismatch")
        if workpack.image.sha256 != image_sha256:
            raise ValueError("workpack image mismatch")
        if workpack.review.curation != review.curation:
            raise ValueError("workpack curation mismatch")
    except Exception:
        return state(
            "invalid",
            "rebuild-workpack-after-review",
            "workpack_invalid",
            image_sha256=image_sha256,
        )

    if not artifacts.annotation:
        if artifacts.review or artifacts.sample:
            return state(
                "invalid",
                "remove-or-reconcile-orphan-artifacts",
                "review_or_sample_without_annotation",
                image_sha256=image_sha256,
            )
        return state(
            "annotation-required",
            "complete-first-annotation",
            "annotation_missing",
            image_sha256=image_sha256,
        )

    try:
        annotation_content = paths["annotation"].read_bytes()
        submission = AnnotationSubmission.model_validate_json(annotation_content)
        validate_submission_identity(workpack, submission)
    except Exception:
        return state(
            "invalid",
            "repair-annotation",
            "annotation_invalid",
            image_sha256=image_sha256,
        )

    if submission.annotation_status == "draft":
        if artifacts.review or artifacts.sample:
            return state(
                "invalid",
                "remove-stale-review-and-sample",
                "downstream_artifact_for_draft",
                image_sha256=image_sha256,
            )
        return state(
            "annotation-in-progress",
            "finish-first-annotation",
            "annotation_draft",
            image_sha256=image_sha256,
        )
    if submission.correction_session is None:
        return state(
            "invalid",
            "redo-timed-first-annotation",
            "correction_session_missing",
            image_sha256=image_sha256,
        )
    if not artifacts.review:
        if artifacts.sample:
            return state(
                "invalid",
                "remove-or-reconcile-orphan-sample",
                "sample_without_geometry_review",
                image_sha256=image_sha256,
            )
        return state(
            "geometry-review-required",
            "complete-second-person-review",
            "geometry_review_missing",
            image_sha256=image_sha256,
        )

    try:
        geometry_review = AnnotationReview.model_validate_json(
            paths["review"].read_text(encoding="utf-8")
        )
        validate_annotation_review(workpack, annotation_content, geometry_review)
    except Exception:
        return state(
            "invalid",
            "redo-second-person-review",
            "geometry_review_invalid",
            image_sha256=image_sha256,
        )

    if geometry_review.decision == "changes-requested":
        if artifacts.sample:
            return state(
                "invalid",
                "remove-invalid-promoted-sample",
                "sample_after_changes_requested",
                image_sha256=image_sha256,
            )
        return state(
            "changes-requested",
            "revise-first-annotation",
            "geometry_changes_requested",
            image_sha256=image_sha256,
        )
    if review.rights.status != "approved" or not review.rights.commercial_use_confirmed:
        if artifacts.sample:
            return state(
                "invalid",
                "remove-unapproved-promoted-sample",
                "sample_without_approved_rights",
                image_sha256=image_sha256,
            )
        return state(
            "rights-review-required",
            "complete-human-rights-review",
            "rights_review_pending",
            image_sha256=image_sha256,
        )
    if not artifacts.sample:
        return state(
            "promotion-required",
            "promote-approved-sample",
            "sample_not_promoted",
            image_sha256=image_sha256,
        )

    try:
        sample = EvaluationSample.model_validate_json(
            paths["sample"].read_text(encoding="utf-8")
        )
        provenance = sample.annotation_provenance
        if sample.annotation_status != "complete" or provenance is None:
            raise ValueError("sample provenance missing")
        if sample.image_sha256 != image_sha256:
            raise ValueError("sample image mismatch")
        if sample.source.source_url != candidate.description_url:
            raise ValueError("sample source mismatch")
        if sample.source.license_id != candidate.normalized_license_id:
            raise ValueError("sample license mismatch")
        if sample.plan_width_meters != review.curation.plan_width_meters:
            raise ValueError("sample plan width mismatch")
        if (
            sample.source.reviewed_by != review.rights.reviewed_by
            or sample.source.reviewed_at != review.rights.reviewed_at
        ):
            raise ValueError("sample rights review mismatch")
        if provenance.workpack_id != workpack.workpack_id:
            raise ValueError("sample workpack mismatch")
        if provenance.submission_sha256 != hashlib.sha256(annotation_content).hexdigest():
            raise ValueError("sample annotation mismatch")
        if provenance.reviewed_by != geometry_review.reviewed_by:
            raise ValueError("sample reviewer mismatch")
        if provenance.reviewed_at != geometry_review.reviewed_at:
            raise ValueError("sample review date mismatch")
        if (
            provenance.annotated_by != submission.annotated_by
            or provenance.annotated_at != submission.annotated_at
        ):
            raise ValueError("sample annotator mismatch")
        if not sample.correction_sessions or not any(
            session.pipeline_version == submission.correction_session.pipeline_version
            and session.duration_seconds
            == submission.correction_session.duration_seconds
            and session.reviewer == submission.annotated_by
            and session.completed_at == submission.annotated_at
            for session in sample.correction_sessions
        ):
            raise ValueError("sample correction session missing")
    except Exception:
        return state(
            "invalid",
            "rebuild-promoted-sample",
            "promoted_sample_invalid",
            image_sha256=image_sha256,
        )
    return state("promoted", "none", image_sha256=image_sha256)


def build_production_report(
    queue: CommonsCandidateQueue,
    reviews: CandidateReviewFile,
    image_directory: Path,
    production_root: Path,
) -> ProductionReport:
    review_by_candidate = {review.candidate_id: review for review in reviews.reviews}
    candidates = [
        _candidate_state(
            candidate,
            review_by_candidate.get(candidate.candidate_id),
            image_directory,
            production_root,
        )
        for candidate in sorted(queue.candidates, key=lambda item: item.candidate_id)
    ]
    counts = dict(sorted(Counter(item.stage for item in candidates).items()))
    identity = {
        "schemaVersion": "1.0",
        "stageCounts": counts,
        "candidates": [
            item.model_dump(by_alias=True, mode="json") for item in candidates
        ],
    }
    report_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ProductionReport(
        schemaVersion="1.0",
        reportId=report_id,
        totalCandidates=len(candidates),
        stageCounts=counts,
        candidates=candidates,
    )


def _write_json(path: Path, value: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(value.model_dump(by_alias=True, mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def prepare_selected_workpacks(
    queue: CommonsCandidateQueue,
    reviews: CandidateReviewFile,
    image_directory: Path,
    production_root: Path,
    backend: RecognitionBackend | None = None,
) -> list[PreparedWorkpack]:
    queue_ids = {candidate.candidate_id for candidate in queue.candidates}
    prepared: list[PreparedWorkpack] = []
    for review in sorted(reviews.reviews, key=lambda item: item.candidate_id):
        if review.candidate_id not in queue_ids:
            raise ValueError(f"review candidate is not in the queue: {review.candidate_id}")
        if review.curation.selection_status != "selected" or review.rights.status == "rejected":
            continue
        paths = _artifact_paths(production_root, review.candidate_id)
        workpack_path = paths["workpack"]
        if workpack_path.is_file():
            workpack = AnnotationWorkpack.model_validate_json(
                workpack_path.read_text(encoding="utf-8")
            )
            candidate = next(
                item for item in queue.candidates if item.candidate_id == review.candidate_id
            )
            _, image = _load_image(candidate, image_directory)
            if (
                workpack.candidate.candidate_id != review.candidate_id
                or workpack.image.sha256 != image.sha256
                or workpack.review.curation != review.curation
            ):
                raise ValueError(f"existing workpack is stale: {review.candidate_id}")
            result: Literal["created", "existing"] = "existing"
        else:
            workpack = build_annotation_workpack(
                queue,
                reviews,
                review.candidate_id,
                image_directory,
                workpack_path.with_name("overlay.png"),
                backend,
            )
            _write_json(workpack_path, workpack)
            result = "created"
        prepared.append(
            PreparedWorkpack(
                candidateId=review.candidate_id,
                workpackId=workpack.workpack_id,
                result=result,
            )
        )
    return prepared


def _load_inputs(
    queue_path: Path,
    reviews_path: Path,
) -> tuple[CommonsCandidateQueue, CandidateReviewFile]:
    queue = CommonsCandidateQueue.model_validate_json(
        queue_path.read_text(encoding="utf-8")
    )
    reviews = CandidateReviewFile.model_validate_json(
        reviews_path.read_text(encoding="utf-8")
    )
    return queue, reviews


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit and prepare the floor-plan evaluation sample production queue"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "prepare"):
        command_parser = commands.add_parser(command)
        command_parser.add_argument("--queue", type=Path, required=True)
        command_parser.add_argument("--reviews", type=Path, required=True)
        command_parser.add_argument("--image-dir", type=Path, required=True)
        command_parser.add_argument("--production-root", type=Path, required=True)
        if command == "status":
            command_parser.add_argument("--output", type=Path, required=True)

    arguments = parser.parse_args()
    queue, reviews = _load_inputs(arguments.queue, arguments.reviews)
    if arguments.command == "prepare":
        prepared = prepare_selected_workpacks(
            queue,
            reviews,
            arguments.image_dir,
            arguments.production_root,
        )
        print(
            json.dumps(
                [item.model_dump(by_alias=True, mode="json") for item in prepared],
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    report = build_production_report(
        queue,
        reviews,
        arguments.image_dir,
        arguments.production_root,
    )
    _write_json(arguments.output, report)
    print(json.dumps(report.stage_counts, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
