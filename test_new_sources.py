"""Tests for the newly added map sources: DOP20 CIR (infrared WMS), Sentinel-2
(satellite + SWIR), and ESA WorldCover (land cover).

Offline tests run always. Live-download tests are marked ``needs_network`` and
only run when DOMMESH_LIVE is set (same convention as the rest of the repo).
"""
import os

import pytest

from backend.downloader import MapDownloader, BAYERN_DATASETS, BAYERN_CATEGORY_LABELS
from backend.sentinel2_downloader import (
    Sentinel2Downloader, polygon_bbox_4326, INDEX_FORMULAS, DEFAULT_BANDS,
)
from backend.worldcover_downloader import (
    WorldCoverDownloader, tile_name_for, tile_url, WORLDCOVER_CLASSES,
)

WKT = "POLYGON((11.55 48.12, 11.57 48.12, 11.57 48.14, 11.55 48.14, 11.55 48.12))"


# --------------------------------------------------------------- CIR (infrared)
def test_cir_in_catalog():
    assert "dop20cir_wms" in BAYERN_DATASETS
    cir = BAYERN_DATASETS["dop20cir_wms"]
    assert cir["kind"] == "wms"
    assert cir["category"] == "infrared"
    assert cir["layer"] == "by_dop20cir"
    assert "infrared" in BAYERN_CATEGORY_LABELS


def test_generate_wms_tiles_cir_url():
    dl = MapDownloader(download_dir="/tmp/omu_t")
    tiles = dl.generate_wms_tiles(WKT, "dop20cir_wms")
    assert tiles, "CIR should intersect tiles"
    fname, url = tiles[0]
    assert fname.startswith("by_dop20cir_") and fname.endswith(".tiff")
    assert "layers=by_dop20cir" in url and "request=GetMap" in url
    assert "srs=EPSG:25832" in url and "BBOX=" in url


def test_generate_wms_tiles_catalog_driven_regression():
    """relief_wms and dop40_wms still generate via the new catalog-driven path."""
    dl = MapDownloader(download_dir="/tmp/omu_t")
    for key in ("relief_wms", "dop40_wms"):
        tiles = dl.generate_wms_tiles(WKT, key)
        assert tiles, f"{key} should still generate tiles"
        assert BAYERN_DATASETS[key]["layer"] in tiles[0][1]


def test_generate_wms_tiles_rejects_raw():
    dl = MapDownloader(download_dir="/tmp/omu_t")
    assert dl.generate_wms_tiles(WKT, "dgm1") == []  # dgm1 is raw, not wms


# ---------------------------------------------------------------- Sentinel-2
def test_polygon_bbox_4326():
    minx, miny, maxx, maxy = polygon_bbox_4326(WKT)
    assert round(minx, 2) == 11.55 and round(maxy, 2) == 48.14


def test_index_registry():
    assert set(DEFAULT_BANDS) >= {"red", "nir", "swir16", "swir22"}
    for k in ("ndvi", "ndbi", "mndwi", "nbr", "ndmi"):
        assert k in INDEX_FORMULAS
    # SWIR-only indices reference a swir band
    assert "swir16" in INDEX_FORMULAS["ndbi"]


# ---------------------------------------------------------------- WorldCover
def test_worldcover_tile_naming():
    assert tile_name_for(48.13, 11.56) == "N48E009"
    assert tile_name_for(48.13, 12.0) == "N48E012"
    assert tile_url(48.13, 11.56).endswith("N48E009_Map.tif")


def test_worldcover_class_table():
    assert WORLDCOVER_CLASSES[10] == "tree_cover"
    assert WORLDCOVER_CLASSES[50] == "built_up"
    assert WORLDCOVER_CLASSES[80] == "permanent_water"


# ---------------------------------------------------------------- live (gated)
@pytest.mark.needs_network
def test_cir_download_live():
    dl = MapDownloader(download_dir="/tmp/omu_cir_live")
    tiles = dl.generate_wms_tiles(WKT, "dop20cir_wms")
    fname, url = tiles[0]
    assert dl.download_file(url, fname)
    path = os.path.join("/tmp/omu_cir_live", fname)
    assert os.path.getsize(path) > 10000
    assert open(path, "rb").read(2) in (b"II", b"MM")  # TIFF magic


@pytest.mark.needs_network
def test_sentinel2_search_and_swir_live():
    s2 = Sentinel2Downloader(download_dir="/tmp/omu_s2_live")
    items = s2.search(WKT, max_cloud=30, limit=3)
    assert items, "expected >=1 Sentinel-2 scene"
    assert "swir16" in items[0]["assets"] and "swir22" in items[0]["assets"]
    bands = s2.download_bands(items[0], WKT, bands=("red", "nir", "swir16"), max_size=128)
    assert {"red", "nir", "swir16"} <= set(bands)


@pytest.mark.needs_network
def test_worldcover_fetch_live():
    wc = WorldCoverDownloader(download_dir="/tmp/omu_wc_live")
    path = wc.fetch(WKT, max_size=128)
    assert os.path.exists(path)
    hist = wc.class_histogram(path)
    assert hist and all(isinstance(v, int) for v in hist.values())
