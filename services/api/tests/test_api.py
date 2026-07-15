from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import MAX_UPLOAD_BYTES, create_app


PNG = b"\x89PNG\r\n\x1a\nminimal-png"
JPG = b"\xff\xd8\xffminimal-jpg"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    with TestClient(create_app(tmp_path)) as test_client:
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
