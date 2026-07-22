from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Any, Literal

from .artifacts import ArtifactStore, NodeGlbOptimizer
from .assets import AssetCatalog, RoomType
from .baselines import BaselineInputAsset, build_structural_glb
from .layouts import generate_layout
from .recognition_evaluation import (
    EvaluationDataset,
    EvaluationOpening,
    EvaluationSample,
    EvaluationWall,
)
from .styles import StyleCatalog


REVIEWED_SHOWROOM_PIPELINE_VERSION = "reviewed-ground-truth-showroom-v1"
SUPPORTED_ROOM_TYPES: dict[str, RoomType] = {
    "living": "living",
    "dining": "dining",
    "bedroom": "bedroom",
}
ROOM_LABELS = {
    "living": "客厅",
    "dining": "餐厅",
    "bedroom": "卧室",
    "kitchen": "厨房",
    "bathroom": "卫生间",
    "unknown": "未分类空间",
}


def _safe_key(value: str) -> str:
    key = "".join(character if character.isalnum() else "_" for character in value.lower())
    return key.strip("_") or "item"


def _nearest_wall(
    opening: EvaluationOpening,
    walls: list[EvaluationWall],
) -> tuple[EvaluationWall, tuple[float, float], float]:
    best: tuple[
        float,
        str,
        EvaluationWall,
        tuple[float, float],
        float,
    ] | None = None
    for wall in walls:
        dx = wall.end[0] - wall.start[0]
        dz = wall.end[1] - wall.start[1]
        length = math.hypot(dx, dz)
        if length < 1e-9:
            continue
        tangent = (dx / length, dz / length)
        relative = (
            opening.center[0] - wall.start[0],
            opening.center[1] - wall.start[1],
        )
        along = relative[0] * tangent[0] + relative[1] * tangent[1]
        perpendicular = abs(relative[0] * tangent[1] - relative[1] * tangent[0])
        overhang = max(0.0, -along, along - length)
        score = perpendicular + max(0.0, overhang - opening.width * 0.75) * 2
        candidate = (score, wall.id, wall, tangent, along)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    if best is None:
        raise ValueError(f"opening has no wall host: {opening.id}")
    return best[2], best[3], best[4]


