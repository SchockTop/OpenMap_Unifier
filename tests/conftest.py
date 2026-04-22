"""Shared pytest fixtures and path wiring."""
from __future__ import annotations

import os
import sys

# Allow `import backend...` even when pytest is invoked from any cwd.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# A tiny polygon around Munich city centre in WGS84 — intersects every
# Bayern dataset we ship and stays entirely inside UTM zone 32N.
#     lon ~11.50-11.52, lat ~48.10-48.12   ->   easting ~686km, northing ~5330km
MUNICH_BBOX = (11.50, 48.10, 11.52, 48.12)
MUNICH_POLYGON_WKT = (
    "POLYGON((11.50 48.10, 11.52 48.10, 11.52 48.12, 11.50 48.12, 11.50 48.10))"
)
# Same polygon with an explicit SRID prefix (EWKT) — the code must strip that.
MUNICH_POLYGON_EWKT = "SRID=4326;" + MUNICH_POLYGON_WKT


import pytest


@pytest.fixture
def repo_root() -> str:
    return REPO_ROOT


@pytest.fixture
def munich_polygon_wkt() -> str:
    return MUNICH_POLYGON_WKT


@pytest.fixture
def munich_polygon_ewkt() -> str:
    return MUNICH_POLYGON_EWKT


@pytest.fixture
def munich_bbox() -> tuple[float, float, float, float]:
    return MUNICH_BBOX


@pytest.fixture
def dop20_meta4_path(repo_root) -> str:
    return os.path.join(repo_root, "dop20rgb.meta4")
