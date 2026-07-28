from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RENDER_DIRECTORY = (
    REPOSITORY_ROOT / "work" / "cinematic-renders" / "warm-minimal-living"
)
DEFAULT_OUTPUT_DIRECTORY = (
    REPOSITORY_ROOT / "work" / "deliveries" / "warm-minimal-living"
)
APP_DIRECTORY = REPOSITORY_ROOT / "apps" / "cinematic-showroom"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="打包暖木极简客厅离线效果展厅")
    parser.add_argument("--render-directory", type=Path, default=DEFAULT_RENDER_DIRECTORY)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--skip-launcher", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def require_file(path: Path) -> Path:
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(path)
    return path


def convert_jpeg(source: Path, destination: Path, quality: int) -> None:
    sips = shutil.which("sips")
    if not sips:
        raise RuntimeError("当前系统缺少 sips，无法生成浏览版 JPEG")
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sips,
            "-s",
            "format",
            "jpeg",
            "-s",
            "formatOptions",
            str(quality),
            str(source),
            "--out",
            str(destination),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    require_file(destination)


def compile_launcher(destination: Path) -> None:
    clang = shutil.which("clang")
    if not clang:
        raise RuntimeError("当前系统缺少 clang，无法生成自包含启动器")
    source = REPOSITORY_ROOT / "tools" / "cinematic" / "showroom_server.c"
    subprocess.run(
        [clang, "-O2", "-Wall", "-Wextra", str(source), "-o", str(destination)],
        check=True,
    )
    destination.chmod(0o755)


def copy_static_app(destination: Path) -> None:
    for name in ("index.html", "styles.css", "app.js"):
        shutil.copy2(require_file(APP_DIRECTORY / name), destination / name)


def write_instructions(destination: Path) -> None:
    (destination / "启动展厅.command").write_text(
        '#!/bin/zsh\ncd "${0:A:h}"\nexec "./打开展厅"\n',
        encoding="utf-8",
    )
    (destination / "启动展厅.command").chmod(0o755)
    (destination / "使用说明.txt").write_text(
        "暖木极简客厅 · 离线效果展厅\n\n"
        "macOS：双击“启动展厅.command”。首次打开若系统询问，请选择允许。\n"
        "电脑浏览器会自动打开；终端会同时显示手机和平板访问地址。\n"
        "移动设备必须与电脑连接同一 Wi-Fi，并保持启动窗口开启。\n"
        "结束展示时关闭启动窗口，或按 Control + C。\n\n"
        "masters 目录保存 4K/8K 原始 PNG；media 目录是浏览器优化版。\n",
        encoding="utf-8",
    )


def file_manifest(root: Path) -> dict[str, Any]:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == "manifest.json":
            continue
        files.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    return {
        "schemaVersion": "1.0",
        "id": "warm-minimal-living-offline-showroom",
        "files": files,
    }


def deterministic_zip(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(item for item in source.rglob("*") if item.is_file()):
            relative = path.relative_to(source.parent).as_posix()
            info = zipfile.ZipInfo(relative, (2026, 7, 28, 0, 0, 0))
            info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as stream:
                archive.writestr(info, stream.read())


def build_package(
    render_directory: Path,
    output_directory: Path,
    skip_launcher: bool,
) -> tuple[Path, Path]:
    hero = require_file(render_directory / "hero-hero.png")
    panorama = require_file(render_directory / "panorama-panorama.png")
    with tempfile.TemporaryDirectory(
        prefix="warm-minimal-showroom-",
        dir=output_directory.parent,
    ) as temporary:
        staging = Path(temporary) / output_directory.name
        staging.mkdir(parents=True)
        copy_static_app(staging)
        (staging / "media").mkdir()
        (staging / "masters").mkdir()
        (staging / "licenses").mkdir()
        (staging / "reports").mkdir()

        shutil.copy2(hero, staging / "masters" / "hero-4k.png")
        shutil.copy2(panorama, staging / "masters" / "panorama-8k.png")
        convert_jpeg(hero, staging / "media" / "hero-4k.jpg", 94)
        convert_jpeg(panorama, staging / "media" / "panorama-8k.jpg", 92)

        shutil.copy2(
            REPOSITORY_ROOT / "packages" / "cinematic-assets" / "LICENSE-POLY-HAVEN.txt",
            staging / "licenses" / "POLY-HAVEN-CC0.txt",
        )
        shutil.copy2(
            REPOSITORY_ROOT / "packages" / "cinematic-assets" / "catalog.json",
            staging / "reports" / "asset-catalog.json",
        )
        shutil.copy2(
            REPOSITORY_ROOT
            / "packages"
            / "cinematic-scenes"
            / "warm-minimal-living-v1.json",
            staging / "reports" / "scene-spec.json",
        )
        for name in ("hero-report.json", "panorama-report.json"):
            shutil.copy2(require_file(render_directory / name), staging / "reports" / name)
        write_instructions(staging)
        if not skip_launcher:
            compile_launcher(staging / "打开展厅")

        manifest = file_manifest(staging)
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if output_directory.exists():
            shutil.rmtree(output_directory)
        shutil.copytree(staging, output_directory)

    zip_path = output_directory.with_suffix(".zip")
    temporary_zip = zip_path.with_suffix(".zip.part")
    deterministic_zip(output_directory, temporary_zip)
    os.replace(temporary_zip, zip_path)
    return output_directory, zip_path


def main() -> None:
    args = parse_arguments()
    args.output_directory.parent.mkdir(parents=True, exist_ok=True)
    directory, zip_path = build_package(
        args.render_directory.resolve(),
        args.output_directory.resolve(),
        args.skip_launcher,
    )
    print(
        json.dumps(
            {
                "directory": str(directory),
                "zip": str(zip_path),
                "zipBytes": zip_path.stat().st_size,
                "zipSha256": sha256(zip_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