def build_reviewed_showroom_scene(
    sample: EvaluationSample,
    input_asset: BaselineInputAsset,
) -> dict[str, Any]:
    if sample.annotation_status != "complete" or sample.annotation_provenance is None:
        raise ValueError("reviewed showroom requires complete, reviewed ground truth")
    if not sample.annotations.rooms:
        raise ValueError("reviewed showroom requires at least one room")

    provenance = sample.annotation_provenance
    identity = hashlib.sha256(
        f"{sample.sample_id}:{provenance.submission_sha256}".encode()
    ).hexdigest()
    prefix = identity[:12]
    site_id = f"site_truth_{prefix}"
    building_id = f"building_truth_{prefix}"
    level_id = f"level_truth_{prefix}"
    wall_ids = {
        wall.id: f"wall_truth_{prefix}_{_safe_key(wall.id)}" for wall in sample.annotations.walls
    }
    zone_ids = {
        room.id: f"zone_truth_{prefix}_{_safe_key(room.id)}" for room in sample.annotations.rooms
    }
    opening_ids = {
        opening.id: f"opening_truth_{prefix}_{_safe_key(opening.id)}"
        for opening in sample.annotations.openings
    }
    truth_metadata = {
        "sampleId": sample.sample_id,
        "workpackId": provenance.workpack_id,
        "submissionSha256": provenance.submission_sha256,
        "annotatedBy": provenance.annotated_by,
        "annotatedAt": provenance.annotated_at,
        "reviewedBy": provenance.reviewed_by,
        "reviewedAt": provenance.reviewed_at,
        "pipelineVersion": REVIEWED_SHOWROOM_PIPELINE_VERSION,
    }

    nodes: dict[str, dict[str, Any]] = {
        site_id: {
            "object": "node",
            "id": site_id,
            "type": "site",
            "name": "真实户型样板间",
            "parentId": None,
            "visible": True,
            "children": [building_id],
            "metadata": {"reviewedGroundTruth": truth_metadata},
        },
        building_id: {
            "object": "node",
            "id": building_id,
            "type": "building",
            "name": "住宅",
            "parentId": site_id,
            "visible": True,
            "children": [level_id],
            "position": [0, 0, 0],
            "rotation": [0, 0, 0],
            "metadata": {},
        },
        level_id: {
            "object": "node",
            "id": level_id,
            "type": "level",
            "name": "首层",
            "parentId": building_id,
            "visible": True,
            "children": [*wall_ids.values(), *zone_ids.values()],
            "level": 0,
            "metadata": {
                "inputAssetId": input_asset.asset_id,
                "reviewedGroundTruth": truth_metadata,
            },
        },
    }

    for wall in sample.annotations.walls:
        wall_id = wall_ids[wall.id]
        nodes[wall_id] = {
            "object": "node",
            "id": wall_id,
            "type": "wall",
            "name": f"真实墙体 {wall.id.rsplit('-', maxsplit=1)[-1]}",
            "parentId": level_id,
            "visible": True,
            "children": [],
            "start": list(wall.start),
            "end": list(wall.end),
            "thickness": round(min(0.45, max(0.08, wall.thickness)), 3),
            "height": 2.8,
            "frontSide": "unknown",
            "backSide": "unknown",
            "metadata": {
                "reviewedGroundTruth": {**truth_metadata, "annotationId": wall.id}
            },
        }

    room_counts: dict[str, int] = {}
    for room in sample.annotations.rooms:
        room_counts[room.room_type] = room_counts.get(room.room_type, 0) + 1
        room_type = SUPPORTED_ROOM_TYPES.get(room.room_type, "other")
        label = ROOM_LABELS.get(room.room_type, "未分类空间")
        if sum(candidate.room_type == room.room_type for candidate in sample.annotations.rooms) > 1:
            label = f"{label} {room_counts[room.room_type]}"
        zone_id = zone_ids[room.id]
        nodes[zone_id] = {
            "object": "node",
            "id": zone_id,
            "type": "zone",
            "name": label,
            "parentId": level_id,
            "visible": True,
            "children": [],
            "polygon": [list(point) for point in room.polygon],
            "roomType": room_type,
            "color": "#22c55e",
            "metadata": {
                "reviewedGroundTruth": {**truth_metadata, "annotationId": room.id},
                "roomTypeSource": "reviewed-ground-truth",
                "originalRoomType": room.room_type,
            },
        }

    for opening in sample.annotations.openings:
        wall, tangent, along = _nearest_wall(opening, sample.annotations.walls)
        wall_id = wall_ids[wall.id]
        wall_length = math.dist(wall.start, wall.end)
        opening_id = opening_ids[opening.id]
        height = 2.1 if opening.kind == "door" else 1.5
        sill_height = 0.0 if opening.kind == "door" else 0.9
        nodes[opening_id] = {
            "object": "node",
            "id": opening_id,
            "type": opening.kind,
            "name": f"真实{'门洞' if opening.kind == 'door' else '窗洞'} {opening.id}",
            "parentId": wall_id,
            "wallId": wall_id,
            "visible": True,
            "children": [],
            "position": [min(wall_length, max(0.0, along)), sill_height + height / 2, 0],
            "planCenter": list(opening.center),
            "planTangent": list(tangent),
            "width": opening.width,
            "height": height,
            "openingKind": opening.kind,
            **({"doorType": "hinged"} if opening.kind == "door" else {"windowType": "fixed"}),
            "metadata": {
                "reviewedGroundTruth": {
                    **truth_metadata,
                    "annotationId": opening.id,
                    "hostAnnotationId": wall.id,
                },
                "worldPlanCenterSource": "reviewed-ground-truth",
            },
        }
        nodes[wall_id]["children"].append(opening_id)

    return {
        "nodes": nodes,
        "rootNodeIds": [site_id],
        "collections": {},
        "materials": {},
    }


def _load_sample(manifest_path: Path, sample_id: str) -> tuple[EvaluationSample, Path]:
    dataset = EvaluationDataset.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    sample = next((candidate for candidate in dataset.samples if candidate.sample_id == sample_id), None)
    if sample is None:
        raise ValueError(f"sample not found: {sample_id}")
    image_path = (manifest_path.parent / sample.image_path).resolve()
    if not image_path.is_file():
        raise ValueError(f"sample image not found: {sample.image_path}")
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    if digest != sample.image_sha256:
        raise ValueError(f"sample image SHA-256 mismatch: {sample_id}")
    return sample, image_path


