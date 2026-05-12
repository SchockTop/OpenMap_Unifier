"""Unit tests for backend/dommesh.py — DOM-Mesh SLPK cutout.

Pure-Python pieces are fully tested without network. The one network test is
marked `needs_network` and skipped unless the DOMMESH_LIVE env var is set
(see conftest.py).
"""
from __future__ import annotations

import io
import json
import struct
import zipfile
from pathlib import Path

import pytest

from backend import dommesh


def _build_zip64(names_and_blobs):
    """Build an in-memory ZIP and return (bytes, {name: stored_size}).

    `allowZip64=True` only *permits* ZIP64 extensions; for small test blobs
    Python writes a plain EOCD (PK\\x05\\x06), so the ZIP64-EOCD branch of
    `parse_central_directory` is NOT exercised here. That path is covered by
    the live `needs_network` test added in a later task.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
        for name, blob in names_and_blobs:
            zf.writestr(name, blob)
    return buf.getvalue(), {n: len(b) for n, b in names_and_blobs}


def test_parse_central_directory_returns_offsets_and_sizes():
    raw, sizes = _build_zip64([
        ("3dSceneLayer.json.gz", b"\x1f\x8b" + b"x" * 50),
        ("nodes/0/geometries/0.bin.gz", b"\x1f\x8b" + b"y" * 120),
    ])
    entries = dommesh.parse_central_directory(raw)
    assert set(entries) == {"3dSceneLayer.json.gz", "nodes/0/geometries/0.bin.gz"}
    for name, (offset, csize, usize, method) in entries.items():
        assert csize == sizes[name]
        assert method == 0  # ZIP_STORED
        # The local file header at `offset` starts with the PK\x03\x04 signature.
        assert raw[offset:offset + 4] == b"PK\x03\x04"


def test_decode_geometry_reads_positions_and_uvs():
    verts = [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)]
    uvs = [(0.1, 0.2), (0.3, 0.4), (0.5, 0.6)]
    blob = struct.pack("<II", len(verts), 1)
    for x, y, z in verts:
        blob += struct.pack("<fff", x, y, z)
    for u, v in uvs:
        blob += struct.pack("<ff", u, v)
    vcount, pos, uv = dommesh.decode_geometry(blob)
    assert vcount == 3
    assert pos == pytest.approx([c for vtx in verts for c in vtx])
    assert uv == pytest.approx([c for t in uvs for c in t])


def test_polygon_from_ewkt_projects_to_utm32():
    # A small square near Auerbach i.d.OPf. roughly (lon 11.6, lat 49.7).
    ewkt = ("SRID=4326;POLYGON((11.60 49.70, 11.61 49.70, 11.61 49.71, "
            "11.60 49.71, 11.60 49.70))")
    poly = dommesh.polygon_from_ewkt(ewkt)
    minx, miny, maxx, maxy = poly.bounds
    # EPSG:25832 easting in the 690 km range, northing ~5.5 Mm.
    assert 680_000 < minx < 700_000
    assert 5_500_000 < miny < 5_520_000
    assert maxx > minx and maxy > miny


def test_polygon_from_ewkt_drops_z():
    ewkt = "SRID=4326;POLYGON Z((11.6 49.7 0, 11.61 49.7 0, 11.61 49.71 0, 11.6 49.7 0))"
    poly = dommesh.polygon_from_ewkt(ewkt)
    assert poly.is_valid


def test_aabb_overlaps_bbox():
    node = {"cx": 100.0, "cy": 200.0, "hx": 10.0, "hy": 10.0}
    assert dommesh.aabb_overlaps(node, (95, 195, 105, 205))
    assert dommesh.aabb_overlaps(node, (90, 190, 95, 195))      # touching corner
    assert not dommesh.aabb_overlaps(node, (200, 200, 300, 300))


def test_clip_triangles_to_polygon_keeps_inside_centroids():
    from shapely.geometry import Polygon
    square = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    # vertices: world (x, y, z), one triangle inside, one outside.
    wx = [1, 2, 1,   100, 101, 100]
    wy = [1, 1, 2,   100, 100, 101]
    wz = [0, 0, 0,   0, 0, 0]
    uv = [0.0] * 12
    tris, used, remap = dommesh.clip_triangles(wx, wy, square)
    assert tris == [(0, 1, 2)]
    assert used == [0, 1, 2]
    assert remap == {0: 0, 1: 1, 2: 2}
