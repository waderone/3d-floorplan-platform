from __future__ import annotations

import hashlib
import json
import shutil
import struct
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import MAX_UPLOAD_BYTES, create_app


PNG = b"\x89PNG\r\n\x1a\nminimal-png"
JPG = b"\xff\xd8\xffminimal-jpg"


def valid_glb() -> bytes:
    json_chunk = b'{"asset":{"version":"2.0"}}'
    json_chunk += b" " * (-len(json_chunk) % 4)
    total_length = 12 + 8 + len(json_chunk)
    return (
        struct.pack("<4sII", b"glTF", 2, total_length)
        + struct.pack("<I4s", len(json_chunk), b"JSON")
        + json_chunk
    )


class CopyOptimizer:
    def optimize(self, source: Path, output: Path) -> dict[str, Any]:
        shutil.copyfile(source, output)
        content = source.read_bytes()
        metrics = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            "nodes": 1,
            "meshes": 1,
            "materials": 1,
            "primitives": 1,
        }
        return {"source": metrics, "optimized": metrics}


class FailingOptimizer:
    def optimize(self, source: Path, output: Path) -> dict[str, Any]:
        raise RuntimeError("synthetic optimizer failure")


class CopyRenderer:
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
        style = json.loads(style_path.read_text(encoding="utf-8"))
        layout = json.loads(layout_path.read_text(encoding="utf-8"))
        catalog = json.loads(asset_catalog_path.read_text(encoding="utf-8"))
        render_catalog = json.loads(render_profile_catalog_path.read_text(encoding="utf-8"))
        profile = render_catalog["profiles"][profile_id]
        assert layout["style"]["id"] == style["id"]
        assert layout["assetCatalog"] == {"id": catalog["id"], "version": catalog["version"]}
        png_header = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(
            ">IIBBBBB", profile["width"], profile["height"], 8, 2, 0, 0, 0
        )
        for view in profile["views"]:
            (output_directory / f".{view['id']}.tmp.png").write_bytes(png_header)
        model_ids = {asset["id"] for asset in catalog["assets"] if asset["kind"] == "model"}
        real_asset_placements = sum(
            placement["assetId"] in model_ids for placement in layout["placements"]
        )
        return {
            "engine": profile["engine"],
            "device": "METAL:test" if profile["engine"] == "CYCLES" else "RASTER:test",
            "blenderVersion": "5.2.0 LTS test",
            "renderSeconds": 0.01,
            "profileId": profile_id,
            "profileVersion": profile["version"],
            "views": [
                {"id": view["id"], "renderSeconds": 0.01} for view in profile["views"]
            ],
            "assetCatalogId": catalog["id"],
            "assetCatalogVersion": catalog["version"],
            "realAssetPlacements": real_asset_placements,
            "fallbackPlacements": 0,
            "openingCount": len(layout["openings"]),
            "ignoredOpeningCount": len(layout["ignoredOpeningIds"]),
            "openingBlockedRoomCount": len(layout["openingBlockedRoomIds"]),
            "openingClearanceValidated": layout["openingClearanceValidated"],
        }


class FailingRenderer:
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
        raise RuntimeError("synthetic render failure")


class IncompleteRenderer(CopyRenderer):
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
        super().render(
            source_glb,
            style_path,
            layout_path,
            asset_catalog_path,
            render_profile_catalog_path,
            profile_id,
            output_directory,
        )
        return {}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    with TestClient(
        create_app(tmp_path, optimizer=CopyOptimizer(), renderer=CopyRenderer())
    ) as test_client:
        yield test_client