def publish_reviewed_showroom(
    manifest_path: Path,
    sample_id: str,
    data_dir: Path,
    project_id: str,
    node_binary: str | None = None,
) -> dict[str, Any]:
    from .main import AssetMetadata, SceneSaveRequest, SceneStore

    sample, image_path = _load_sample(manifest_path.resolve(), sample_id)
    root = data_dir.resolve()
    extension = "png" if image_path.suffix.lower() == ".png" else "jpg"
    media_type: Literal["image/png", "image/jpeg"] = (
        "image/png" if extension == "png" else "image/jpeg"
    )
    asset_directory = root / "assets"
    asset_directory.mkdir(parents=True, exist_ok=True)
    asset_path = asset_directory / f"{sample.image_sha256}.{extension}"
    if not asset_path.is_file():
        shutil.copyfile(image_path, asset_path)
    asset_content = asset_path.read_bytes()
    if hashlib.sha256(asset_content).hexdigest() != sample.image_sha256:
        raise ValueError(f"stored asset SHA-256 mismatch: {sample_id}")
    asset = BaselineInputAsset(
        assetId=sample.image_sha256,
        url=f"/assets/{asset_path.name}",
        mediaType=media_type,
        size=len(asset_content),
    )
    scene_graph = build_reviewed_showroom_scene(sample, asset)
    scene_store = SceneStore(root / "scenes")
    existing = scene_store.load(project_id)
    if existing is None:
        saved, _ = scene_store.save(
            project_id,
            SceneSaveRequest(
                schemaVersion="1.0",
                revision=0,
                expectedRevision=None,
                units="m",
                scene=scene_graph,
                assets=[AssetMetadata.model_validate(asset.model_dump(by_alias=True))],
            ),
        )
    else:
        expected_scene = scene_graph
        expected_assets = [asset.model_dump(by_alias=True, mode="json")]
        if (
            existing.scene.model_dump(by_alias=True, mode="json") != expected_scene
            or [entry.model_dump(by_alias=True, mode="json") for entry in existing.assets]
            != expected_assets
        ):
            raise ValueError(f"project already exists with different content: {project_id}")
        saved = existing

    source_glb = build_structural_glb(saved.scene.nodes)
    artifact_store = ArtifactStore(root / "artifacts")
    artifact, should_process = artifact_store.begin(project_id, saved.revision, source_glb)
    if should_process:
        artifact_store.process(
            artifact.artifact_id,
            NodeGlbOptimizer(node_binary=node_binary),
        )
    artifact = artifact_store.load(artifact.artifact_id)
    if artifact is None or artifact.status != "ready" or artifact.optimized is None:
        raise RuntimeError(artifact.error if artifact is not None else "artifact disappeared")

    style_catalog = StyleCatalog()
    asset_catalog = AssetCatalog()
    layouts = []
    for summary in style_catalog.list():
        style = style_catalog.get(summary.id)
        if style is None:
            raise RuntimeError(f"style disappeared: {summary.id}")
        layout = generate_layout(project_id, saved.revision, saved.scene.nodes, style, asset_catalog)
        layouts.append(
            {
                "styleId": style.id,
                "layoutId": layout.layout_id,
                "status": layout.status,
                "furnishedRoomCount": len(layout.furnished_room_ids),
                "unfurnishedRoomCount": len(layout.unfurnished_room_ids),
                "openingCount": len(layout.openings),
                "ignoredOpeningCount": len(layout.ignored_opening_ids),
                "placementCount": len(layout.placements),
            }
        )
    if not layouts or any(layout["furnishedRoomCount"] == 0 for layout in layouts):
        raise RuntimeError("reviewed showroom has no furnished room in at least one style")

    report = {
        "schemaVersion": "1.0",
        "pipelineVersion": REVIEWED_SHOWROOM_PIPELINE_VERSION,
        "projectId": project_id,
        "sampleId": sample.sample_id,
        "sceneRevision": saved.revision,
        "artifactId": artifact.artifact_id,
        "artifactBytes": artifact.optimized.bytes,
        "groundTruth": {
            "walls": len(sample.annotations.walls),
            "rooms": len(sample.annotations.rooms),
            "openings": len(sample.annotations.openings),
            "submissionSha256": sample.annotation_provenance.submission_sha256,
            "reviewedBy": sample.annotation_provenance.reviewed_by,
        },
        "layouts": layouts,
        "viewerUrl": f"/?project={project_id}&style=warm-minimal",
    }
    report_directory = root / "reviewed-showrooms"
    report_directory.mkdir(parents=True, exist_ok=True)
    report_path = report_directory / f"{project_id}.json"
    temporary = report_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(report_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish a reviewed recognition sample as a real-time three-style showroom."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--project-id")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--node-binary")
    args = parser.parse_args()
    project_id = args.project_id or f"truth-{args.sample_id}"
    report = publish_reviewed_showroom(
        args.manifest,
        args.sample_id,
        args.data_dir,
        project_id,
        args.node_binary,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
