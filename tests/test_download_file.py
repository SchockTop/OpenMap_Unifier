"""download_file: mirror fallback, skip-if-exists, cancel — mocked over the network."""
from __future__ import annotations

import io
import os
from unittest.mock import MagicMock, patch

import pytest

from backend.downloader import MapDownloader


def _fake_response(status=200, body=b"DATA"):
    """Build a mock that looks like requests.Response for stream downloads."""
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"content-length": str(len(body))}
    resp.iter_content = MagicMock(return_value=iter([body]))
    if status >= 400:
        from requests import HTTPError
        resp.raise_for_status = MagicMock(side_effect=HTTPError(f"{status} Client Error"))
    else:
        resp.raise_for_status = MagicMock(return_value=None)
    return resp


def test_single_url_success(tmp_path):
    d = MapDownloader(download_dir=str(tmp_path))
    with patch("backend.downloader.requests.get", return_value=_fake_response(200, b"HELLO")):
        ok = d.download_file("https://example.com/a.tif", "a.tif")
    assert ok
    target = tmp_path / "a.tif"
    assert target.exists()
    assert target.read_bytes() == b"HELLO"


def test_skip_if_target_exists(tmp_path):
    (tmp_path / "a.tif").write_bytes(b"OLD")
    d = MapDownloader(download_dir=str(tmp_path))
    called = MagicMock()
    with patch("backend.downloader.requests.get", side_effect=called):
        ok = d.download_file("https://example.com/a.tif", "a.tif")
    assert ok is True
    assert called.call_count == 0
    # Content untouched.
    assert (tmp_path / "a.tif").read_bytes() == b"OLD"


def test_all_mirrors_fail_returns_false(tmp_path):
    d = MapDownloader(download_dir=str(tmp_path))
    responses = [_fake_response(404), _fake_response(503)]
    with patch("backend.downloader.requests.get", side_effect=responses):
        ok = d.download_file(
            ["https://mirror1.example/a.tif", "https://mirror2.example/a.tif"],
            "a.tif",
        )
    assert ok is False
    assert not (tmp_path / "a.tif").exists()
    assert not (tmp_path / "a.tif.part").exists()


def test_mirror_fallback_succeeds_when_second_mirror_works(tmp_path):
    """This is the exact scenario Bayern metalinks give us:
    download1 down, download2 up. The second mirror must complete."""
    d = MapDownloader(download_dir=str(tmp_path))
    responses = [_fake_response(404), _fake_response(200, b"PAYLOAD")]
    with patch("backend.downloader.requests.get", side_effect=responses):
        ok = d.download_file(
            ["https://mirror1.example/a.tif", "https://mirror2.example/a.tif"],
            "a.tif",
        )
    assert ok is True
    assert (tmp_path / "a.tif").read_bytes() == b"PAYLOAD"


def test_progress_callback_sees_each_mirror(tmp_path):
    d = MapDownloader(download_dir=str(tmp_path))
    seen = []
    def cb(fname, pct, status, speed, eta):
        seen.append(status)

    with patch(
        "backend.downloader.requests.get",
        side_effect=[_fake_response(404), _fake_response(200, b"OK")],
    ):
        d.download_file(
            ["https://mirror1.example/a.tif", "https://mirror2.example/a.tif"],
            "a.tif",
            progress_callback=cb,
        )

    # We expect at least a "Connecting... (mirror 1/2)", "Connecting... (mirror 2/2)"
    # and "Completed" somewhere in there. Exact wording can evolve; just check
    # that both mirrors were announced and completion landed.
    texts = " | ".join(seen)
    assert "mirror 1/2" in texts, texts
    assert "mirror 2/2" in texts, texts
    assert "Completed" in texts, texts


def test_cancel_stops_without_trying_more_mirrors(tmp_path):
    d = MapDownloader(download_dir=str(tmp_path))
    d.stop_event = True
    cb = MagicMock()
    with patch("backend.downloader.requests.get") as mock_get:
        ok = d.download_file(
            ["https://mirror1.example/a.tif", "https://mirror2.example/a.tif"],
            "a.tif",
            progress_callback=cb,
        )
    assert ok is False
    assert mock_get.call_count == 0, "Cancel before any attempt must not call requests"


def test_empty_url_list_returns_false(tmp_path):
    d = MapDownloader(download_dir=str(tmp_path))
    assert d.download_file([], "a.tif") is False
