from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


MAX_GLB_UPLOAD_BYTES = 80 * 1024 * 1024
MOBILE_GLB_BUDGET_BYTES = 15 * 1024 * 1024
PIPELINE_VERSION = "gltf-transform-4.4.1-pascal-v4"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class GlbStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: int = Field(ge=0)
    meshes: int = Field(ge=0)
    materials: int = Field(ge=0)
    primitives: int = Field(ge=0)


class GlbFileMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=1, le=MAX_GLB_UPLOAD_BYTES)
    url: str
    statistics: GlbStatistics | None = None


class ArtifactManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    artifact_id: str = Field(alias="artifactId", pattern=r"^[0-9a-f]{64}$")
    project_id: str = Field(alias="projectId")
    scene_revision: int = Field(alias="sceneRevision", ge=1)
    pipeline_version: str = Field(alias="pipelineVersion")
    status: Literal["processing", "ready", "failed"]
    source: GlbFileMetadata
    optimized: GlbFileMetadata | None = None
    mobile_budget_exceeded: bool = Field(alias="mobileBudgetExceeded", default=False)
    error: str | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class GlbOptimizer(Protocol):
    def optimize(self, source: Path, output: Path) -> dict[str, Any]: ...


class NodeGlbOptimizer:
    def __init__(self, script: Path | None = None, node_binary: str | None = None) -> None:
        repository_root = Path(__file__).resolve().parents[3]
        self.script = script or repository_root / "workers" / "model" / "process-glb.mjs"
        self.node_binary = node_binary or os.getenv("FLOORPLAN_NODE_BIN", "node")

    def optimize(self, source: Path, output: Path) -> dict[str, Any]:
        completed = subprocess.run(
            [self.node_binary, str(self.script), str(source), str(output)],
            cwd=self.script.parent,
            capture_output=True,
            check=False,
            text=True,
            timeout=300,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(message or f"model worker exited with {completed.returncode}")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError("model worker returned invalid JSON") from error
        if not isinstance(result, dict):
            raise RuntimeError("model worker returned invalid metrics")
        return result


def validate_glb(content: bytes) -> None:
    if len(content) < 20 or content[:4] != b"glTF":
        raise ValueError("File is not a binary glTF 2.0 model")
    version = int.from_bytes(content[4:8], "little")
    declared_length = int.from_bytes(content[8:12], "little")
    if version != 2:
        raise ValueError("Only binary glTF 2.0 models are supported")
    if declared_length != len(content):
        raise ValueError("GLB header length does not match the uploaded file")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _file_metadata(value: Any, url: str) -> GlbFileMetadata:
    if not isinstance(value, dict):
        raise RuntimeError("model worker omitted file metrics")
    statistics = GlbStatistics.model_validate(
        {key: value.get(key) for key in ("nodes", "meshes", "materials", "primitives")}
    )
    return GlbFileMetadata(
        sha256=value.get("sha256"),
        bytes=value.get("bytes"),
        url=url,
        statistics=statistics,
    )


class ArtifactStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.index_directory = directory.parent / "artifact-index"
        self.index_directory.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()

    def _artifact_directory(self, artifact_id: str) -> Path:
        if not SHA256_RE.fullmatch(artifact_id):
            raise ValueError("invalid artifact id")
        return self.directory / artifact_id

    def _manifest_path(self, artifact_id: str) -> Path:
        return self._artifact_directory(artifact_id) / "manifest.json"

    def _latest_path(self, project_id: str) -> Path:
        return self.index_directory / f"{project_id}.json"

    def _write_json(self, path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def _write_manifest(self, manifest: ArtifactManifest) -> None:
        self._write_json(
            self._manifest_path(manifest.artifact_id),
            manifest.model_dump(by_alias=True, mode="json"),
        )

    def load(self, artifact_id: str) -> ArtifactManifest | None:
        path = self._manifest_path(artifact_id)
        if not path.is_file():
            return None
        return ArtifactManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def load_latest(self, project_id: str) -> ArtifactManifest | None:
        path = self._latest_path(project_id)
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        artifact_id = value.get("artifactId") if isinstance(value, dict) else None
        if not isinstance(artifact_id, str):
            return None
        return self.load(artifact_id)

    def begin(
        self,
        project_id: str,
        scene_revision: int,
        content: bytes,
    ) -> tuple[ArtifactManifest, bool]:
        source_sha = hashlib.sha256(content).hexdigest()
        identity = f"{project_id}:{scene_revision}:{PIPELINE_VERSION}:{source_sha}".encode()
        artifact_id = hashlib.sha256(identity).hexdigest()
        with self.lock:
            existing = self.load(artifact_id)
            if existing and existing.status in {"processing", "ready"}:
                return existing, False

            artifact_directory = self._artifact_directory(artifact_id)
            artifact_directory.mkdir(parents=True, exist_ok=True)
            source_path = artifact_directory / "source.glb"
            temporary = artifact_directory / ".source.glb.tmp"
            temporary.write_bytes(content)
            temporary.replace(source_path)
            now = _utcnow()
            manifest = ArtifactManifest(
                artifactId=artifact_id,
                projectId=project_id,
                sceneRevision=scene_revision,
                pipelineVersion=PIPELINE_VERSION,
                status="processing",
                source=GlbFileMetadata(
                    sha256=source_sha,
                    bytes=len(content),
                    url=f"/artifacts/{artifact_id}/source.glb",
                ),
                createdAt=existing.created_at if existing else now,
                updatedAt=now,
            )
            self._write_manifest(manifest)
            self._write_json(self._latest_path(project_id), {"artifactId": artifact_id})
            return manifest, True

    def process(self, artifact_id: str, optimizer: GlbOptimizer) -> None:
        manifest = self.load(artifact_id)
        if manifest is None:
            return
        artifact_directory = self._artifact_directory(artifact_id)
        source_path = artifact_directory / "source.glb"
        output_path = artifact_directory / "optimized.glb"
        temporary_output = artifact_directory / ".optimized.tmp.glb"
        try:
            report = optimizer.optimize(source_path, temporary_output)
            if not temporary_output.is_file():
                raise RuntimeError("model worker did not create an optimized GLB")
            optimized_content = temporary_output.read_bytes()
            validate_glb(optimized_content)
            source = _file_metadata(
                report.get("source"), f"/artifacts/{artifact_id}/source.glb"
            )
            optimized = _file_metadata(
                report.get("optimized"), f"/artifacts/{artifact_id}/optimized.glb"
            )
            if source.sha256 != manifest.source.sha256:
                raise RuntimeError("source GLB changed while it was being optimized")
            optimized_sha = hashlib.sha256(optimized_content).hexdigest()
            if optimized.sha256 != optimized_sha or optimized.bytes != len(optimized_content):
                raise RuntimeError("model worker returned inconsistent optimized metrics")
            temporary_output.replace(output_path)
            ready = manifest.model_copy(
                update={
                    "status": "ready",
                    "source": source,
                    "optimized": optimized,
                    "mobile_budget_exceeded": optimized.bytes > MOBILE_GLB_BUDGET_BYTES,
                    "error": None,
                    "updated_at": _utcnow(),
                }
            )
            with self.lock:
                self._write_manifest(ready)
        except Exception as error:
            temporary_output.unlink(missing_ok=True)
            failed = manifest.model_copy(
                update={
                    "status": "failed",
                    "error": str(error)[:1000],
                    "updated_at": _utcnow(),
                }
            )
            with self.lock:
                self._write_manifest(failed)
