from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field


COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
DEFAULT_CATEGORY = "Category:Floor plans of houses"
USER_AGENT = (
    "3d-floorplan-platform/0.1 "
    "(recognition dataset candidate intake; https://github.com/waderone/3d-floorplan-platform)"
)
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
ELIGIBLE_LICENSE_LABELS = {
    "CC0": "CC0-1.0",
    "Public domain": "Public-Domain",
}


class CommonsCandidate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    candidate_id: str = Field(alias="candidateId", pattern=r"^commons-[1-9][0-9]*$")
    page_id: int = Field(alias="pageId", gt=0)
    title: str = Field(min_length=1, max_length=500)
    author: str = Field(min_length=1, max_length=500)
    description_url: str = Field(alias="descriptionUrl", pattern=r"^https://")
    original_url: str = Field(alias="originalUrl", pattern=r"^https://")
    download_url: str = Field(alias="downloadUrl", pattern=r"^https://")
    mime_type: Literal["image/jpeg", "image/png"] = Field(alias="mimeType")
    source_width: int = Field(alias="sourceWidth", gt=0)
    source_height: int = Field(alias="sourceHeight", gt=0)
    provider_sha1: str = Field(alias="providerSha1", pattern=r"^[0-9a-f]{40}$")
    reported_license_label: Literal["CC0", "Public domain"] = Field(
        alias="reportedLicenseLabel"
    )
    normalized_license_id: Literal["CC0-1.0", "Public-Domain"] = Field(
        alias="normalizedLicenseId"
    )
    license_evidence_url: str = Field(alias="licenseEvidenceUrl", pattern=r"^https://")
    rights_review_status: Literal["pending"] = Field(alias="rightsReviewStatus")
    commercial_use_confirmed: Literal[False] = Field(alias="commercialUseConfirmed")
    redistribution_allowed_confirmed: Literal[False] = Field(
        alias="redistributionAllowedConfirmed"
    )
    selection_status: Literal["pending"] = Field(alias="selectionStatus")
    download_status: Literal["pending", "downloaded", "failed"] = Field(
        alias="downloadStatus",
        default="pending",
    )
    download_file: str | None = Field(alias="downloadFile", default=None)
    download_sha256: str | None = Field(
        alias="downloadSha256",
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    download_bytes: int | None = Field(alias="downloadBytes", default=None, gt=0)
    download_error: str | None = Field(alias="downloadError", default=None, max_length=1000)


class CommonsCandidateQueue(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    provider: Literal["wikimedia-commons"]
    category: str
    requested_limit: int = Field(alias="requestedLimit", ge=1, le=100)
    candidates: list[CommonsCandidate]


def _metadata_value(metadata: dict[str, Any], key: str, default: str) -> str:
    raw = metadata.get(key, {})
    value = raw.get("value") if isinstance(raw, dict) else None
    if not isinstance(value, str) or not value.strip():
        return default
    without_tags = re.sub(r"<[^>]+>", " ", html.unescape(value))
    return " ".join(without_tags.split())[:500] or default


def _https_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith("https://"):
        return value
    return None


def extract_candidate(page: dict[str, Any]) -> CommonsCandidate | None:
    page_id = page.get("pageid")
    title = page.get("title")
    image_info = page.get("imageinfo")
    if (
        not isinstance(page_id, int)
        or page_id <= 0
        or not isinstance(title, str)
        or not isinstance(image_info, list)
        or not image_info
        or not isinstance(image_info[0], dict)
    ):
        return None
    info = image_info[0]
    metadata = info.get("extmetadata")
    if not isinstance(metadata, dict):
        return None
    license_label = _metadata_value(metadata, "LicenseShortName", "")
    normalized_license = ELIGIBLE_LICENSE_LABELS.get(license_label)
    mime_type = info.get("mime")
    width = info.get("width")
    height = info.get("height")
    if (
        normalized_license is None
        or mime_type not in {"image/jpeg", "image/png"}
        or not isinstance(width, int)
        or not isinstance(height, int)
        or min(width, height) < 400
    ):
        return None
    description_url = _https_url(info.get("descriptionurl"))
    original_url = _https_url(info.get("url"))
    download_url = _https_url(info.get("thumburl")) or original_url
    provider_sha1 = info.get("sha1")
    if (
        description_url is None
        or original_url is None
        or download_url is None
        or not isinstance(provider_sha1, str)
        or not re.fullmatch(r"[0-9a-f]{40}", provider_sha1)
    ):
        return None
    license_url = _https_url(_metadata_value(metadata, "LicenseUrl", "")) or description_url
    return CommonsCandidate(
        candidateId=f"commons-{page_id}",
        pageId=page_id,
        title=title.removeprefix("File:")[:500],
        author=_metadata_value(metadata, "Artist", "Unknown; verify on source page"),
        descriptionUrl=description_url,
        originalUrl=original_url,
        downloadUrl=download_url,
        mimeType=mime_type,
        sourceWidth=width,
        sourceHeight=height,
        providerSha1=provider_sha1,
        reportedLicenseLabel=license_label,
        normalizedLicenseId=normalized_license,
        licenseEvidenceUrl=license_url,
        rightsReviewStatus="pending",
        commercialUseConfirmed=False,
        redistributionAllowedConfirmed=False,
        selectionStatus="pending",
    )


def _fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"Commons API returned HTTP {response.status}")
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("Commons API returned an invalid JSON payload")
    return payload


def _fetch_bytes(url: str) -> bytes:
    for attempt in range(4):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 200:
                    raise RuntimeError(f"candidate download returned HTTP {response.status}")
                content = response.read(MAX_DOWNLOAD_BYTES + 1)
            break
        except urllib.error.HTTPError as error:
            if error.code not in {429, 503} or attempt == 3:
                raise
            retry_after = error.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
            time.sleep(min(max(delay, 1), 10))
    if not content or len(content) > MAX_DOWNLOAD_BYTES:
        raise RuntimeError("candidate download is empty or exceeds 20 MiB")
    return content


def collect_candidates(
    limit: int,
    category: str = DEFAULT_CATEGORY,
    fetch_json: Callable[[str], dict[str, Any]] = _fetch_json,
) -> list[CommonsCandidate]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    candidates: dict[str, CommonsCandidate] = {}
    continuation: dict[str, str] = {}
    while len(candidates) < limit:
        parameters = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "generator": "categorymembers",
            "gcmtitle": category,
            "gcmtype": "file",
            "gcmlimit": "50",
            "prop": "imageinfo",
            "iiprop": "url|sha1|mime|size|extmetadata",
            "iiurlwidth": "1024",
            **continuation,
        }
        payload = fetch_json(f"{COMMONS_API_URL}?{urllib.parse.urlencode(parameters)}")
        query = payload.get("query", {})
        pages = query.get("pages", []) if isinstance(query, dict) else []
        if not isinstance(pages, list):
            raise RuntimeError("Commons API query.pages must be an array")
        for page in pages:
            if not isinstance(page, dict):
                continue
            candidate = extract_candidate(page)
            if candidate is not None:
                candidates[candidate.candidate_id] = candidate
                if len(candidates) == limit:
                    break
        next_page = payload.get("continue")
        if len(candidates) >= limit:
            break
        if not isinstance(next_page, dict):
            raise RuntimeError(
                f"Commons category only yielded {len(candidates)} eligible candidates"
            )
        continuation = {
            key: value
            for key, value in next_page.items()
            if isinstance(key, str) and isinstance(value, str)
        }
    return sorted(candidates.values(), key=lambda candidate: candidate.page_id)


