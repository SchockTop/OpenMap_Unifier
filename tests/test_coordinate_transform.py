"""Sanity checks on the WGS84 -> UTM 32N transform we rely on for tile math."""
from __future__ import annotations

from pyproj import Transformer


TO_25832 = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)


def test_munich_projects_into_expected_tile():
    """Munich centre (11.5°, 48.1°) -> ~(676000, 5334000) in EPSG:25832.

    This anchors every other tile-count assertion — if pyproj breaks or we
    swap the lon/lat order, this test falls over immediately.
    """
    x, y = TO_25832.transform(11.5, 48.1)
    assert 670_000 < x < 695_000, f"easting out of range: {x}"
    assert 5_325_000 < y < 5_340_000, f"northing out of range: {y}"


def test_transformer_always_xy_is_lon_lat():
    """A quick guard that nobody flipped the axis order in the transformer."""
    x1, y1 = TO_25832.transform(11.0, 48.0)
    x2, y2 = TO_25832.transform(12.0, 48.0)
    # Easting must increase when we move East (increasing longitude).
    assert x2 > x1
    x3, y3 = TO_25832.transform(11.0, 49.0)
    # Northing must increase when we move North (increasing latitude).
    assert y3 > y1
