from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
APP_DIRECTORY = REPOSITORY_ROOT / "apps" / "cinematic-showroom"


def test_showroom_is_offline_and_chinese_first() -> None:
    html = (APP_DIRECTORY / "index.html").read_text(encoding="utf-8")
    script = (APP_DIRECTORY / "app.js").read_text(encoding="utf-8")

    assert 'lang="zh-CN"' in html
    assert "4K 主图" in html
    assert "8K 全景" in html
    assert "复制当前地址" in html
    assert "http://" not in html
    assert "https://" not in html
    assert "http://" not in script
    assert "https://" not in script
    assert "getContext(\"webgl2\"" in script
    assert "MAX_TEXTURE_SIZE" in script
    assert "pointerDistance()" in script
    assert "this.pointers.size >= 2" in script
    assert 'this.canvas.addEventListener("keydown"' in script
    assert 'loadingStatus.hidden = Boolean(ready)' in script
    assert 'activeMode === "hero" ? heroReady : panoramaReady' in script
    assert 'tabindex="0"' in html


def test_showroom_packager_requires_master_media_and_native_launcher() -> None:
    packager = (
        REPOSITORY_ROOT / "tools" / "cinematic" / "package_showroom.py"
    ).read_text(encoding="utf-8")
    launcher = (
        REPOSITORY_ROOT / "tools" / "cinematic" / "showroom_server.c"
    ).read_text(encoding="utf-8")

    assert 'render_directory / "hero-hero.png"' in packager
    assert 'render_directory / "panorama-panorama.png"' in packager
    assert "deterministic_zip" in packager
    assert "compile_launcher" in packager
    assert 'strstr(relative, "..")' in launcher
    assert "INADDR_ANY" in launcher
    assert "Cache-Control: no-store" in launcher
