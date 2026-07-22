from __future__ import annotations

import hashlib
import json
import math
import struct
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .recognitions import RecognitionManifest


BASELINE_PIPELINE_VERSION = "floorplan-to-showroom-baseline-v1"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BaselineLayoutReference(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    style_id: str = Field(alias="styleId")
    layout_id: str = Field(alias="layoutId", pattern=r"^[0-9a-f]{64}$")
    status: Literal["ready", "partial", "fallback"]


class BaselineInputAsset(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    asset_id: str = Field(alias="assetId", pattern=r"^[0-9a-f]{64}$")
    url: str = Field(pattern=r"^/assets/[0-9a-f]{64}\.(?:jpg|png)$")
    media_type: Literal["image/jpeg", "image/png"] = Field(alias="mediaType")
    size: int = Field(ge=1)


class BaselineManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["1.0"] = Field(alias="schemaVersion", default="1.0")
    job_id: str = Field(alias="jobId", pattern=r"^[0-9a-f]{64}$")
    pipeline_version: Literal["floorplan-to-showroom-baseline-v1"] = Field(
        alias="pipelineVersion", default=BASELINE_PIPELINE_VERSION
    )
    project_id: str = Field(alias="projectId")
    status: Literal["processing", "ready", "failed"]
    stage: Literal["recognition", "scene", "artifact", "layout", "ready", "failed"]
    input_asset: BaselineInputAsset = Field(alias="inputAsset")
    plan_width_meters: float = Field(alias="planWidthMeters", gt=0, le=500)
    recognition_id: str | None = Field(
        alias="recognitionId", default=None, pattern=r"^[0-9a-f]{64}$"
    )
    recognition_pipeline_version: str | None = Field(
        alias="recognitionPipelineVersion", default=None
    )
    recognition_confidence: float | None = Field(
        alias="recognitionConfidence", default=None, ge=0, le=1
    )
    auto_room_types: dict[str, Literal["living", "dining", "bedroom", "other"]] = Field(
        alias="autoRoomTypes", default_factory=dict
    )
    scene_revision: int | None = Field(alias="sceneRevision", default=None, ge=1)
    artifact_id: str | None = Field(
        alias="artifactId", default=None, pattern=r"^[0-9a-f]{64}$"
    )
    layouts: list[BaselineLayoutReference] = Field(default_factory=list)
    viewer_url: str | None = Field(alias="viewerUrl", default=None)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @model_validator(mode="after")
    def validate_status_payload(self) -> "BaselineManifest":
        if self.status == "ready":
            if (
                self.stage != "ready"
                or self.scene_revision is None
                or self.artifact_id is None
                or not self.layouts
                or self.viewer_url is None
                or self.error is not None
            ):
                raise ValueError("ready baseline manifest is incomplete")
        elif self.status == "failed":
            if self.stage != "failed" or not self.error or self.viewer_url is not None:
                raise ValueError("failed baseline manifest is invalid")
        return self


class BaselineStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.index_directory = directory.parent / "baseline-index"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.index_directory.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()

    def _manifest_path(self, job_id: str) -> Path:
        return self.directory / job_id / "manifest.json"

    def _index_path(self, project_id: str) -> Path:
        return self.index_directory / f"{project_id}.json"

    def _write(self, manifest: BaselineManifest) -> None:
        path = self._manifest_path(manifest.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(manifest.model_dump(by_alias=True, mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def load(self, job_id: str) -> BaselineManifest | None:
        path = self._manifest_path(job_id)
        if not path.is_file():
            return None
        return BaselineManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def load_latest(self, project_id: str) -> BaselineManifest | None:
        path = self._index_path(project_id)
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        job_id = value.get("jobId") if isinstance(value, dict) else None
        return self.load(job_id) if isinstance(job_id, str) else None

    def begin(
        self,
        project_id: str,
        input_asset: BaselineInputAsset,
        plan_width_meters: float,
    ) -> BaselineManifest:
        identity = (
            f"{project_id}:{input_asset.asset_id}:{plan_width_meters:.6f}:"
            f"{BASELINE_PIPELINE_VERSION}"
        ).encode()
        job_id = hashlib.sha256(identity).hexdigest()
        now = _utcnow()
        manifest = BaselineManifest(
            jobId=job_id,
            projectId=project_id,
            status="processing",
            stage="recognition",
            inputAsset=input_asset,
            planWidthMeters=plan_width_meters,
            warnings=[
                "baseline_auto_accept_without_human_review",
                "axis_aligned_walls_only",
                "doors_windows_not_detected",
                "room_types_use_area_heuristic",
            ],
            createdAt=now,
            updatedAt=now,
        )
        with self.lock:
            self._write(manifest)
            index = self._index_path(project_id)
            temporary = index.with_suffix(".json.tmp")
            temporary.write_text(json.dumps({"jobId": job_id}), encoding="utf-8")
            temporary.replace(index)
        return manifest

    def update(self, job_id: str, **changes: Any) -> BaselineManifest:
        with self.lock:
            current = self.load(job_id)
            if current is None:
                raise RuntimeError("baseline manifest disappeared")
            updated = current.model_copy(update={**changes, "updated_at": _utcnow()})
            updated = BaselineManifest.model_validate(updated.model_dump(by_alias=True))
            self._write(updated)
            return updated

    def fail(self, job_id: str, error: Exception) -> None:
        self.update(
            job_id,
            status="failed",
            stage="failed",
            viewer_url=None,
            error=(str(error) or error.__class__.__name__)[:4000],
        )


def _safe_suggestion_key(value: str) -> str:
    key = "".join(character if character.isalnum() else "_" for character in value.lower())
    return key.strip("_") or "suggestion"


def build_baseline_scene(
    recognition: RecognitionManifest,
    input_asset: BaselineInputAsset,
) -> tuple[dict[str, Any], dict[str, Literal["living", "dining", "bedroom", "other"]]]:
    if recognition.status != "review_required":
        raise RuntimeError("recognition did not produce reviewable geometry")
    if not recognition.rooms:
        raise RuntimeError("recognition produced no room polygons for styled layout")

    prefix = recognition.recognition_id[:12]
    site_id = f"site_baseline_{prefix}"
    building_id = f"building_baseline_{prefix}"
    level_id = f"level_baseline_{prefix}"
    wall_ids = [
        f"wall_recognition_{prefix}_{_safe_suggestion_key(suggestion.id)}"
        for suggestion in recognition.walls
    ]
    sorted_rooms = sorted(
        recognition.rooms,
        key=lambda room: (-room.approximate_area_sq_m, room.id),
    )
    heuristic_types: tuple[Literal["living", "bedroom", "dining"], ...] = (
        "living",
        "bedroom",
        "dining",
    )
    room_types: dict[str, Literal["living", "dining", "bedroom", "other"]] = {}
    zone_ids: list[str] = []
    for index, room in enumerate(sorted_rooms):
        room_type: Literal["living", "dining", "bedroom", "other"] = (
            heuristic_types[index] if index < len(heuristic_types) else "other"
        )
        room_types[room.id] = room_type
        zone_ids.append(f"zone_recognition_{prefix}_{_safe_suggestion_key(room.id)}")

    nodes: dict[str, dict[str, Any]] = {
        site_id: {
            "object": "node",
            "id": site_id,
            "type": "site",
            "name": "自动生成项目",
            "parentId": None,
            "visible": True,
            "children": [building_id],
            "metadata": {"baselinePipelineVersion": BASELINE_PIPELINE_VERSION},
        },
        building_id: {
            "object": "node",
            "id": building_id,
            "type": "building",
            "name": "自动生成建筑",
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
            "children": [*wall_ids, *zone_ids],
            "level": 0,
            "metadata": {
                "recognitionId": recognition.recognition_id,
                "inputAssetId": input_asset.asset_id,
                "autoGenerated": True,
            },
        },
    }
    for suggestion, wall_id in zip(recognition.walls, wall_ids, strict=True):
        nodes[wall_id] = {
            "object": "node",
            "id": wall_id,
            "type": "wall",
            "name": f"自动墙体 {suggestion.id.rsplit('-', maxsplit=1)[-1]}",
            "parentId": level_id,
            "visible": True,
            "children": [],
            "start": list(suggestion.start),
            "end": list(suggestion.end),
            "thickness": round(min(0.45, max(0.08, suggestion.thickness)), 3),
            "height": 2.8,
            "frontSide": "unknown",
            "backSide": "unknown",
            "metadata": {
                "recognition": {
                    "recognitionId": recognition.recognition_id,
                    "suggestionId": suggestion.id,
                    "confidence": suggestion.confidence,
                    "assetId": recognition.asset_id,
                    "sceneRevision": recognition.scene_revision,
                    "pipelineVersion": recognition.pipeline_version,
                    "decision": "baseline-auto-accepted",
                }
            },
        }
    for room, zone_id in zip(sorted_rooms, zone_ids, strict=True):
        room_type = room_types[room.id]
        nodes[zone_id] = {
            "object": "node",
            "id": zone_id,
            "type": "zone",
            "name": {"living": "客厅", "bedroom": "卧室", "dining": "餐厅"}.get(
                room_type, room.name
            ),
            "parentId": level_id,
            "visible": True,
            "children": [],
            "polygon": [list(point) for point in room.polygon],
            "roomType": room_type,
            "color": "#22c55e",
            "metadata": {
                "recognition": {
                    "recognitionId": recognition.recognition_id,
                    "suggestionId": room.id,
                    "confidence": room.confidence,
                    "assetId": recognition.asset_id,
                    "sceneRevision": recognition.scene_revision,
                    "pipelineVersion": recognition.pipeline_version,
                    "decision": "baseline-auto-accepted",
                },
                "roomTypeSource": "area-order-heuristic",
                "approximateAreaSqM": room.approximate_area_sq_m,
            },
        }
    return {
        "nodes": nodes,
        "rootNodeIds": [site_id],
        "collections": {},
        "materials": {},
    }, room_types


def _cube_geometry() -> tuple[list[float], list[float], list[int]]:
    faces = [
        ((0, 0, 1), [(-0.5, 0, 0.5), (0.5, 0, 0.5), (0.5, 1, 0.5), (-0.5, 1, 0.5)]),
        ((0, 0, -1), [(0.5, 0, -0.5), (-0.5, 0, -0.5), (-0.5, 1, -0.5), (0.5, 1, -0.5)]),
        ((1, 0, 0), [(0.5, 0, 0.5), (0.5, 0, -0.5), (0.5, 1, -0.5), (0.5, 1, 0.5)]),
        ((-1, 0, 0), [(-0.5, 0, -0.5), (-0.5, 0, 0.5), (-0.5, 1, 0.5), (-0.5, 1, -0.5)]),
        ((0, 1, 0), [(-0.5, 1, 0.5), (0.5, 1, 0.5), (0.5, 1, -0.5), (-0.5, 1, -0.5)]),
        ((0, -1, 0), [(-0.5, 0, -0.5), (0.5, 0, -0.5), (0.5, 0, 0.5), (-0.5, 0, 0.5)]),
    ]
    positions: list[float] = []
    normals: list[float] = []
    indices: list[int] = []
    for normal, vertices in faces:
        offset = len(positions) // 3
        for vertex in vertices:
            positions.extend(vertex)
            normals.extend(normal)
        indices.extend((offset, offset + 1, offset + 2, offset, offset + 2, offset + 3))
    return positions, normals, indices


def build_structural_glb(nodes: dict[str, dict[str, Any]]) -> bytes:
    wall_nodes: list[dict[str, Any]] = []
    for node_id, node in sorted(nodes.items()):
        if node.get("type") != "wall" or node.get("curveOffset") not in {None, 0, 0.0}:
            continue
        start = node.get("start")
        end = node.get("end")
        if not (
            isinstance(start, list)
            and isinstance(end, list)
            and len(start) == len(end) == 2
            and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in [*start, *end])
        ):
            continue
        dx = float(end[0]) - float(start[0])
        dz = float(end[1]) - float(start[1])
        length = math.hypot(dx, dz)
        if not math.isfinite(length) or length < 0.05:
            continue
        thickness_value = node.get("thickness", 0.15)
        height_value = node.get("height", 2.8)
        thickness = float(thickness_value) if isinstance(thickness_value, (int, float)) else 0.15
        height = float(height_value) if isinstance(height_value, (int, float)) else 2.8
        if not all(math.isfinite(value) and value > 0 for value in (thickness, height)):
            continue
        tangent_x, tangent_z = dx / length, dz / length
        wall_nodes.append(
            {
                "name": node_id,
                "mesh": 0,
                "matrix": [
                    dx,
                    0,
                    dz,
                    0,
                    0,
                    height,
                    0,
                    0,
                    -tangent_z * thickness,
                    0,
                    tangent_x * thickness,
                    0,
                    (float(start[0]) + float(end[0])) / 2,
                    0,
                    (float(start[1]) + float(end[1])) / 2,
                    1,
                ],
                "extras": {"pascalId": node_id, "kind": "wall", "pascalType": "wall"},
            }
        )
    if not wall_nodes:
        raise RuntimeError("scene contains no supported straight walls")

    positions, normals, indices = _cube_geometry()
    position_bytes = struct.pack(f"<{len(positions)}f", *positions)
    normal_bytes = struct.pack(f"<{len(normals)}f", *normals)
    index_bytes = struct.pack(f"<{len(indices)}H", *indices)
    binary = position_bytes + normal_bytes + index_bytes
    document = {
        "asset": {"version": "2.0", "generator": BASELINE_PIPELINE_VERSION},
        "scene": 0,
        "scenes": [{"name": "baseline-floorplan", "nodes": list(range(len(wall_nodes)))}],
        "nodes": wall_nodes,
        "meshes": [
            {
                "name": "baseline-wall-box",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1},
                        "indices": 2,
                        "material": 0,
                    }
                ],
            }
        ],
        "materials": [
            {
                "name": "baseline-wall",
                "doubleSided": True,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.86, 0.84, 0.8, 1],
                    "metallicFactor": 0,
                    "roughnessFactor": 0.82,
                },
            }
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(position_bytes), "target": 34962},
            {
                "buffer": 0,
                "byteOffset": len(position_bytes),
                "byteLength": len(normal_bytes),
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteOffset": len(position_bytes) + len(normal_bytes),
                "byteLength": len(index_bytes),
                "target": 34963,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(positions) // 3,
                "type": "VEC3",
                "min": [-0.5, 0, -0.5],
                "max": [0.5, 1, 0.5],
            },
            {"bufferView": 1, "componentType": 5126, "count": len(normals) // 3, "type": "VEC3"},
            {
                "bufferView": 2,
                "componentType": 5123,
                "count": len(indices),
                "type": "SCALAR",
                "min": [0],
                "max": [max(indices)],
            },
        ],
    }
    json_chunk = json.dumps(document, separators=(",", ":")).encode()
    json_chunk += b" " * (-len(json_chunk) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total_length = 12 + 8 + len(json_chunk) + 8 + len(binary)
    return (
        struct.pack("<4sII", b"glTF", 2, total_length)
        + struct.pack("<I4s", len(json_chunk), b"JSON")
        + json_chunk
        + struct.pack("<I4s", len(binary), b"BIN\0")
        + binary
    )