def scene_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": "1.0",
        "revision": 0,
        "expectedRevision": None,
        "units": "m",
        "scene": {
            "nodes": {},
            "rootNodeIds": [],
            "collections": {},
            "materials": {},
        },
        "assets": [],
    }
    payload.update(changes)
    return payload


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_preflight_allows_editor_origin(client: TestClient) -> None:
    response = client.options(
        "/api/assets",
        headers={
            "Origin": "http://localhost:3002",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


@pytest.mark.parametrize(
    ("filename", "media_type", "content", "extension"),
    [
        ("floor.png", "image/png", PNG, ".png"),
        ("floor.jpg", "image/jpeg", JPG, ".jpg"),
    ],
)
def test_upload_supported_images_is_stable(
    client: TestClient,
    filename: str,
    media_type: str,
    content: bytes,
    extension: str,
) -> None:
    first = client.post("/api/assets", files={"file": (filename, content, media_type)})
    second = client.post("/api/assets", files={"file": ("renamed", content, media_type)})

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["url"] == second.json()["url"]
    assert first.json()["url"].endswith(extension)
    assert first.json()["mediaType"] == media_type
    assert client.get(first.json()["url"]).content == content


@pytest.mark.parametrize(
    ("media_type", "content"),
    [
        ("image/gif", b"GIF89a"),
        ("image/png", JPG),
        ("application/octet-stream", PNG),
    ],
)
def test_upload_rejects_unsupported_or_spoofed_types(
    client: TestClient, media_type: str, content: bytes
) -> None:
    response = client.post("/api/assets", files={"file": ("floor", content, media_type)})
    assert response.status_code == 415


def test_upload_rejects_images_over_size_limit(client: TestClient) -> None:
    content = PNG + b"x" * MAX_UPLOAD_BYTES
    response = client.post(
        "/api/assets",
        files={"file": ("too-large.png", content, "image/png")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Image exceeds the 20 MiB upload limit"


def test_create_update_and_load_scene(client: TestClient) -> None:
    missing = client.get("/api/projects/demo/scene")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "scene_not_found"

    created = client.put("/api/projects/demo/scene", json=scene_payload())
    assert created.status_code == 201
    assert created.json()["revision"] == 1

    loaded = client.get("/api/projects/demo/scene")
    assert loaded.status_code == 200
    assert loaded.json() == created.json()

    updated = client.put(
        "/api/projects/demo/scene",
        json=scene_payload(
            revision=1,
            expectedRevision=1,
            scene={
                "nodes": {"wall-1": {"id": "wall-1", "type": "wall"}},
                "rootNodeIds": [],
            },
        ),
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert updated.json()["scene"]["nodes"]["wall-1"]["id"] == "wall-1"


@pytest.mark.parametrize(
    "scene",
    [
        {"nodes": {"node-1": None}, "rootNodeIds": []},
        {
            "nodes": {"node-1": {"id": "different-id", "type": "wall"}},
            "rootNodeIds": [],
        },
        {
            "nodes": {"node-1": {"id": "node-1", "type": "site"}},
            "rootNodeIds": ["missing-root"],
        },
    ],
)
def test_scene_rejects_invalid_node_structure(client: TestClient, scene: dict[str, object]) -> None:
    response = client.put(
        "/api/projects/invalid-scene/scene",
        json=scene_payload(scene=scene),
    )

    assert response.status_code == 422


def test_scene_rejects_untrusted_asset_metadata(client: TestClient) -> None:
    response = client.put(
        "/api/projects/invalid-asset/scene",
        json=scene_payload(
            assets=[
                {
                    "assetId": "not-a-sha",
                    "url": "https://example.com/floor.png",
                    "mediaType": "image/png",
                    "size": 12,
                }
            ]
        ),
    )

    assert response.status_code == 422


def test_scene_rejects_asset_identity_mismatch(client: TestClient) -> None:
    response = client.put(
        "/api/projects/mismatched-asset/scene",
        json=scene_payload(
            assets=[
                {
                    "assetId": "0" * 64,
                    "url": f"/platform-assets/{'1' * 64}.jpg",
                    "mediaType": "image/png",
                    "size": 12,
                }
            ]
        ),
    )

    assert response.status_code == 422


def test_scene_rejects_missing_asset_file(client: TestClient) -> None:
    missing_id = "0" * 64
    response = client.put(
        "/api/projects/missing-asset/scene",
        json=scene_payload(
            assets=[
                {
                    "assetId": missing_id,
                    "url": f"/platform-assets/{missing_id}.png",
                    "mediaType": "image/png",
                    "size": 12,
                }
            ]
        ),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "asset_not_found",
        "assetIds": [missing_id],
    }


def test_scene_round_trip_preserves_proxied_asset_metadata(client: TestClient) -> None:
    upload = client.post(
        "/api/assets",
        files={"file": ("floor.png", PNG, "image/png")},
    )
    assert upload.status_code == 201
    asset = upload.json()
    asset["url"] = asset["url"].replace("/assets/", "/platform-assets/")

    created = client.put(
        "/api/projects/asset-round-trip/scene",
        json=scene_payload(assets=[asset]),
    )

    assert created.status_code == 201
    assert created.json()["assets"] == [asset]
    assert client.get("/api/projects/asset-round-trip/scene").json()["assets"] == [asset]


def test_revision_conflicts_are_explicit(client: TestClient) -> None:
    missing_expected_revision = scene_payload()
    missing_expected_revision.pop("expectedRevision")
    missing_token = client.put(
        "/api/projects/new-project/scene",
        json=missing_expected_revision,
    )
    assert missing_token.status_code == 422

    invalid_first_create = client.put(
        "/api/projects/new-project/scene",
        json=scene_payload(revision=0, expectedRevision=0),
    )
    assert invalid_first_create.status_code == 409
    assert invalid_first_create.json()["detail"] == {
        "code": "revision_conflict",
        "currentRevision": None,
    }

    assert client.put("/api/projects/demo/scene", json=scene_payload()).status_code == 201

    stale = client.put(
        "/api/projects/demo/scene",
        json=scene_payload(revision=0, expectedRevision=0),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "revision_conflict",
        "currentRevision": 1,
    }

    recreate = client.put("/api/projects/demo/scene", json=scene_payload())
    assert recreate.status_code == 409
    assert recreate.json()["detail"]["currentRevision"] == 1


def test_paths_cannot_escape_data_directory(client: TestClient, tmp_path: Path) -> None:
    upload = client.post(
        "/api/assets",
        files={"file": ("../../outside.png", PNG, "image/png")},
    )
    assert upload.status_code == 201
    assert ".." not in upload.json()["url"]
    assert not (tmp_path.parent / "outside.png").exists()

    invalid_project = client.put(
        "/api/projects/%2E%2E/scene",
        json=scene_payload(),
    )
    assert invalid_project.status_code == 422
    assert not (tmp_path.parent / "scene.json").exists()


def test_glb_artifact_requires_a_saved_scene(client: TestClient) -> None:
    response = client.post(
        "/api/projects/missing/artifacts/glb",
        data={"sceneRevision": "1"},
        files={"file": ("model.glb", valid_glb(), "model/gltf-binary")},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "scene_not_found"


def test_glb_artifact_rejects_stale_scene_revision(client: TestClient) -> None:
    assert client.put("/api/projects/model/scene", json=scene_payload()).status_code == 201

    response = client.post(
        "/api/projects/model/artifacts/glb",
        data={"sceneRevision": "2"},
        files={"file": ("model.glb", valid_glb(), "model/gltf-binary")},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "scene_revision_mismatch",
        "currentRevision": 1,
    }


@pytest.mark.parametrize(
    ("media_type", "content", "expected_status"),
    [
        ("application/octet-stream", valid_glb(), 415),
        ("model/gltf-binary", b"not-a-glb", 422),
        ("model/gltf-binary", valid_glb()[:-1], 422),
    ],
)
def test_glb_artifact_rejects_invalid_uploads(
    client: TestClient,
    media_type: str,
    content: bytes,
    expected_status: int,
) -> None:
    assert client.put("/api/projects/invalid-glb/scene", json=scene_payload()).status_code == 201

    response = client.post(
        "/api/projects/invalid-glb/artifacts/glb",
        data={"sceneRevision": "1"},
        files={"file": ("model.glb", content, media_type)},
    )

    assert response.status_code == expected_status


def test_glb_artifact_rejects_files_over_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert client.put("/api/projects/large-glb/scene", json=scene_payload()).status_code == 201
    monkeypatch.setattr("app.main.MAX_GLB_UPLOAD_BYTES", 32)

    response = client.post(
        "/api/projects/large-glb/artifacts/glb",
        data={"sceneRevision": "1"},
        files={"file": ("model.glb", valid_glb(), "model/gltf-binary")},
    )

    assert response.status_code == 413


def test_glb_artifact_is_optimized_and_served(client: TestClient) -> None:
    assert client.put("/api/projects/model/scene", json=scene_payload()).status_code == 201
    content = valid_glb()

    accepted = client.post(
        "/api/projects/model/artifacts/glb",
        data={"sceneRevision": "1"},
        files={"file": ("model.glb", content, "model/gltf-binary")},
    )

    assert accepted.status_code == 202
    assert accepted.json()["status"] == "processing"
    manifest = client.get("/api/projects/model/artifacts/latest")
    assert manifest.status_code == 200
    payload = manifest.json()
    assert payload["status"] == "ready"
    assert payload["sceneRevision"] == 1
    assert payload["pipelineVersion"] == "gltf-transform-4.4.1-pascal-v4"
    assert payload["source"]["bytes"] == len(content)
    assert payload["source"]["statistics"]["nodes"] == 1
    assert payload["optimized"]["statistics"]["meshes"] == 1
    assert payload["mobileBudgetExceeded"] is False
    assert client.get(payload["optimized"]["url"]).content == content

    duplicate = client.post(
        "/api/projects/model/artifacts/glb",
        data={"sceneRevision": "1"},
        files={"file": ("renamed.glb", content, "model/gltf-binary")},
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["artifactId"] == payload["artifactId"]
    assert duplicate.json()["status"] == "ready"


def test_glb_optimizer_failure_is_persisted(tmp_path: Path) -> None:
    with TestClient(
        create_app(tmp_path, optimizer=FailingOptimizer(), renderer=CopyRenderer())
    ) as client:
        assert client.put("/api/projects/failure/scene", json=scene_payload()).status_code == 201
        accepted = client.post(
            "/api/projects/failure/artifacts/glb",
            data={"sceneRevision": "1"},
            files={"file": ("model.glb", valid_glb(), "model/gltf-binary")},
        )
        manifest = client.get("/api/projects/failure/artifacts/latest")

    assert accepted.status_code == 202
    assert manifest.status_code == 200
    assert manifest.json()["status"] == "failed"
    assert manifest.json()["error"] == "synthetic optimizer failure"


def test_style_catalog_is_listed_and_served(client: TestClient) -> None:
    styles = client.get("/api/styles")
    style = client.get("/api/styles/warm-minimal")

    assert styles.status_code == 200
    assert [value["id"] for value in styles.json()] == [
        "modern-contrast",
        "nordic-light",
        "warm-minimal",
    ]
    assert style.status_code == 200
    assert style.json()["schemaVersion"] == "1.1"
    assert style.json()["version"] == 2
    assert style.json()["materials"]["architecture"]["baseColor"] == "#F3EADF"
    assert style.json()["assets"][0]["source"] == "project-authored"
    assert client.get("/api/styles/missing-style").status_code == 404


def test_project_layout_exposes_ready_and_fallback_states(client: TestClient) -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "room-layout-scene.json").read_text(
            encoding="utf-8"
        )
    )
    nodes = fixture["scene"]["nodes"]
    nodes["level_layout"]["children"].extend(["wall_entry", "wall_bedroom_window"])
    nodes["wall_entry"] = {
        "id": "wall_entry",
        "type": "wall",
        "parentId": "level_layout",
        "children": ["door_entry"],
        "start": [-8, -4],
        "end": [-8, 3],
    }
    nodes["door_entry"] = {
        "id": "door_entry",
        "type": "door",
        "parentId": "wall_entry",
        "wallId": "wall_entry",
        "position": [1, 1.05, 0],
        "width": 0.9,
        "height": 2.1,
        "doorType": "hinged",
    }
    nodes["wall_bedroom_window"] = {
        "id": "wall_bedroom_window",
        "type": "wall",
        "parentId": "level_layout",
        "children": ["window_bedroom"],
        "start": [-2, 6],
        "end": [3, 6],
    }
    nodes["window_bedroom"] = {
        "id": "window_bedroom",
        "type": "window",
        "parentId": "wall_bedroom_window",
        "wallId": "wall_bedroom_window",
        "position": [4, 1.55, 0],
        "width": 1.5,
        "height": 1.5,
        "windowType": "casement",
    }
    assert client.put(
        "/api/projects/room-layout/scene",
        json=scene_payload(scene=fixture["scene"]),
    ).status_code == 201
    ready = client.get(
        "/api/projects/room-layout/layout",
        params={"styleId": "modern-contrast"},
    )

    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["selectedRoomId"] == "zone_living"
    assert ready.json()["style"] == {"id": "modern-contrast", "version": 1}
    assert ready.json()["placements"][0]["roomId"] == "zone_living"
    assert {entry["sourceType"] for entry in ready.json()["openings"]} == {"door", "window"}
    assert ready.json()["openingClearanceValidated"] is True
    assert ready.json()["ignoredOpeningIds"] == []

    assert client.put(
        "/api/projects/no-layout/scene",
        json=scene_payload(),
    ).status_code == 201
    fallback = client.get("/api/projects/no-layout/layout")
    assert fallback.status_code == 200
    assert fallback.json()["status"] == "fallback"
    assert fallback.json()["fallbackReason"] == "no-room-polygon"
    assert fallback.json()["placements"] == []


def publish_model(client: TestClient, project_id: str = "render-model") -> dict[str, Any]:
    assert client.put(f"/api/projects/{project_id}/scene", json=scene_payload()).status_code == 201
    uploaded = client.post(
        f"/api/projects/{project_id}/artifacts/glb",
        data={"sceneRevision": "1"},
        files={"file": ("model.glb", valid_glb(), "model/gltf-binary")},
    )
    assert uploaded.status_code == 202
    artifact = client.get(f"/api/projects/{project_id}/artifacts/latest")
    assert artifact.json()["status"] == "ready"
    return artifact.json()


def test_render_requires_ready_artifact_and_known_style(client: TestClient) -> None:
    assert client.put("/api/projects/no-model/scene", json=scene_payload()).status_code == 201
    missing_artifact = client.post(
        "/api/projects/no-model/renders",
        json={"sceneRevision": 1, "styleId": "warm-minimal"},
    )
    assert missing_artifact.status_code == 409
    assert missing_artifact.json()["detail"]["code"] == "artifact_not_ready"

    publish_model(client, "unknown-style")
    unknown_style = client.post(
        "/api/projects/unknown-style/renders",
        json={"sceneRevision": 1, "styleId": "missing-style"},
    )
    assert unknown_style.status_code == 404
    assert unknown_style.json()["detail"]["code"] == "style_not_found"

    unknown_profile = client.post(
        "/api/projects/unknown-style/renders",
        json={"sceneRevision": 1, "styleId": "warm-minimal", "profileId": "missing"},
    )
    assert unknown_profile.status_code == 404
    assert unknown_profile.json()["detail"]["code"] == "render_profile_not_found"


def test_render_is_deterministic_processed_and_served(client: TestClient) -> None:
    artifact = publish_model(client)
    accepted = client.post(
        "/api/projects/render-model/renders",
        json={"sceneRevision": 1, "styleId": "warm-minimal"},
    )
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "processing"

    latest = client.get(
        "/api/projects/render-model/renders/latest",
        params={"styleId": "warm-minimal"},
    )
    assert latest.status_code == 200
    payload = latest.json()
    layout = client.get("/api/projects/render-model/layout").json()
    assert payload["status"] == "ready"
    assert payload["artifactId"] == artifact["artifactId"]
    assert payload["pipelineVersion"] == "blender-5x-quality-profiles-v7"
    assert payload["style"] == {"id": "warm-minimal", "version": 2}
    assert len(payload["layoutId"]) == 64
    assert payload["layoutId"] == layout["layoutId"]
    assert payload["output"]["width"] == 1280
    assert payload["output"]["height"] == 720
    assert payload["profile"] == {"id": "preview", "version": 1}
    assert [view["id"] for view in payload["views"]] == ["overview"]
    assert payload["engine"] == "BLENDER_EEVEE"
    assert payload["device"] == "RASTER:test"
    assert payload["blenderVersion"] == "5.2.0 LTS test"
    assert payload["openingCount"] == 0
    assert payload["ignoredOpeningCount"] == 0
    assert payload["openingBlockedRoomCount"] == 0
    assert payload["openingClearanceValidated"] is True
    assert client.get(payload["output"]["url"]).content.startswith(b"\x89PNG")

    duplicate = client.post(
        "/api/projects/render-model/renders",
        json={"sceneRevision": 1, "styleId": "warm-minimal"},
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["renderId"] == payload["renderId"]
    assert duplicate.json()["status"] == "ready"


def test_quality_render_has_distinct_identity_and_three_views(client: TestClient) -> None:
    publish_model(client, "quality-render")
    preview = client.post(
        "/api/projects/quality-render/renders",
        json={"sceneRevision": 1, "styleId": "warm-minimal"},
    ).json()
    accepted_quality = client.post(
        "/api/projects/quality-render/renders",
        json={"sceneRevision": 1, "styleId": "warm-minimal", "profileId": "quality"},
    ).json()
    quality = client.get(
        "/api/projects/quality-render/renders/latest",
        params={"styleId": "warm-minimal", "profileId": "quality"},
    ).json()

    assert accepted_quality["status"] == "processing"
    assert quality["status"] == "ready"
    assert quality["renderId"] != preview["renderId"]
    assert quality["profile"] == {"id": "quality", "version": 1}
    assert quality["engine"] == "CYCLES"
    assert quality["device"] == "METAL:test"
    assert [view["id"] for view in quality["views"]] == ["overview", "living", "bedroom"]
    assert all(view["output"]["width"] == 1920 for view in quality["views"])
    assert all(client.get(view["output"]["url"]).status_code == 200 for view in quality["views"])

    latest = client.get(
        "/api/projects/quality-render/renders/latest",
        params={"styleId": "warm-minimal", "profileId": "quality"},
    )
    assert latest.json()["renderId"] == quality["renderId"]


def test_render_failure_is_persisted(tmp_path: Path) -> None:
    with TestClient(
        create_app(tmp_path, optimizer=CopyOptimizer(), renderer=FailingRenderer())
    ) as client:
        publish_model(client, "render-failure")
        accepted = client.post(
            "/api/projects/render-failure/renders",
            json={"sceneRevision": 1, "styleId": "warm-minimal"},
        )
        manifest = client.get("/api/projects/render-failure/renders/latest")

    assert accepted.status_code == 202
    assert manifest.status_code == 200
    assert manifest.json()["status"] == "failed"
    assert manifest.json()["error"] == "synthetic render failure"


def test_render_incomplete_report_is_rejected(tmp_path: Path) -> None:
    with TestClient(
        create_app(tmp_path, optimizer=CopyOptimizer(), renderer=IncompleteRenderer())
    ) as client:
        publish_model(client, "incomplete-render")
        client.post(
            "/api/projects/incomplete-render/renders",
            json={"sceneRevision": 1, "styleId": "warm-minimal"},
        )
        manifest = client.get("/api/projects/incomplete-render/renders/latest")

    assert manifest.json()["status"] == "failed"
    assert manifest.json()["error"] == "render worker returned incomplete metadata"
