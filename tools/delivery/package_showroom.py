from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPOSITORY_ROOT / "services" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.artifacts import ArtifactStore  # noqa: E402
from app.assets import AssetCatalog  # noqa: E402
from app.layouts import generate_layout  # noqa: E402
from app.styles import STYLE_ID_RE, StyleCatalog  # noqa: E402


PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
META_PATTERN = r'(<meta name="{name}" content=")[^"]*(" ?/?>)'
FIXED_ZIP_TIME = (2026, 7, 27, 0, 0, 0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def patch_viewer_index(index_path: Path, project_id: str) -> None:
    html = index_path.read_text(encoding="utf-8")
    values = {
        "showroom-data-base": "./showroom-data",
        "showroom-project-id": project_id,
        "showroom-mode": "presentation",
        "showroom-quality": "high",
    }
    for name, value in values.items():
        pattern = META_PATTERN.format(name=re.escape(name))
        html, count = re.subn(pattern, rf"\g<1>{value}\g<2>", html, count=1)
        if count != 1:
            raise RuntimeError(f"viewer build is missing delivery metadata: {name}")
    html = html.replace('src="/assets/', 'src="./assets/')
    html = html.replace('href="/assets/', 'href="./assets/')
    index_path.write_text(html, encoding="utf-8")


def payload_entries(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == "bundle-manifest.json":
            continue
        entries.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)})
    return entries


