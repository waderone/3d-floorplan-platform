from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .layouts import LayoutManifest
from .render_profiles import RenderProfile
from .styles import StylePack


RENDER_PIPELINE_VERSION = "blender-5x-quality-profiles-v7"
MAX_RENDER_BYTES = 50 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class StyleReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: int = Field(ge=1)


class RenderImageMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=1, le=MAX_RENDER_BYTES)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    url: str


class RenderViewMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str
    name: str
    room_type: Literal["living", "dining", "bedroom"] | None = Field(alias="roomType")
    output: RenderImageMetadata
    render_seconds: float = Field(alias="renderSeconds", ge=0)


class RenderManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    render_id: str = Field(alias="renderId", pattern=r"^[0-9a-f]{64}$")
    project_id: str = Field(alias="projectId")
    scene_revision: int = Field(alias="sceneRevision", ge=1)
    artifact_id: str = Field(alias="artifactId", pattern=r"^[0-9a-f]{64}$")
    layout_id: str = Field(alias="layoutId", pattern=r"^[0-9a-f]{64}$")
    pipeline_version: str = Field(alias="pipelineVersion")
    style: StyleReference
    asset_catalog: StyleReference = Field(alias="assetCatalog")
    profile: StyleReference
    status: Literal["processing", "ready", "failed"]
    output: RenderImageMetadata | None = None
    views: list[RenderViewMetadata] = Field(default_factory=list)
    engine: str | None = None
    device: str | None = None
    blender_version: str | None = Field(alias="blenderVersion", default=None)
    render_seconds: float | None = Field(alias="renderSeconds", default=None, ge=0)
    real_asset_placements: int | None = Field(alias="realAssetPlacements", default=None, ge=0)
    fallback_placements: int | None = Field(alias="fallbackPlacements", default=None, ge=0)
    opening_count: int | None = Field(alias="openingCount", default=None, ge=0)
    ignored_opening_count: int | None = Field(alias="ignoredOpeningCount", default=None, ge=0)
    opening_blocked_room_count: int | None = Field(
        alias="openingBlockedRoomCount", default=None, ge=0
    )
    opening_clearance_validated: bool | None = Field(
        alias="openingClearanceValidated", default=None
    )
    error: str | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class RenderBackend(Protocol):
    def render(
        self,
        source_glb: Path,
        style_path: Path,
        layout_path: Path,
        asset_catalog_path: Path,
        render_profile_catalog_path: Path,
        profile_id: str,
        output_directory: Path,
    ) -> dict[str, Any]: ...


