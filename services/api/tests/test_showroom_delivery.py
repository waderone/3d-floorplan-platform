from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.delivery.package_showroom import build_showroom_bundle  # noqa: E402


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_showroom_bundle_is_complete_and_deterministic(tmp_path: Path) -> None:
    viewer_dist = tmp_path / "viewer-dist"
    (viewer_dist / "assets").mkdir(parents=True)
    (viewer_dist / "assets" / "app.js").write_text("export {}\n", encoding="utf-8")
    (viewer_dist / "index.html").write_text(
        """<!doctype html><html><head>
<meta name="showroom-data-base" content="" />
<meta name="showroom-project-id" content="" />
<meta name="showroom-mode" content="" />
<meta name="showroom-quality" content="" />
</head><body><script src="/assets/app.js"></script></body></html>
""",
        encoding="utf-8",
    )
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    values = {
        "project_id": "refined-commons-190205778",
        "viewer_dist": viewer_dist,
        "data_dir": ROOT / "services" / "api" / "data",
    }
    first_report = build_showroom_bundle(output=first, **values)
    second_report = build_showroom_bundle(output=second, **values)

    assert first_report["zipSha256"] == second_report["zipSha256"]
    assert file_sha256(first) == file_sha256(second)
    assert first_report["styleIds"] == [
        "modern-contrast",
        "nordic-light",
        "warm-minimal",
    ]
    assert first_report["payloadBytes"] > 10_000_000

    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
        assert {
            "index.html",
            "bundle-manifest.json",
            "启动预览.py",
            "启动预览.command",
            "启动预览.bat",
            "预览说明.md",
            "showroom-data/manifest.json",
            "showroom-data/catalog.json",
            "showroom-data/styles/index.json",
            "showroom-data/styles/warm-minimal.json",
            "showroom-data/styles/nordic-light.json",
            "showroom-data/styles/modern-contrast.json",
            "showroom-data/layouts/warm-minimal.json",
            "showroom-data/layouts/nordic-light.json",
            "showroom-data/layouts/modern-contrast.json",
        }.issubset(names)
        index = archive.read("index.html").decode("utf-8")
        assert 'name="showroom-data-base" content="./showroom-data"' in index
        assert 'name="showroom-project-id" content="refined-commons-190205778"' in index
        assert 'name="showroom-mode" content="presentation"' in index
        assert 'name="showroom-quality" content="high"' in index
        assert 'src="./assets/app.js"' in index
        launcher = archive.read("启动预览.py").decode("utf-8")
        assert 'self.send_header("Cache-Control", "no-store, max-age=0")' in launcher

        manifest = json.loads(archive.read("bundle-manifest.json"))
        assert manifest["projectId"] == "refined-commons-190205778"
        assert manifest["defaultStyleId"] == "warm-minimal"
        assert manifest["mode"] == "presentation"
        assert manifest["quality"] == "high"
        for entry in manifest["files"]:
            content = archive.read(entry["path"])
            assert len(content) == entry["bytes"]
            assert hashlib.sha256(content).hexdigest() == entry["sha256"]
