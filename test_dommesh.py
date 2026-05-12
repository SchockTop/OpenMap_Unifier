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


def _tiny_submesh(node_id=42):
    return dommesh.SubMesh(
        node_id=node_id,
        verts=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],   # already V-flipped for OBJ/GLB
        tris=[(0, 1, 2)],
        jpeg=b"\xff\xd8\xff\xd9",                    # minimal JPEG SOI+EOI marker bytes
    )


def test_write_obj_emits_mtl_and_texture(tmp_path):
    dommesh.write_obj(str(tmp_path), [_tiny_submesh(7)], anchor=(690000.0, 5506000.0))
    obj = (tmp_path / "cutout.obj").read_text()
    assert obj.startswith("mtllib cutout.mtl")
    assert "o node_7" in obj
    assert "\nv 0.0000 0.0000 0.0000" in obj
    assert "\nvt 0.000000 0.000000" in obj
    assert "\nf 1/1 2/2 3/3" in obj            # 1-based indices
    mtl = (tmp_path / "cutout.mtl").read_text()
    assert "newmtl m7" in mtl and "map_Kd tex/node_7.jpg" in mtl
    assert (tmp_path / "tex" / "node_7.jpg").read_bytes() == b"\xff\xd8\xff\xd9"


def _parse_glb(data: bytes):
    magic, version, length = struct.unpack("<4sII", data[:12])
    assert magic == b"glTF" and version == 2 and length == len(data)
    p = 12
    chunks = []
    while p < len(data):
        clen, ctype = struct.unpack("<I4s", data[p:p + 8]); p += 8
        chunks.append((ctype, data[p:p + clen])); p += clen
    return chunks


def test_write_glb_structure_and_roundtrip(tmp_path):
    out = tmp_path / "cutout.glb"
    dommesh.write_glb(str(out), [_tiny_submesh(3), _tiny_submesh(4)],
                      anchor=(690000.0, 5506000.0))
    data = out.read_bytes()
    chunks = _parse_glb(data)
    assert chunks[0][0] == b"JSON"
    assert chunks[1][0] == b"BIN\x00"
    assert len(chunks[1][1]) % 4 == 0          # BIN chunk is 4-byte aligned
    gltf = json.loads(chunks[0][1])
    assert gltf["asset"]["version"] == "2.0"
    assert len(gltf["meshes"]) == 2 and len(gltf["nodes"]) == 2
    assert len(gltf["images"]) == 2 and len(gltf["materials"]) == 2
    assert len(gltf["scenes"]) == 1 and set(gltf["scenes"][0]["nodes"]) == {0, 1}
    # accessors: 3 per submesh (POSITION, TEXCOORD_0, indices) -> 6 total
    assert len(gltf["accessors"]) == 6
    # The embedded JPEG bytes survive: find an image bufferView and slice the BIN.
    bv = gltf["bufferViews"][gltf["images"][0]["bufferView"]]
    blob = chunks[1][1][bv["byteOffset"]:bv["byteOffset"] + bv["byteLength"]]
    assert blob == b"\xff\xd8\xff\xd9"


def test_write_glb_maps_to_yup():
    # POSITION in glTF must be (easting, height, -northing); verts here are
    # already anchor-relative, so vert (1, 2, 3) -> (1, 3, -2).
    sm = dommesh.SubMesh(node_id=1, verts=[(1.0, 2.0, 3.0), (0, 0, 0), (0, 0, 0)],
                         uvs=[(0, 0)] * 3, tris=[(0, 1, 2)], jpeg=b"\xff\xd8\xff\xd9")
    import tempfile, os as _os
    path = _os.path.join(tempfile.mkdtemp(), "g.glb")
    dommesh.write_glb(path, [sm], anchor=(0.0, 0.0))
    chunks = _parse_glb(open(path, "rb").read())
    gltf = json.loads(chunks[0][1])
    pos_acc = gltf["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
    acc = gltf["accessors"][pos_acc]
    bv = gltf["bufferViews"][acc["bufferView"]]
    raw = chunks[1][1][bv["byteOffset"]:bv["byteOffset"] + bv["byteLength"]]
    first = struct.unpack("<fff", raw[:12])
    assert first == pytest.approx((1.0, 3.0, -2.0))
    # accessor min/max present (glTF validators require it for POSITION).
    assert "min" in acc and "max" in acc


_FAKE_LOS_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
 <Placemark><name>111111_0</name><Polygon><outerBoundaryIs><LinearRing>
   <coordinates>11.50,49.60,0 11.70,49.60,0 11.70,49.80,0 11.50,49.80,0 11.50,49.60,0</coordinates>
 </LinearRing></outerBoundaryIs></Polygon></Placemark>
 <Placemark><name>222222_0</name><Polygon><outerBoundaryIs><LinearRing>
   <coordinates>12.00,50.00,0 12.10,50.00,0 12.10,50.10,0 12.00,50.10,0 12.00,50.00,0</coordinates>
 </LinearRing></outerBoundaryIs></Polygon></Placemark>
</Document></kml>"""


def test_los_index_point_in_polygon(tmp_path):
    kml_path = tmp_path / "los.kml"
    kml_path.write_text(_FAKE_LOS_KML)
    idx = dommesh.LosIndex(cached_kml_path=str(kml_path))
    # A point near (11.6, 49.7) -> EPSG:25832 roughly (690k, 5506k). Use the
    # transformer to find a coordinate inside the first polygon.
    from pyproj import Transformer
    e, n = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True).transform(11.6, 49.7)
    assert idx.los_ids_for_point(e, n) == ["111111_0"]
    e2, n2 = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True).transform(11.6, 60.0)
    assert idx.los_ids_for_point(e2, n2) == []