class BlenderRenderer:
    def __init__(self, script: Path | None = None, blender_binary: str | None = None) -> None:
        repository_root = Path(__file__).resolve().parents[3]
        self.script = script or repository_root / "workers" / "render" / "render_scene.py"
        self.blender_binary = blender_binary or os.getenv("FLOORPLAN_BLENDER_BIN", "blender")

    def render(
        self,
        source_glb: Path,
        style_path: Path,
        layout_path: Path,
        asset_catalog_path: Path,
        render_profile_catalog_path: Path,
        profile_id: str,
        output_directory: Path,
    ) -> dict[str, Any]:
        report_path = output_directory / ".render.report.json"
        completed = subprocess.run(
            [
                self.blender_binary,
                "--background",
                "--factory-startup",
                "--disable-autoexec",
                "--python-exit-code",
                "1",
                "--python",
                str(self.script),
                "--",
                "--input",
                str(source_glb),
                "--style",
                str(style_path),
                "--layout",
                str(layout_path),
                "--catalog",
                str(asset_catalog_path),
                "--render-config",
                str(render_profile_catalog_path),
                "--profile",
                profile_id,
                "--output-directory",
                str(output_directory),
                "--report",
                str(report_path),
            ],
            cwd=self.script.parent,
            capture_output=True,
            check=False,
            text=True,
            timeout=900,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(message[-4000:] or f"Blender exited with {completed.returncode}")
        if not report_path.is_file():
            raise RuntimeError("Blender worker did not write a render report")
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise RuntimeError("Blender worker returned an invalid report") from error
        finally:
            report_path.unlink(missing_ok=True)
        if not isinstance(report, dict):
            raise RuntimeError("Blender worker returned an invalid report")
        return report


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_png(path: Path) -> tuple[int, int, int, str]:
    content = path.read_bytes()
    if len(content) < 24 or content[:8] != b"\x89PNG\r\n\x1a\n" or content[12:16] != b"IHDR":
        raise RuntimeError("render worker did not create a valid PNG")
    if len(content) > MAX_RENDER_BYTES:
        raise RuntimeError("render output exceeds the 50 MiB limit")
    width, height = struct.unpack(">II", content[16:24])
    if width < 1 or height < 1:
        raise RuntimeError("render output has invalid dimensions")
    return width, height, len(content), hashlib.sha256(content).hexdigest()


class RenderStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.index_directory = directory.parent / "render-index"
        self.index_directory.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()

    def _render_directory(self, render_id: str) -> Path:
        if not SHA256_RE.fullmatch(render_id):
            raise ValueError("invalid render id")
        return self.directory / render_id

    def _manifest_path(self, render_id: str) -> Path:
        return self._render_directory(render_id) / "manifest.json"

    def layout_path(self, render_id: str) -> Path:
        return self._render_directory(render_id) / "layout.json"

    def _latest_path(self, project_id: str, style_id: str, profile_id: str) -> Path:
        return self.index_directory / f"{project_id}--{style_id}--{profile_id}.json"

    def _write_json(self, path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def _write_manifest(self, manifest: RenderManifest) -> None:
        self._write_json(
            self._manifest_path(manifest.render_id),
            manifest.model_dump(by_alias=True, mode="json"),
        )

    def load(self, render_id: str) -> RenderManifest | None:
        path = self._manifest_path(render_id)
        if not path.is_file():
            return None
        return RenderManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def load_latest(self, project_id: str, style_id: str, profile_id: str) -> RenderManifest | None:
        path = self._latest_path(project_id, style_id, profile_id)
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        render_id = value.get("renderId") if isinstance(value, dict) else None
        if not isinstance(render_id, str):
            return None
        return self.load(render_id)

    def begin(
        self,
        project_id: str,
        scene_revision: int,
        artifact_id: str,
        style: StylePack,
        layout: LayoutManifest,
        profile_id: str,
        profile: RenderProfile,
    ) -> tuple[RenderManifest, bool]:
        identity = (
            f"{project_id}:{scene_revision}:{artifact_id}:{layout.layout_id}:{style.id}:{style.version}:"
            f"{profile_id}:{profile.version}:{RENDER_PIPELINE_VERSION}"
        ).encode()
        render_id = hashlib.sha256(identity).hexdigest()
        with self.lock:
            existing = self.load(render_id)
            if existing and existing.status in {"processing", "ready"}:
                return existing, False
            render_directory = self._render_directory(render_id)
            render_directory.mkdir(parents=True, exist_ok=True)
            now = _utcnow()
            manifest = RenderManifest(
                renderId=render_id,
                projectId=project_id,
                sceneRevision=scene_revision,
                artifactId=artifact_id,
                layoutId=layout.layout_id,
                pipelineVersion=RENDER_PIPELINE_VERSION,
                style=StyleReference(id=style.id, version=style.version),
                assetCatalog=StyleReference(
                    id=layout.asset_catalog.id,
                    version=layout.asset_catalog.version,
                ),
                profile=StyleReference(id=profile_id, version=profile.version),
                status="processing",
                createdAt=existing.created_at if existing else now,
                updatedAt=now,
            )
            self._write_manifest(manifest)
            self._write_json(
                self.layout_path(render_id),
                layout.model_dump(by_alias=True, mode="json"),
            )
            self._write_json(
                self._latest_path(project_id, style.id, profile_id),
                {"renderId": render_id},
            )
            return manifest, True

    def process(
        self,
        render_id: str,
        renderer: RenderBackend,
        source_glb: Path,
        style_path: Path,
        layout_path: Path,
        asset_catalog_path: Path,
        render_profile_catalog_path: Path,
        profile: RenderProfile,
    ) -> None:
        manifest = self.load(render_id)
        if manifest is None:
            return
        render_directory = self._render_directory(render_id)
        temporary_paths = {
            view.id: render_directory / f".{view.id}.tmp.png" for view in profile.views
        }
        try:
            if not source_glb.is_file():
                raise RuntimeError("optimized GLB is missing")
            report = renderer.render(
                source_glb,
                style_path,
                layout_path,
                asset_catalog_path,
                render_profile_catalog_path,
                manifest.profile.id,
                render_directory,
            )
            engine = report.get("engine")
            device = report.get("device")
            blender_version = report.get("blenderVersion")
            render_seconds = report.get("renderSeconds")
            real_asset_placements = report.get("realAssetPlacements")
            fallback_placements = report.get("fallbackPlacements")
            opening_count = report.get("openingCount")
            ignored_opening_count = report.get("ignoredOpeningCount")
            opening_blocked_room_count = report.get("openingBlockedRoomCount")
            opening_clearance_validated = report.get("openingClearanceValidated")
            reported_views = report.get("views")
            if (
                not isinstance(engine, str)
                or not engine
                or not isinstance(device, str)
                or not device
                or not isinstance(blender_version, str)
                or not blender_version
                or not isinstance(render_seconds, (int, float))
                or isinstance(render_seconds, bool)
                or render_seconds < 0
                or not isinstance(real_asset_placements, int)
                or isinstance(real_asset_placements, bool)
                or real_asset_placements < 0
                or not isinstance(fallback_placements, int)
                or isinstance(fallback_placements, bool)
                or fallback_placements < 0
                or not isinstance(opening_count, int)
                or isinstance(opening_count, bool)
                or opening_count < 0
                or not isinstance(ignored_opening_count, int)
                or isinstance(ignored_opening_count, bool)
                or ignored_opening_count < 0
                or not isinstance(opening_blocked_room_count, int)
                or isinstance(opening_blocked_room_count, bool)
                or opening_blocked_room_count < 0
                or opening_clearance_validated is not True
                or report.get("assetCatalogId") != manifest.asset_catalog.id
                or report.get("assetCatalogVersion") != manifest.asset_catalog.version
                or report.get("profileId") != manifest.profile.id
                or report.get("profileVersion") != manifest.profile.version
                or not isinstance(reported_views, list)
                or [entry.get("id") for entry in reported_views if isinstance(entry, dict)]
                != [view.id for view in profile.views]
            ):
                raise RuntimeError("render worker returned incomplete metadata")
            ready_views: list[RenderViewMetadata] = []
            for index, (view, reported) in enumerate(zip(profile.views, reported_views, strict=True)):
                if not isinstance(reported, dict):
                    raise RuntimeError("render worker returned invalid view metadata")
                view_seconds = reported.get("renderSeconds")
                if (
                    not isinstance(view_seconds, (int, float))
                    or isinstance(view_seconds, bool)
                    or view_seconds < 0
                ):
                    raise RuntimeError("render worker returned invalid view timing")
                temporary = temporary_paths[view.id]
                if not temporary.is_file():
                    raise RuntimeError(f"render worker did not create view: {view.id}")
                width, height, size, sha256 = validate_png(temporary)
                if (width, height) != (profile.width, profile.height):
                    raise RuntimeError("render output dimensions do not match the profile")
                filename = "image.png" if index == 0 else f"{view.id}.png"
                output_path = render_directory / filename
                temporary.replace(output_path)
                ready_views.append(
                    RenderViewMetadata(
                        id=view.id,
                        name=view.name,
                        roomType=view.room_type,
                        output=RenderImageMetadata(
                            sha256=sha256,
                            bytes=size,
                            width=width,
                            height=height,
                            url=f"/renders/{render_id}/{filename}",
                        ),
                        renderSeconds=float(view_seconds),
                    )
                )
            ready = manifest.model_copy(
                update={
                    "status": "ready",
                    "output": ready_views[0].output,
                    "views": ready_views,
                    "engine": engine,
                    "device": device,
                    "blender_version": blender_version,
                    "render_seconds": float(render_seconds),
                    "real_asset_placements": real_asset_placements,
                    "fallback_placements": fallback_placements,
                    "opening_count": opening_count,
                    "ignored_opening_count": ignored_opening_count,
                    "opening_blocked_room_count": opening_blocked_room_count,
                    "opening_clearance_validated": opening_clearance_validated,
                    "error": None,
                    "updated_at": _utcnow(),
                }
            )
            with self.lock:
                self._write_manifest(ready)
        except Exception as error:
            for path in temporary_paths.values():
                path.unlink(missing_ok=True)
            failed = manifest.model_copy(
                update={
                    "status": "failed",
                    "error": str(error)[:4000],
                    "updated_at": _utcnow(),
                }
            )
            with self.lock:
                self._write_manifest(failed)
