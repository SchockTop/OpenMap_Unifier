"""End-to-end smoke tests for backend.api (the thing external callers hit)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from backend import api


def test_list_datasets_returns_catalog_copy():
    everything = api.list_datasets()
    assert "dop20" in everything
    assert everything["dop20"]["ext"] == ".tif"
    # Mutating the returned dict must not affect the catalog.
    everything["dop20"]["ext"] = ".xyz"
    again = api.list_datasets()
    assert again["dop20"]["ext"] == ".tif"


def test_list_datasets_filter_by_category():
    only_height = api.list_datasets(category="height")
    assert set(only_height) == {"dgm1", "dgm5"}


def test_list_datasets_filter_by_kind():
    raw_only = api.list_datasets(kind="raw")
    assert "lod2" in raw_only
    assert "relief_wms" not in raw_only


def test_urls_for_bbox_munich_dop20(munich_bbox):
    pairs = api.urls_for_bbox(*munich_bbox, dataset="dop20")
    assert len(pairs) > 0
    names = {n for n, _ in pairs}
    assert "32686_5330.tif" in names


def test_urls_for_polygon_lod2(munich_polygon_wkt):
    pairs = api.urls_for_polygon(munich_polygon_wkt, "lod2")
    assert all(url.startswith("https://download1.bayernwolke.de/a/lod2/citygml/") for _, url in pairs)


def test_probe_honours_injected_proxy_manager(munich_bbox):
    """probe_dataset should drive the mocked session, not create its own."""
    session = MagicMock()
    session.head.return_value = MagicMock(status_code=200, reason="OK")
    pm = MagicMock()
    pm.get_session.return_value = session

    results = api.probe_dataset("dgm1", 672, 5424, proxy_manager=pm)
    assert len(results) >= 1
    # First candidate = current url_path.
    assert results[0]["ok"] is True
    assert results[0]["status"] == 200
    # The mock must have actually been called.
    assert session.head.call_count == len(results)


def test_probe_reports_failures(munich_bbox):
    session = MagicMock()
    session.head.return_value = MagicMock(status_code=404, reason="Not Found")
    pm = MagicMock()
    pm.get_session.return_value = session

    results = api.probe_dataset("laser", 672, 5424, proxy_manager=pm)
    assert all(r["ok"] is False for r in results)
    assert all(r["status"] == 404 for r in results)


def test_probe_first_ok_wins(munich_bbox):
    """Confirm we don't short-circuit the probe — every candidate is tested,
    so the user sees the full picture even after finding a winner."""
    session = MagicMock()
    # Return alternating 404 / 200 so different candidates land on different sides.
    session.head.side_effect = [
        MagicMock(status_code=404, reason="Not Found"),
        MagicMock(status_code=200, reason="OK"),
        MagicMock(status_code=404, reason="Not Found"),
        MagicMock(status_code=404, reason="Not Found"),
    ]
    pm = MagicMock()
    pm.get_session.return_value = session

    results = api.probe_dataset(
        "dgm1", 672, 5424,
        candidates=["dgm/dgm1", "dgm1/data", "dgm1/tiff", "dgm1"],
        proxy_manager=pm,
    )
    statuses = [r["status"] for r in results]
    assert statuses == [404, 200, 404, 404]
    assert [r["ok"] for r in results] == [False, True, False, False]


def test_download_tiles_rejects_both_polygon_and_bbox():
    with pytest.raises(ValueError):
        api.download_tiles("dop20", polygon_wkt="POLYGON((0 0,1 0,1 1,0 1,0 0))",
                           bbox=(0, 0, 1, 1))


def test_download_tiles_rejects_neither():
    with pytest.raises(ValueError):
        api.download_tiles("dop20")


def test_download_tiles_end_to_end(tmp_path, munich_bbox):
    """Drive download_tiles through a mocked network. Every tile succeeds."""
    def fake_get(url, *a, **kw):
        r = MagicMock()
        r.status_code = 200
        r.headers = {"content-length": "5"}
        r.iter_content = MagicMock(return_value=iter([b"HELLO"]))
        r.raise_for_status = MagicMock(return_value=None)
        return r

    with patch("backend.downloader.requests.get", side_effect=fake_get):
        result = api.download_tiles(
            "dop20",
            bbox=munich_bbox,
            out_dir=str(tmp_path / "dop20"),
        )
    assert result["requested"] > 0
    assert result["failed"] == []
    assert result["ok"] == result["requested"]


# -------- CLI smoke tests ---------------------------------------------------

def test_cli_tile_prints_url(capsys):
    rc = api.main(["tile", "--dataset", "dop20", "--east", "672", "--north", "5424"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out == "https://download1.bayernwolke.de/a/dop20/data/32672_5424.tif"


def test_cli_list_valid_json(capsys):
    rc = api.main(["list", "--kind", "raw"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert rc == 0
    assert "dop20" in data
    assert "relief_wms" not in data
