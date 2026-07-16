from __future__ import annotations

import hashlib
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

from app.recognition_candidates import (
    CommonsCandidate,
    _fetch_bytes,
    collect_candidates,
    create_contact_sheet,
    download_candidate,
    extract_candidate,
)


def _page(
    page_id: int,
    *,
    license_label: str = "CC0",
    mime_type: str = "image/png",
    width: int = 1200,
    height: int = 800,
) -> dict[str, object]:
    return {
        "pageid": page_id,
        "title": f"File:Floor plan {page_id}.png",
        "imageinfo": [
            {
                "descriptionurl": (
                    "https://commons.wikimedia.org/wiki/"
                    f"File:Floor_plan_{page_id}.png"
                ),
                "url": f"https://upload.wikimedia.org/original-{page_id}.png",
                "thumburl": f"https://upload.wikimedia.org/thumb-{page_id}.png",
                "sha1": f"{page_id:040x}",
                "mime": mime_type,
                "width": width,
                "height": height,
                "extmetadata": {
                    "LicenseShortName": {"value": license_label},
                    "LicenseUrl": {"value": "//creativecommons.org/publicdomain/zero/1.0/"},
                    "Artist": {"value": "<b>Example &amp; Author</b>"},
                },
            }
        ],
    }


def test_candidate_extraction_keeps_rights_pending_and_filters_inputs() -> None:
    candidate = extract_candidate(_page(12))

    assert candidate is not None
    assert candidate.candidate_id == "commons-12"
    assert candidate.author == "Example & Author"
    assert candidate.normalized_license_id == "CC0-1.0"
    assert candidate.license_evidence_url.startswith("https://")
    assert candidate.rights_review_status == "pending"
    assert candidate.commercial_use_confirmed is False
    assert candidate.redistribution_allowed_confirmed is False
    assert extract_candidate(_page(13, license_label="CC BY-SA 4.0")) is None
    assert extract_candidate(_page(14, mime_type="image/tiff")) is None
    assert extract_candidate(_page(15, width=399)) is None


def test_collection_follows_continuation_and_stops_at_limit() -> None:
    requested_urls: list[str] = []

    def fetch_json(url: str) -> dict[str, object]:
        requested_urls.append(url)
        continuation = parse_qs(urlparse(url).query).get("gcmcontinue")
        if continuation:
            return {"query": {"pages": [_page(3), _page(4)]}}
        return {
            "continue": {"gcmcontinue": "next", "continue": "gcmcontinue||"},
            "query": {"pages": [_page(1), _page(2, license_label="CC BY 4.0")]},
        }

    candidates = collect_candidates(2, fetch_json=fetch_json)

    assert [candidate.page_id for candidate in candidates] == [1, 3]
    assert len(requested_urls) == 2
    assert "gcmtitle=Category%3AFloor+plans+of+houses" in requested_urls[0]


def test_download_decodes_image_and_records_delivery_integrity(tmp_path: Path) -> None:
    image = np.full((32, 48, 3), 255, dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success
    content = encoded.tobytes()
    candidate = CommonsCandidate.model_validate(extract_candidate(_page(20)))

    downloaded = download_candidate(
        candidate,
        tmp_path,
        fetch_bytes=lambda _: content,
    )

    assert downloaded.download_file == "commons-20.png"
    assert downloaded.download_status == "downloaded"
    assert downloaded.download_bytes == len(content)
    assert downloaded.download_sha256 == hashlib.sha256(content).hexdigest()
    assert (tmp_path / downloaded.download_file).read_bytes() == content

    resumed = download_candidate(
        candidate,
        tmp_path,
        fetch_bytes=lambda _: (_ for _ in ()).throw(AssertionError("must resume")),
    )
    assert resumed.download_sha256 == downloaded.download_sha256

    contact_sheet = tmp_path / "contact-sheet.jpg"
    create_contact_sheet([downloaded], tmp_path, contact_sheet)
    rendered = cv2.imread(str(contact_sheet))
    assert rendered is not None
    assert rendered.shape[:2] == (260, 1280)


def test_download_retries_rate_limit_once(monkeypatch) -> None:
    attempts = 0
    sleeps: list[float] = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self, _: int) -> bytes:
            return b"candidate"

    def urlopen(*_: object, **__: object):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise urllib.error.HTTPError(
                "https://example.com/candidate.png",
                429,
                "Too many requests",
                {"Retry-After": "1"},
                None,
            )
        return Response()

    monkeypatch.setattr("app.recognition_candidates.urllib.request.urlopen", urlopen)
    monkeypatch.setattr("app.recognition_candidates.time.sleep", sleeps.append)

    assert _fetch_bytes("https://example.com/candidate.png") == b"candidate"
    assert attempts == 2
    assert sleeps == [1.0]
