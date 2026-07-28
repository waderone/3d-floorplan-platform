from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = REPOSITORY_ROOT / "packages" / "cinematic-assets" / "catalog.json"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "work" / "cinematic-assets"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="下载并校验离线商业效果素材")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--resource", action="append")
    return parser.parse_args()


def load_catalog(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != "1.0"
        or not isinstance(value.get("resources"), list)
    ):
        raise ValueError("cinematic asset catalog is invalid")
    return value


def digest(path: Path) -> str:
    checksum = hashlib.md5()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def validate_file(path: Path, delivery: dict[str, Any]) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size != delivery["bytes"]:
        raise RuntimeError(f"素材字节数不匹配：{path}")
    if digest(path) != delivery["md5"]:
        raise RuntimeError(f"素材校验值不匹配：{path}")


def download(resource: dict[str, Any], output_directory: Path) -> Path:
    delivery = resource["delivery"]
    destination = output_directory / delivery["path"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        try:
            validate_file(destination, delivery)
            return destination
        except RuntimeError:
            destination.unlink()
    temporary = destination.with_suffix(destination.suffix + ".part")
    curl = shutil.which("curl")
    if curl:
        subprocess.run(
            [
                curl,
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                "--user-agent",
                "floorplan-cinematic-delivery/1.0 (asset audit)",
                "--output",
                str(temporary),
                resource["url"],
            ],
            check=True,
        )
    else:
        request = urllib.request.Request(
            resource["url"],
            headers={"User-Agent": "floorplan-cinematic-delivery/1.0 (asset audit)"},
        )
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as stream:
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
    temporary.replace(destination)
    validate_file(destination, delivery)
    return destination


def main() -> None:
    args = parse_arguments()
    catalog = load_catalog(args.catalog)
    requested = set(args.resource or ())
    resources = [
        resource
        for resource in catalog["resources"]
        if not requested or resource["id"] in requested
    ]
    missing = requested - {resource["id"] for resource in resources}
    if missing:
        raise ValueError(f"未知素材：{', '.join(sorted(missing))}")
    for index, resource in enumerate(resources, start=1):
        path = args.output_directory / resource["delivery"]["path"]
        if args.verify_only:
            validate_file(path, resource["delivery"])
        else:
            path = download(resource, args.output_directory)
        print(f"[{index}/{len(resources)}] {resource['id']} -> {path}")


if __name__ == "__main__":
    main()
