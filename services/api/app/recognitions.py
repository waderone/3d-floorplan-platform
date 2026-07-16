from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Literal, Protocol

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .renders import RenderImageMetadata, validate_png


RECOGNITION_PIPELINE_VERSION = "opencv-axis-aligned-baseline-v1"
MAX_RECOGNITION_PIXELS = 40_000_000


class RecognitionCoordinateSystem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    units: Literal["m"] = "m"
    origin: Literal["plan-bottom-left"] = "plan-bottom-left"
    axes: Literal["x-right-z-up"] = "x-right-z-up"


class RecognitionWall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    start: tuple[float, float]
    end: tuple[float, float]
    thickness: float = Field(gt=0)
    confidence: float = Field(ge=0, le=1)


class RecognitionRoom(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str
    name: str
    room_type: Literal["unknown"] = Field(alias="roomType", default="unknown")
    polygon: list[tuple[float, float]] = Field(min_length=3)
    approximate_area_sq_m: float = Field(alias="approximateAreaSqM", gt=0)
    confidence: float = Field(ge=0, le=1)


class RecognitionOpening(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["door", "window"]
    center: tuple[float, float]
    width: float = Field(gt=0)
    confidence: float = Field(ge=0, le=1)


class RecognitionMetrics(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    image_width_pixels: int = Field(alias="imageWidthPixels", gt=0)
    image_height_pixels: int = Field(alias="imageHeightPixels", gt=0)
    plan_bounds_pixels: tuple[int, int, int, int] = Field(alias="planBoundsPixels")
    pixels_per_meter: float = Field(alias="pixelsPerMeter", gt=0)
    otsu_threshold: float = Field(alias="otsuThreshold", ge=0, le=255)
    structural_pixel_ratio: float = Field(alias="structuralPixelRatio", ge=0, le=1)


class RecognitionManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    recognition_id: str = Field(alias="recognitionId", pattern=r"^[0-9a-f]{64}$")
    project_id: str = Field(alias="projectId")
    scene_revision: int = Field(alias="sceneRevision", ge=1)
    asset_id: str = Field(alias="assetId", pattern=r"^[0-9a-f]{64}$")
    pipeline_version: str = Field(alias="pipelineVersion")
    status: Literal["processing", "review_required", "failed"]
    coordinate_system: RecognitionCoordinateSystem = Field(alias="coordinateSystem")
    plan_width_meters: float = Field(alias="planWidthMeters", gt=0, le=500)
    confidence: float | None = Field(default=None, ge=0, le=1)
    walls: list[RecognitionWall] = Field(default_factory=list)
    rooms: list[RecognitionRoom] = Field(default_factory=list)
    openings: list[RecognitionOpening] = Field(default_factory=list)
    review_reasons: list[str] = Field(alias="reviewReasons", default_factory=list)
    metrics: RecognitionMetrics | None = None
    overlay: RenderImageMetadata | None = None
    error: str | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @model_validator(mode="after")
    def validate_status_payload(self) -> "RecognitionManifest":
        if self.status == "review_required":
            if (
                self.confidence is None
                or not self.walls
                or self.metrics is None
                or self.overlay is None
            ):
                raise ValueError("review_required recognition must include reviewable geometry")
            if self.error is not None:
                raise ValueError("review_required recognition cannot include an error")
        elif self.status == "failed":
            if not self.error:
                raise ValueError("failed recognition must include an error")
            if self.walls or self.rooms or self.openings or self.overlay is not None:
                raise ValueError("failed recognition cannot publish suggestions")
        return self


class RecognitionBackend(Protocol):
    def recognize(
        self,
        image_path: Path,
        plan_width_meters: float,
        overlay_path: Path,
    ) -> dict[str, Any]: ...


def _rounded_point(x: float, y: float, scale: float, min_x: int, max_y: int) -> tuple[float, float]:
    return (round((x - min_x) * scale, 3), round((max_y - y) * scale, 3))


class OpenCvRecognitionBackend:
    def recognize(
        self,
        image_path: Path,
        plan_width_meters: float,
        overlay_path: Path,
    ) -> dict[str, Any]:
        encoded = np.frombuffer(image_path.read_bytes(), dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError("uploaded image cannot be decoded")
        if image.shape[0] * image.shape[1] > MAX_RECOGNITION_PIXELS:
            raise RuntimeError("uploaded image exceeds the 40 megapixel recognition limit")
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        threshold, dark = cv2.threshold(
            blurred,
            0,
            255,
            cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
        )
        height, width = gray.shape
        run_length = max(12, round(min(width, height) * 0.06))
        horizontal = cv2.morphologyEx(
            dark,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (run_length, 3)),
        )
        vertical = cv2.morphologyEx(
            dark,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, run_length)),
        )
        structural = cv2.bitwise_or(horizontal, vertical)
        ys, xs = np.nonzero(structural)
        if len(xs) == 0:
            raise RuntimeError("no axis-aligned wall candidates were detected")
        min_x, max_x = int(xs.min()), int(xs.max())
        min_y, max_y = int(ys.min()), int(ys.max())
        plan_pixel_width = max_x - min_x
        if plan_pixel_width < run_length * 2:
            raise RuntimeError("detected plan bounds are too small")
        scale = plan_width_meters / plan_pixel_width

        walls: list[RecognitionWall] = []
        for orientation, mask in (("h", horizontal), ("v", vertical)):
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            candidates: list[tuple[int, int, int, int]] = []
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                major, minor = (w, h) if orientation == "h" else (h, w)
                if major < run_length or minor < 2:
                    continue
                candidates.append((x, y, w, h))
            candidates.sort(key=lambda box: (box[1], box[0]))
            for x, y, w, h in candidates:
                if orientation == "h":
                    start = _rounded_point(x, y + h / 2, scale, min_x, max_y)
                    end = _rounded_point(x + w - 1, y + h / 2, scale, min_x, max_y)
                    minor = h
                else:
                    start = _rounded_point(x + w / 2, y + h - 1, scale, min_x, max_y)
                    end = _rounded_point(x + w / 2, y, scale, min_x, max_y)
                    minor = w
                walls.append(
                    RecognitionWall(
                        id=f"wall-suggestion-{len(walls) + 1}",
                        start=start,
                        end=end,
                        thickness=round(max(0.05, minor * scale), 3),
                        confidence=0.82,
                    )
                )
        if len(walls) < 4:
            raise RuntimeError("too few wall candidates were detected")

        cropped = structural[min_y : max_y + 1, min_x : max_x + 1]
        closed = cv2.morphologyEx(
            cropped,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
        )
        free_space = cv2.bitwise_not(closed)
        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(free_space)
        plan_area = cropped.shape[0] * cropped.shape[1]
        room_components: list[tuple[int, int]] = []
        for label in range(1, component_count):
            x, y, w, h, area = (int(value) for value in stats[label])
            touches_edge = (
                x == 0
                or y == 0
                or x + w == cropped.shape[1]
                or y + h == cropped.shape[0]
            )
            if touches_edge or area < plan_area * 0.025:
                continue
            room_components.append((label, area))
        room_components.sort(key=lambda item: (-item[1], item[0]))

        rooms: list[RecognitionRoom] = []
        for label, area in room_components:
            room_mask = np.where(labels == label, 255, 0).astype(np.uint8)
            contours, _ = cv2.findContours(room_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                continue
            contour = max(contours, key=cv2.contourArea)
            epsilon = max(1.0, cv2.arcLength(contour, True) * 0.012)
            polygon = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
            points = [
                _rounded_point(float(x + min_x), float(y + min_y), scale, min_x, max_y)
                for x, y in polygon
            ]
            if len(points) < 3:
                continue
            rooms.append(
                RecognitionRoom(
                    id=f"room-suggestion-{len(rooms) + 1}",
                    name=f"待确认房间 {len(rooms) + 1}",
                    roomType="unknown",
                    polygon=points,
                    approximateAreaSqM=round(area * scale * scale, 2),
                    confidence=0.74,
                )
            )

        confidence = 0.78 if rooms else 0.58
        review_reasons = [
            "axis_aligned_baseline_only",
            "doors_windows_not_detected",
            "room_types_unclassified",
        ]
        if not rooms:
            review_reasons.append("room_boundaries_not_closed")

        overlay = image.copy()
        for wall in walls:
            start_x = round(wall.start[0] / scale + min_x)
            start_y = round(max_y - wall.start[1] / scale)
            end_x = round(wall.end[0] / scale + min_x)
            end_y = round(max_y - wall.end[1] / scale)
            cv2.line(overlay, (start_x, start_y), (end_x, end_y), (30, 60, 230), 2)
        for room in rooms:
            pixels = np.array(
                [
                    [round(x / scale + min_x), round(max_y - z / scale)]
                    for x, z in room.polygon
                ],
                dtype=np.int32,
            )
            cv2.polylines(overlay, [pixels], True, (40, 180, 70), 2)
        if not cv2.imwrite(str(overlay_path), overlay):
            raise RuntimeError("recognition overlay could not be written")

        return {
            "confidence": confidence,
            "walls": [wall.model_dump(mode="json") for wall in walls],
            "rooms": [room.model_dump(by_alias=True, mode="json") for room in rooms],
            "openings": [],
            "reviewReasons": review_reasons,
            "metrics": RecognitionMetrics(
                imageWidthPixels=width,
                imageHeightPixels=height,
                planBoundsPixels=(min_x, min_y, max_x, max_y),
                pixelsPerMeter=round(1 / scale, 4),
                otsuThreshold=float(threshold),
                structuralPixelRatio=round(
                    float(np.count_nonzero(structural)) / structural.size,
                    6,
                ),
            ).model_dump(by_alias=True, mode="json"),
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RecognitionStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.index_directory = directory.parent / "recognition-index"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.index_directory.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()

    def _directory(self, recognition_id: str) -> Path:
        return self.directory / recognition_id

    def _manifest_path(self, recognition_id: str) -> Path:
        return self._directory(recognition_id) / "manifest.json"

    def _index_path(self, project_id: str) -> Path:
        return self.index_directory / f"{project_id}.json"

    def _write_manifest(self, manifest: RecognitionManifest) -> None:
        path = self._manifest_path(manifest.recognition_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                manifest.model_dump(by_alias=True, mode="json"),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)

    def load(self, recognition_id: str) -> RecognitionManifest | None:
        path = self._manifest_path(recognition_id)
        if not path.is_file():
            return None
        return RecognitionManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def load_latest(self, project_id: str) -> RecognitionManifest | None:
        path = self._index_path(project_id)
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        recognition_id = value.get("recognitionId")
        if not isinstance(recognition_id, str):
            return None
        return self.load(recognition_id)

    def begin(
        self,
        project_id: str,
        scene_revision: int,
        asset_id: str,
        plan_width_meters: float,
    ) -> tuple[RecognitionManifest, bool]:
        identity = (
            f"{project_id}:{scene_revision}:{asset_id}:{plan_width_meters:.6f}:"
            f"{RECOGNITION_PIPELINE_VERSION}"
        ).encode()
        recognition_id = hashlib.sha256(identity).hexdigest()
        with self.lock:
            existing = self.load(recognition_id)
            if existing and existing.status in {"processing", "review_required"}:
                return existing, False
            now = _utcnow()
            manifest = RecognitionManifest(
                recognitionId=recognition_id,
                projectId=project_id,
                sceneRevision=scene_revision,
                assetId=asset_id,
                pipelineVersion=RECOGNITION_PIPELINE_VERSION,
                status="processing",
                coordinateSystem=RecognitionCoordinateSystem(),
                planWidthMeters=plan_width_meters,
                createdAt=existing.created_at if existing else now,
                updatedAt=now,
            )
            self._write_manifest(manifest)
            index = self._index_path(project_id)
            temporary = index.with_suffix(".json.tmp")
            temporary.write_text(json.dumps({"recognitionId": recognition_id}), encoding="utf-8")
            temporary.replace(index)
            return manifest, True

    def process(
        self,
        recognition_id: str,
        backend: RecognitionBackend,
        image_path: Path,
    ) -> None:
        manifest = self.load(recognition_id)
        if manifest is None:
            return
        directory = self._directory(recognition_id)
        temporary_overlay = directory / ".overlay.tmp.png"
        output_overlay = directory / "overlay.png"
        try:
            result = backend.recognize(
                image_path,
                manifest.plan_width_meters,
                temporary_overlay,
            )
            width, height, size, sha256 = validate_png(temporary_overlay)
            temporary_overlay.replace(output_overlay)
            ready = manifest.model_copy(
                update={
                    "status": "review_required",
                    "confidence": result["confidence"],
                    "walls": [RecognitionWall.model_validate(item) for item in result["walls"]],
                    "rooms": [RecognitionRoom.model_validate(item) for item in result["rooms"]],
                    "openings": [
                        RecognitionOpening.model_validate(item) for item in result["openings"]
                    ],
                    "review_reasons": result["reviewReasons"],
                    "metrics": RecognitionMetrics.model_validate(result["metrics"]),
                    "overlay": RenderImageMetadata(
                        sha256=sha256,
                        bytes=size,
                        width=width,
                        height=height,
                        url=f"/recognitions/{recognition_id}/overlay.png",
                    ),
                    "error": None,
                    "updated_at": _utcnow(),
                }
            )
            self._write_manifest(ready)
        except Exception as error:
            temporary_overlay.unlink(missing_ok=True)
            failed = manifest.model_copy(
                update={
                    "status": "failed",
                    "error": str(error)[:4000] or error.__class__.__name__,
                    "updated_at": _utcnow(),
                }
            )
            self._write_manifest(failed)