def download_candidate(
    candidate: CommonsCandidate,
    directory: Path,
    fetch_bytes: Callable[[str], bytes] = _fetch_bytes,
) -> CommonsCandidate:
    extension = ".jpg" if candidate.mime_type == "image/jpeg" else ".png"
    filename = f"{candidate.candidate_id}{extension}"
    output = directory / filename
    if output.is_file():
        content = output.read_bytes()
    else:
        content = fetch_bytes(candidate.download_url)
    encoded = np.frombuffer(content, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"candidate image cannot be decoded: {candidate.candidate_id}")
    directory.mkdir(parents=True, exist_ok=True)
    if not output.is_file():
        temporary = output.with_suffix(f"{output.suffix}.tmp")
        temporary.write_bytes(content)
        temporary.replace(output)
    return candidate.model_copy(
        update={
            "download_status": "downloaded",
            "download_file": filename,
            "download_sha256": hashlib.sha256(content).hexdigest(),
            "download_bytes": len(content),
            "download_error": None,
        }
    )


def create_contact_sheet(
    candidates: list[CommonsCandidate],
    image_directory: Path,
    output_path: Path,
    columns: int = 4,
) -> None:
    if columns < 1:
        raise ValueError("contact sheet columns must be positive")
    downloaded = [
        candidate
        for candidate in candidates
        if candidate.download_status == "downloaded" and candidate.download_file
    ]
    if not downloaded:
        raise ValueError("contact sheet requires at least one downloaded candidate")
    cell_width, cell_height, label_height = 320, 260, 38
    rows = math.ceil(len(downloaded) / columns)
    canvas = np.full((rows * cell_height, columns * cell_width, 3), 245, dtype=np.uint8)
    for index, candidate in enumerate(downloaded):
        image = cv2.imread(str(image_directory / candidate.download_file))
        if image is None:
            raise RuntimeError(f"contact sheet image is missing: {candidate.download_file}")
        available_height = cell_height - label_height
        scale = min(cell_width / image.shape[1], available_height / image.shape[0])
        resized = cv2.resize(
            image,
            (max(1, round(image.shape[1] * scale)), max(1, round(image.shape[0] * scale))),
            interpolation=cv2.INTER_AREA,
        )
        row, column = divmod(index, columns)
        top = row * cell_height + (available_height - resized.shape[0]) // 2
        left = column * cell_width + (cell_width - resized.shape[1]) // 2
        canvas[top : top + resized.shape[0], left : left + resized.shape[1]] = resized
        label = f"{candidate.candidate_id} | {candidate.reported_license_label}"
        cv2.putText(
            canvas,
            label,
            (column * cell_width + 8, (row + 1) * cell_height - 13),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.43,
            (35, 35, 35),
            1,
            cv2.LINE_AA,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), canvas):
        raise RuntimeError("contact sheet could not be written")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect review-pending Commons floor-plan candidates"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path)
    parser.add_argument("--contact-sheet", type=Path)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--category", default=DEFAULT_CATEGORY)
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    arguments = parser.parse_args()
    if not 0 <= arguments.delay_seconds <= 10:
        parser.error("--delay-seconds must be between 0 and 10")
    if arguments.contact_sheet and not arguments.download_dir:
        parser.error("--contact-sheet requires --download-dir")

    candidates = collect_candidates(arguments.limit, arguments.category)
    if arguments.download_dir:
        downloaded: list[CommonsCandidate] = []
        requested_download = False
        for candidate in candidates:
            extension = ".jpg" if candidate.mime_type == "image/jpeg" else ".png"
            exists = (arguments.download_dir / f"{candidate.candidate_id}{extension}").is_file()
            if requested_download and not exists:
                time.sleep(arguments.delay_seconds)
            requested_download = requested_download or not exists
            try:
                downloaded.append(download_candidate(candidate, arguments.download_dir))
            except Exception as error:
                downloaded.append(
                    candidate.model_copy(
                        update={
                            "download_status": "failed",
                            "download_error": (str(error) or error.__class__.__name__)[:1000],
                        }
                    )
                )
        candidates = downloaded
    queue = CommonsCandidateQueue(
        schemaVersion="1.0",
        provider="wikimedia-commons",
        category=arguments.category,
        requestedLimit=arguments.limit,
        candidates=candidates,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(queue.model_dump(by_alias=True), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if arguments.contact_sheet and arguments.download_dir:
        create_contact_sheet(candidates, arguments.download_dir, arguments.contact_sheet)
    failed_downloads = [
        candidate.candidate_id
        for candidate in candidates
        if candidate.download_status == "failed"
    ]
    if failed_downloads:
        raise RuntimeError(f"candidate downloads failed: {', '.join(failed_downloads)}")


if __name__ == "__main__":
    main()
