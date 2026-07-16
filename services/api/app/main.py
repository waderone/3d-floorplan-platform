from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from threading import Lock
from typing import Annotated, Any, Literal

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Path as ApiPath,
    Query,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .artifacts import (
    MAX_GLB_UPLOAD_BYTES,
    ArtifactManifest,
    ArtifactStore,
    GlbOptimizer,
    NodeGlbOptimizer,
    validate_glb,
)
from .layouts import LayoutManifest, generate_layout
from .renders import (
    BlenderRenderer,
    RenderBackend,
    RenderManifest,
    RenderStore,
)
from .styles import STYLE_ID_RE, StyleCatalog, StylePack, StyleSummary


PROJECT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
PROJECT_ID_RE = re.compile(PROJECT_ID_PATTERN)
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ProjectId = Annotated[str, ApiPath(pattern=PROJECT_ID_PATTERN)]
StyleId = Annotated[str, ApiPath(pattern=STYLE_ID_RE.pattern)]


class PascalSceneGraph(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    nodes: dict[str, dict[str, Any]]
    root_node_ids: list[str] = Field(alias="rootNodeIds")
    collections: dict[str, Any] = Field(default_factory=dict)
    materials: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_node_references(self) -> "PascalSceneGraph":
        for node_id, node in self.nodes.items():
            if node.get("id") != node_id:
                raise ValueError(f"scene node key must match node.id: {node_id}")
            if not isinstance(node.get("type"), str) or not node["type"]:
                raise ValueError(f"scene node must have a type: {node_id}")

        missing_roots = [node_id for node_id in self.root_node_ids if node_id not in self.nodes]
        if missing_roots:
            raise ValueError(f"rootNodeIds reference missing nodes: {missing_roots}")
        return self


class AssetMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    asset_id: str = Field(alias="assetId", pattern=r"^[0-9a-f]{64}$")
    url: str = Field(pattern=r"^/(?:assets|platform-assets)/[0-9a-f]{64}\.(?:jpg|png)$")
    media_type: Literal["image/jpeg", "image/png"] = Field(alias="mediaType")
    size: int = Field(ge=1, le=MAX_UPLOAD_BYTES)

    @model_validator(mode="after")
    def validate_asset_identity(self) -> "AssetMetadata":
        filename = self.url.rsplit("/", maxsplit=1)[-1]
        digest, extension = filename.rsplit(".", maxsplit=1)
        expected_extension = "jpg" if self.media_type == "image/jpeg" else "png"
        if digest != self.asset_id or extension != expected_extension:
            raise ValueError("asset URL must match assetId and mediaType")
        return self


class SceneEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    revision: int = Field(ge=0)
    units: Literal["m"]
    scene: PascalSceneGraph
    assets: list[AssetMetadata]


class SceneSaveRequest(SceneEnvelope):
    expected_revision: int | None = Field(alias="expectedRevision", ge=0)


class RenderCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    scene_revision: int = Field(alias="sceneRevision", ge=1)
    style_id: str = Field(alias="styleId", pattern=STYLE_ID_RE.pattern)


class SceneStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()

    def _path(self, project_id: str) -> Path:
        if not PROJECT_ID_RE.fullmatch(project_id):
            raise ValueError("invalid project id")
        return self.directory / f"{project_id}.json"

    def load(self, project_id: str) -> SceneEnvelope | None:
        path = self._path(project_id)
        if not path.exists():
            return None
        return SceneEnvelope.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, project_id: str, request: SceneSaveRequest) -> tuple[SceneEnvelope, bool]:
        path = self._path(project_id)
        with self.lock:
            current = self.load(project_id)
            current_revision = current.revision if current else None
            is_create = current is None

            if is_create:
                matches = request.expected_revision is None and request.revision == 0
            else:
                matches = (
                    request.expected_revision == current_revision
                    and request.revision == current_revision
                )

            if not matches:
                raise RevisionConflict(current_revision)

            saved = SceneEnvelope(
                schemaVersion=request.schema_version,
                revision=(current_revision or 0) + 1,
                units=request.units,
                scene=request.scene,
                assets=request.assets,
            )
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(saved.model_dump(by_alias=True), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(path)
            return saved, is_create


class RevisionConflict(Exception):
    def __init__(self, current_revision: int | None) -> None:
        self.current_revision = current_revision


def _detect_image(content: bytes, declared_type: str | None) -> tuple[str, str]:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = ("image/png", "png")
    elif content.startswith(b"\xff\xd8\xff"):
        detected = ("image/jpeg", "jpg")
    else:
        raise HTTPException(status_code=415, detail="Only JPG and PNG images are supported")

    if declared_type != detected[0]:
        raise HTTPException(status_code=415, detail="Content-Type does not match image data")
    return detected


def create_app(
    data_dir: Path | None = None,
    optimizer: GlbOptimizer | None = None,
    renderer: RenderBackend | None = None,
    style_directory: Path | None = None,
) -> FastAPI:
    root = (data_dir or Path(os.getenv("FLOORPLAN_DATA_DIR", "data"))).expanduser().resolve()
    assets_dir = root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    asset_lock = Lock()
    store = SceneStore(root / "scenes")
    artifact_store = ArtifactStore(root / "artifacts")
    artifact_optimizer = optimizer or NodeGlbOptimizer()
    style_catalog = StyleCatalog(style_directory)
    render_store = RenderStore(root / "renders")
    render_backend = renderer or BlenderRenderer()

    app = FastAPI(title="3D Floorplan API", version="0.4.0")
    app.state.data_dir = root
    app.state.style_catalog = style_catalog
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["*"],
    )
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    app.mount(
        "/artifacts",
        StaticFiles(directory=artifact_store.directory),
        name="artifacts",
    )
    app.mount("/renders", StaticFiles(directory=render_store.directory), name="renders")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/assets", response_model=AssetMetadata, status_code=201)
    async def upload_asset(file: Annotated[UploadFile, File()]) -> AssetMetadata:
        try:
            content = await file.read(MAX_UPLOAD_BYTES + 1)
        finally:
            await file.close()

        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Image exceeds the 20 MiB upload limit")

        media_type, extension = _detect_image(content, file.content_type)
        digest = hashlib.sha256(content).hexdigest()
        target = assets_dir / f"{digest}.{extension}"
        with asset_lock:
            if not target.exists():
                temporary = assets_dir / f".{digest}.{extension}.tmp"
                temporary.write_bytes(content)
                temporary.replace(target)

        return AssetMetadata(
            assetId=digest,
            url=f"/assets/{target.name}",
            mediaType=media_type,
            size=len(content),
        )

    @app.get("/api/projects/{project_id}/scene", response_model=SceneEnvelope)
    def get_scene(project_id: ProjectId) -> SceneEnvelope:
        scene = store.load(project_id)
        if scene is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "scene_not_found", "projectId": project_id},
            )
        return scene

    @app.put("/api/projects/{project_id}/scene", response_model=SceneEnvelope)
    def put_scene(project_id: ProjectId, request: SceneSaveRequest, response: Response) -> SceneEnvelope:
        missing_assets = [
            asset.asset_id
            for asset in request.assets
            if not (assets_dir / asset.url.rsplit("/", maxsplit=1)[-1]).is_file()
        ]
        if missing_assets:
            raise HTTPException(
                status_code=422,
                detail={"code": "asset_not_found", "assetIds": missing_assets},
            )
        try:
            saved, is_create = store.save(project_id, request)
        except RevisionConflict as conflict:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "revision_conflict",
                    "currentRevision": conflict.current_revision,
                },
            ) from conflict
        if is_create:
            response.status_code = 201
        return saved

    @app.post(
        "/api/projects/{project_id}/artifacts/glb",
        response_model=ArtifactManifest,
        status_code=202,
    )
    async def upload_glb_artifact(
        project_id: ProjectId,
        background_tasks: BackgroundTasks,
        file: Annotated[UploadFile, File()],
        scene_revision: Annotated[int, Form(alias="sceneRevision", ge=1)],
    ) -> ArtifactManifest:
        scene = store.load(project_id)
        if scene is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "scene_not_found", "projectId": project_id},
            )
        if scene.revision != scene_revision:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "scene_revision_mismatch",
                    "currentRevision": scene.revision,
                },
            )
        try:
            content = await file.read(MAX_GLB_UPLOAD_BYTES + 1)
        finally:
            await file.close()
        if len(content) > MAX_GLB_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="GLB exceeds the 80 MiB upload limit")
        if file.content_type != "model/gltf-binary":
            raise HTTPException(
                status_code=415,
                detail="Content-Type must be model/gltf-binary",
            )
        try:
            validate_glb(content)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        manifest, should_process = artifact_store.begin(project_id, scene_revision, content)
        if should_process:
            background_tasks.add_task(
                artifact_store.process,
                manifest.artifact_id,
                artifact_optimizer,
            )
        return manifest

    @app.get(
        "/api/projects/{project_id}/artifacts/latest",
        response_model=ArtifactManifest,
    )
    def get_latest_artifact(project_id: ProjectId) -> ArtifactManifest:
        manifest = artifact_store.load_latest(project_id)
        if manifest is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "artifact_not_found", "projectId": project_id},
            )
        return manifest

    @app.get("/api/styles", response_model=list[StyleSummary])
    def list_styles() -> list[StyleSummary]:
        return style_catalog.list()

    @app.get("/api/styles/{style_id}", response_model=StylePack)
    def get_style(style_id: StyleId) -> StylePack:
        style = style_catalog.get(style_id)
        if style is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "style_not_found", "styleId": style_id},
            )
        return style

    @app.get(
        "/api/projects/{project_id}/layout",
        response_model=LayoutManifest,
    )
    def get_project_layout(
        project_id: ProjectId,
        style_id: Annotated[str, Query(alias="styleId", pattern=STYLE_ID_RE.pattern)] = "warm-minimal",
    ) -> LayoutManifest:
        scene = store.load(project_id)
        if scene is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "scene_not_found", "projectId": project_id},
            )
        style = style_catalog.get(style_id)
        if style is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "style_not_found", "styleId": style_id},
            )
        return generate_layout(project_id, scene.revision, scene.scene.nodes, style)

    @app.post(
        "/api/projects/{project_id}/renders",
        response_model=RenderManifest,
        status_code=202,
    )
    def create_render(
        project_id: ProjectId,
        request: RenderCreateRequest,
        background_tasks: BackgroundTasks,
    ) -> RenderManifest:
        scene = store.load(project_id)
        if scene is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "scene_not_found", "projectId": project_id},
            )
        if scene.revision != request.scene_revision:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "scene_revision_mismatch",
                    "currentRevision": scene.revision,
                },
            )
        style = style_catalog.get(request.style_id)
        if style is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "style_not_found", "styleId": request.style_id},
            )
        artifact = artifact_store.load_latest(project_id)
        if (
            artifact is None
            or artifact.status != "ready"
            or artifact.scene_revision != request.scene_revision
            or artifact.optimized is None
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "artifact_not_ready",
                    "sceneRevision": request.scene_revision,
                },
            )
        manifest, should_process = render_store.begin(
            project_id,
            request.scene_revision,
            artifact.artifact_id,
            style,
            generate_layout(project_id, scene.revision, scene.scene.nodes, style),
        )
        if should_process:
            background_tasks.add_task(
                render_store.process,
                manifest.render_id,
                render_backend,
                artifact_store.directory / artifact.artifact_id / "optimized.glb",
                style_catalog.path_for(style.id),
                render_store.layout_path(manifest.render_id),
                style,
            )
        return manifest

    @app.get(
        "/api/projects/{project_id}/renders/latest",
        response_model=RenderManifest,
    )
    def get_latest_render(
        project_id: ProjectId,
        style_id: Annotated[str, Query(alias="styleId", pattern=STYLE_ID_RE.pattern)] = "warm-minimal",
    ) -> RenderManifest:
        manifest = render_store.load_latest(project_id, style_id)
        if manifest is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "render_not_found",
                    "projectId": project_id,
                    "styleId": style_id,
                },
            )
        return manifest

    return app


app = create_app()
