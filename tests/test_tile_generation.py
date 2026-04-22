"""Tile URL + filename generation for each raw dataset."""
from __future__ import annotations

import re

import pytest

from backend.api import (
    tile_filename,
    tile_url,
    urls_for_bbox,
    urls_for_polygon,
)
from backend.downloader import MapDownloader, BAYERN_DATASETS


# -------- single-tile URL building ------------------------------------------

def test_dop20_single_tile_matches_repo_meta4():
    """The DOP20 tile URL we generate must match the known-good URLs that
    live in dop20rgb.meta4 — that's our only ground-truth example."""
    assert tile_url("dop20", 672, 5424) == \
        "https://download1.bayernwolke.de/a/dop20/data/32672_5424.tif"


def test_dop20_tile_filename():
    assert tile_filename("dop20", 672, 5424) == "32672_5424.tif"


def test_lod2_tile_has_no_prefix_and_gml_ext():
    """LoD2 is the user-confirmed 2 km / no-prefix / .gml dataset."""
    url = tile_url("lod2", 686, 5330)
    assert url == "https://download1.bayernwolke.de/a/lod2/citygml/686_5330.gml"
    assert tile_filename("lod2", 686, 5330) == "686_5330.gml"


def test_dgm5_tile_uses_2km_scheme():
    url = tile_url("dgm5", 686, 5330)
    assert url == "https://download1.bayernwolke.de/a/dgm/dgm5/686_5330.tif"
    assert tile_filename("dgm5", 686, 5330) == "686_5330.tif"


def test_dgm1_uses_dgm_subfolder():
    """DGM1 was reported broken with the old /a/dgm1/data/ layout.
    The metalink sits at /a/dgm/dgm1/... so tiles must too."""
    url = tile_url("dgm1", 672, 5424)
    assert url == "https://download1.bayernwolke.de/a/dgm/dgm1/32672_5424.tif"


def test_unknown_dataset_raises():
    with pytest.raises(KeyError):
        tile_url("unknown-dataset", 1, 1)


def test_wms_dataset_rejected_in_raw_builders():
    with pytest.raises(ValueError):
        tile_url("relief_wms", 1, 1)


def test_override_url_path_for_probing():
    url = tile_url("laser", 672, 5424, url_path_override="laser/data")
    assert url == "https://download1.bayernwolke.de/a/laser/data/32672_5424.laz"


# -------- polygon → tile list -----------------------------------------------

def test_polygon_generates_nonempty_dop20(munich_polygon_wkt):
    pairs = urls_for_polygon(munich_polygon_wkt, "dop20")
    assert len(pairs) > 0
    for fname, url in pairs:
        assert re.fullmatch(r"32\d{3}_\d{4}\.tif", fname), \
            f"DOP20 filenames must be 32XXX_YYYY.tif, got {fname!r}"
        assert url.startswith("https://download1.bayernwolke.de/a/dop20/data/")
        assert url.endswith(fname)


def test_polygon_generates_2km_lod2(munich_polygon_wkt):
    pairs = urls_for_polygon(munich_polygon_wkt, "lod2")
    # 2 km grid so the Munich ~2 km polygon lands on 1-4 tiles depending on edges.
    assert 1 <= len(pairs) <= 4, f"expected ~1-4 LoD2 tiles, got {len(pairs)}"
    for fname, url in pairs:
        assert fname.endswith(".gml")
        assert "/a/lod2/citygml/" in url


def test_bbox_and_polygon_agree(munich_polygon_wkt, munich_bbox):
    by_bbox = urls_for_bbox(*munich_bbox, dataset="dop20")
    by_poly = urls_for_polygon(munich_polygon_wkt, "dop20")
    assert set(by_bbox) == set(by_poly)


def test_ewkt_prefix_is_stripped(munich_polygon_ewkt):
    pairs = urls_for_polygon(munich_polygon_ewkt, "dop20")
    assert len(pairs) > 0


def test_polygon_way_outside_bayern_returns_empty():
    # New York, definitely not in Bayern.
    poly = "POLYGON((-74.0 40.7, -74.0 40.8, -73.9 40.8, -73.9 40.7, -74.0 40.7))"
    assert urls_for_polygon(poly, "dop20") == []


def test_bbox_order_validation():
    import pytest
    with pytest.raises(ValueError):
        urls_for_bbox(11.52, 48.12, 11.50, 48.10, dataset="dop20")


# -------- grid / prefix invariants across every raw dataset -----------------

@pytest.mark.parametrize("key,meta", [(k, v) for k, v in BAYERN_DATASETS.items() if v["kind"] == "raw"])
def test_tile_names_match_declared_prefix(key, meta, munich_polygon_wkt):
    pairs = MapDownloader().generate_1km_grid_files(munich_polygon_wkt, dataset=key)
    prefix = meta.get("tile_prefix", "32")
    ext = meta["ext"]
    for fname, _ in pairs:
        assert fname.endswith(ext), f"{key}: {fname!r} missing {ext}"
        stem = fname[:-len(ext)]
        assert stem.startswith(prefix), f"{key}: {fname!r} should start with {prefix!r}"


@pytest.mark.parametrize("key,meta", [(k, v) for k, v in BAYERN_DATASETS.items() if v["kind"] == "raw"])
def test_all_urls_target_download1(key, meta, munich_polygon_wkt):
    pairs = MapDownloader().generate_1km_grid_files(munich_polygon_wkt, dataset=key)
    for _, url in pairs:
        assert url.startswith("https://download1.bayernwolke.de/a/")


def test_grid_km_2_yields_fewer_tiles_than_grid_km_1(munich_polygon_wkt):
    """A polygon covers roughly (1km/2km)^2 = 1/4 as many 2 km tiles as 1 km tiles."""
    n_dop20 = len(urls_for_polygon(munich_polygon_wkt, "dop20"))   # 1 km
    n_lod2 = len(urls_for_polygon(munich_polygon_wkt, "lod2"))    # 2 km
    assert n_lod2 < n_dop20