def write_launchers(root: Path) -> None:
    copy_file(Path(__file__).with_name("serve_showroom.py"), root / "启动预览.py")
    command = root / "启动预览.command"
    command.write_text(
        '#!/bin/zsh\ncd "$(dirname "$0")"\npython3 "启动预览.py"\n',
        encoding="utf-8",
    )
    command.chmod(command.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (root / "启动预览.bat").write_text(
        '@echo off\r\ncd /d "%~dp0"\r\npython "启动预览.py"\r\npause\r\n',
        encoding="utf-8",
    )
    (root / "预览说明.md").write_text(
        """# 客户 3D 户型预览包

本预览包已包含户型结构、家具、三套装修风格和全部 PBR/HDR 资源，不依赖开发 API。

## 启动

- macOS：双击 `启动预览.command`；如系统阻止，右键选择“打开”。
- Windows：双击 `启动预览.bat`。
- 通用方式：在本目录运行 `python3 启动预览.py`。

浏览器打开终端显示的地址。手机或平板与电脑连接同一 Wi-Fi 后，使用终端显示的局域网地址。

默认使用高端演示画质和干净客户界面。地址后添加 `?mode=full&quality=auto` 可查看完整工程信息并恢复自动画质。

## 完整性

`bundle-manifest.json` 记录每个交付文件的 SHA-256 和字节数，可用于复制、上传或归档后的完整性核验。
""",
        encoding="utf-8",
    )


def deterministic_zip(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    with zipfile.ZipFile(
        temporary,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(candidate for candidate in source.rglob("*") if candidate.is_file()):
            relative = path.relative_to(source).as_posix()
            information = zipfile.ZipInfo(relative, FIXED_ZIP_TIME)
            mode = path.stat().st_mode
            information.external_attr = (mode & 0xFFFF) << 16
            information.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(information, path.read_bytes(), compresslevel=9)
    temporary.replace(output)


def build_showroom_bundle(
    *,
    project_id: str,
    viewer_dist: Path,
    output: Path,
    data_dir: Path,
    style_ids: list[str] | None = None,
) -> dict[str, Any]:
    if not PROJECT_ID_RE.fullmatch(project_id):
        raise ValueError("invalid project id")
    if not (viewer_dist / "index.html").is_file():
        raise FileNotFoundError("viewer dist is missing index.html")

    scene_path = data_dir / "scenes" / f"{project_id}.json"
    scene_value = json.loads(scene_path.read_text(encoding="utf-8"))
    scene_revision = scene_value.get("revision")
    nodes = scene_value.get("scene", {}).get("nodes")
    if not isinstance(scene_revision, int) or scene_revision < 1 or not isinstance(nodes, dict):
        raise ValueError("project scene is invalid")

    artifact_store = ArtifactStore(data_dir / "artifacts")
    artifact = artifact_store.load_latest(project_id)
    if artifact is None or artifact.status != "ready" or artifact.optimized is None:
        raise ValueError("project does not have a ready optimized artifact")
    if artifact.scene_revision != scene_revision:
        raise ValueError("project scene and artifact revision do not match")

    style_catalog = StyleCatalog()
    available_style_ids = [summary.id for summary in style_catalog.list()]
    selected_style_ids = style_ids or available_style_ids
    if (
        not selected_style_ids
        or len(selected_style_ids) != len(set(selected_style_ids))
        or any(not STYLE_ID_RE.fullmatch(style_id) for style_id in selected_style_ids)
    ):
        raise ValueError("style ids are invalid")
    if "warm-minimal" not in selected_style_ids:
        raise ValueError("delivery bundle requires warm-minimal")

    asset_catalog = AssetCatalog()
    layouts = {}
    styles = {}
    for style_id in selected_style_ids:
        style = style_catalog.get(style_id)
        if style is None:
            raise ValueError(f"unknown style: {style_id}")
        styles[style_id] = style
        layouts[style_id] = generate_layout(
            project_id,
            scene_revision,
            nodes,
            style,
            asset_catalog,
        )
    if any(not layout.furnished_room_ids for layout in layouts.values()):
        raise ValueError("delivery layout contains no furnished rooms")

    referenced_asset_ids = {
        placement.asset_id
        for layout in layouts.values()
        for placement in layout.placements
        if asset_catalog.assets[placement.asset_id].delivery is not None
    }

    with tempfile.TemporaryDirectory(prefix=f"{project_id}-showroom-") as temporary_directory:
        staging = Path(temporary_directory)
        shutil.copytree(viewer_dist, staging, dirs_exist_ok=True)
        patch_viewer_index(staging / "index.html", project_id)
        data_root = staging / "showroom-data"
        write_json(
            data_root / "manifest.json",
            artifact.model_dump(by_alias=True, mode="json"),
        )
        write_json(
            data_root / "catalog.json",
            asset_catalog.manifest.model_dump(by_alias=True, mode="json"),
        )
        summaries = [
            summary.model_dump(mode="json")
            for summary in style_catalog.list()
            if summary.id in selected_style_ids
        ]
        write_json(data_root / "styles" / "index.json", summaries)
        for style_id, style in styles.items():
            write_json(
                data_root / "styles" / f"{style_id}.json",
                style.model_dump(by_alias=True, mode="json"),
            )
            write_json(
                data_root / "layouts" / f"{style_id}.json",
                layouts[style_id].model_dump(by_alias=True, mode="json"),
            )

        optimized_source = (
            data_dir
            / "artifacts"
            / artifact.artifact_id
            / artifact.optimized.url.rsplit("/", maxsplit=1)[-1]
        )
        copy_file(
            optimized_source,
            data_root
            / "artifacts"
            / artifact.artifact_id
            / artifact.optimized.url.rsplit("/", maxsplit=1)[-1],
        )
        for asset_id in sorted(referenced_asset_ids):
            delivery = asset_catalog.assets[asset_id].delivery
            assert delivery is not None
            filename = delivery.url.rsplit("/", maxsplit=1)[-1]
            copy_file(
                asset_catalog.models_directory / filename,
                data_root / "catalog-assets" / "models" / filename,
            )
        for notice in sorted(asset_catalog.directory.glob("LICENSE-*.txt")):
            copy_file(notice, data_root / "catalog-assets" / notice.name)

        render_catalog_path = REPOSITORY_ROOT / "packages" / "render-assets" / "catalog.json"
        render_catalog = json.loads(render_catalog_path.read_text(encoding="utf-8"))
        render_root = render_catalog_path.parent
        copy_file(render_catalog_path, data_root / "render-assets" / "catalog.json")
        for resource in render_catalog.get("resources", []):
            delivery = resource.get("delivery") if isinstance(resource, dict) else None
            relative = delivery.get("path") if isinstance(delivery, dict) else None
            if not isinstance(relative, str):
                raise ValueError("render asset delivery path is invalid")
            copy_file(render_root / relative, data_root / "render-assets" / relative)
        license_notice = render_root / render_catalog["license"]["localNotice"]
        copy_file(license_notice, data_root / "render-assets" / license_notice.name)

        write_launchers(staging)
        files = payload_entries(staging)
        bundle_manifest = {
            "schemaVersion": "1.0",
            "projectId": project_id,
            "artifactId": artifact.artifact_id,
            "sceneRevision": scene_revision,
            "styleIds": selected_style_ids,
            "defaultStyleId": "warm-minimal",
            "mode": "presentation",
            "quality": "high",
            "referencedAssetIds": sorted(referenced_asset_ids),
            "payloadBytes": sum(entry["bytes"] for entry in files),
            "files": files,
        }
        write_json(staging / "bundle-manifest.json", bundle_manifest)
        deterministic_zip(staging, output)

    return {
        **bundle_manifest,
        "output": str(output),
        "zipBytes": output.stat().st_size,
        "zipSha256": sha256(output),
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="打包可独立运行的客户 3D 户型预览")
    parser.add_argument("--project-id", required=True)
    parser.add_argument(
        "--viewer-dist",
        type=Path,
        default=REPOSITORY_ROOT / "apps" / "viewer" / "dist",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPOSITORY_ROOT / "services" / "api" / "data",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--style", action="append", dest="style_ids")
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    report = build_showroom_bundle(
        project_id=arguments.project_id,
        viewer_dist=arguments.viewer_dist.resolve(),
        output=arguments.output.resolve(),
        data_dir=arguments.data_dir.resolve(),
        style_ids=arguments.style_ids,
    )
    summary = {
        "projectId": report["projectId"],
        "styleIds": report["styleIds"],
        "fileCount": len(report["files"]),
        "payloadBytes": report["payloadBytes"],
        "zipBytes": report["zipBytes"],
        "zipSha256": report["zipSha256"],
        "output": report["output"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
