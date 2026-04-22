"""parse_metalink against the repo's own dop20rgb.meta4 — ground truth."""
from __future__ import annotations

import pytest

from backend.downloader import MapDownloader


def test_parses_repo_meta4(dop20_meta4_path):
    files = MapDownloader().parse_metalink(dop20_meta4_path)
    assert len(files) == 64, f"expected 64 files in dop20rgb.meta4, got {len(files)}"


def test_entries_have_filename_and_urls(dop20_meta4_path):
    files = MapDownloader().parse_metalink(dop20_meta4_path)
    for name, urls in files:
        assert name.endswith(".tif")
        assert isinstance(urls, list)
        assert len(urls) >= 1


def test_every_entry_has_two_mirrors(dop20_meta4_path):
    """Bayern's metalinks ship download1 + download2 — both must be captured.
    This is the regression we added mirror-fallback for."""
    files = MapDownloader().parse_metalink(dop20_meta4_path)
    for name, urls in files:
        assert len(urls) == 2, f"{name}: expected 2 mirrors, got {len(urls)}"
        hosts = {u.split("/")[2] for u in urls}
        assert hosts == {"download1.bayernwolke.de", "download2.bayernwolke.de"}, \
            f"{name}: unexpected mirror hosts {hosts}"


def test_first_entry_matches_known_url(dop20_meta4_path):
    files = MapDownloader().parse_metalink(dop20_meta4_path)
    first_name, first_urls = files[0]
    assert first_name == "32672_5424.tif"
    assert first_urls[0] == "https://download1.bayernwolke.de/a/dop20/data/32672_5424.tif"
    assert first_urls[1] == "https://download2.bayernwolke.de/a/dop20/data/32672_5424.tif"


def test_empty_or_missing_file_returns_empty(tmp_path):
    empty = tmp_path / "empty.meta4"
    empty.write_text('<?xml version="1.0"?><metalink xmlns="urn:ietf:params:xml:ns:metalink"/>')
    assert MapDownloader().parse_metalink(str(empty)) == []


def test_malformed_xml_returns_empty(tmp_path):
    bad = tmp_path / "bad.meta4"
    bad.write_text("not-xml")
    assert MapDownloader().parse_metalink(str(bad)) == []
