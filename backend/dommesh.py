"""DOM-Mesh (Bayern, pn=dommesh) polygon cutout.

Given a Google Earth KML polygon (EWKT, WGS84), pick the flight-day "Los",
HTTP-Range-read only the I3S leaf nodes of that Los's DSM_Mesh.slpk that
overlap the polygon, decode the uncompressed I3S triangle geometry + JPEG
textures, clip to the polygon, and write a Blender-ready OBJ and/or GLB.

Proven facts (see experiments/dommesh_cutout/README.md):
- SLPK = ZIP64 of I3S 1.9 meshpyramids; download{1,2}.bayernwolke.de honour
  HTTP Range (206 Partial Content).
- OBB centers/halfSizes are in EPSG:25832, identity quaternions -> AOI filter
  is a 2D AABB test.
- Geometry nodes/<res>/geometries/0.bin.gz: u32 vertexCount + u32 featureCount,
  then positions f32x3 (relative to OBB center), then uv0 f32x2; triangle soup.
- Texture nodes/<res>/textures/0.jpg: plain JPEG, UV in [0,1] (flip V for OBJ).
"""
from __future__ import annotations

import gzip
import json
import math
import os
import struct
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

LOS_INDEX_KML_URL = (
    "https://geodaten.bayern.de/odd/m/3/daten/DOMMesh/DOM_Mesh_projektgebiete_2026.kml"
)
SLPK_MIRRORS = ("https://download1.bayernwolke.de", "https://download2.bayernwolke.de")


# --------------------------------------------------------------------------- #
# ZIP64 central directory                                                      #
# --------------------------------------------------------------------------- #
_EOCD64_LOCATOR_SIG = b"PK\x06\x07"
_EOCD64_SIG = b"PK\x06\x06"
_EOCD_SIG = b"PK\x05\x06"
_CD_SIG = b"PK\x01\x02"


def parse_central_directory(raw: bytes) -> dict[str, tuple[int, int, int, int]]:
    """Parse a (ZIP64) central directory blob -> {name: (local_offset, csize, usize, method)}.

    `raw` must contain at least the central directory and the end-of-central-
    directory records (i.e. the tail of the archive). Offsets are absolute into
    the original archive, so when you only fetched the tail you must pass the
    tail's start offset to the caller — here we assume `raw` is the whole file
    OR the caller has already aligned offsets (SlpkReader passes the tail and
    fixes offsets itself; tests pass the whole file).
    """
    # Find the (ZIP64) EOCD locator near the end.
    loc = raw.rfind(_EOCD64_LOCATOR_SIG)
    if loc != -1:
        # The locator gives the absolute byte offset of the EOCD64 record
        # directly; no need to scan for the PK\x06\x06 signature. This works
        # because raw is the whole archive (a tail-aware variant comes later).
        rec = struct.unpack("<Q", raw[loc + 8:loc + 16])[0]
        cd_size = struct.unpack("<Q", raw[rec + 40:rec + 48])[0]
        cd_off = struct.unpack("<Q", raw[rec + 48:rec + 56])[0]
    else:
        e = raw.rfind(_EOCD_SIG)
        cd_size = struct.unpack("<I", raw[e + 12:e + 16])[0]
        cd_off = struct.unpack("<I", raw[e + 16:e + 20])[0]
    # The central directory lives at cd_off..cd_off+cd_size within `raw`.
    cd = raw[cd_off:cd_off + cd_size]
    return _parse_cd_records(cd)


def _parse_cd_records(cd: bytes) -> dict[str, tuple[int, int, int, int]]:
    out: dict[str, tuple[int, int, int, int]] = {}
    p = 0
    while p + 4 <= len(cd) and cd[p:p + 4] == _CD_SIG:
        method = struct.unpack("<H", cd[p + 10:p + 12])[0]
        csize = struct.unpack("<I", cd[p + 20:p + 24])[0]
        usize = struct.unpack("<I", cd[p + 24:p + 28])[0]
        fnlen = struct.unpack("<H", cd[p + 28:p + 30])[0]
        eflen = struct.unpack("<H", cd[p + 30:p + 32])[0]
        cmlen = struct.unpack("<H", cd[p + 32:p + 34])[0]
        lho = struct.unpack("<I", cd[p + 42:p + 46])[0]
        name = cd[p + 46:p + 46 + fnlen].decode("utf-8", "replace")
        extra = cd[p + 46 + fnlen:p + 46 + fnlen + eflen]
        # ZIP64 extra field (id 0x0001): replaces 0xFFFFFFFF placeholders, in
        # the fixed order usize, csize, local-header-offset (only those that
        # were 0xFFFFFFFF are present).
        if (csize == 0xFFFFFFFF or usize == 0xFFFFFFFF or lho == 0xFFFFFFFF) and extra:
            q = 0
            while q + 4 <= len(extra):
                hid, hsz = struct.unpack("<HH", extra[q:q + 4])
                if hid == 0x0001:
                    vals = extra[q + 4:q + 4 + hsz]
                    vi = 0
                    if usize == 0xFFFFFFFF:
                        usize = struct.unpack("<Q", vals[vi:vi + 8])[0]; vi += 8
                    if csize == 0xFFFFFFFF:
                        csize = struct.unpack("<Q", vals[vi:vi + 8])[0]; vi += 8
                    if lho == 0xFFFFFFFF:
                        lho = struct.unpack("<Q", vals[vi:vi + 8])[0]; vi += 8
                    break
                q += 4 + hsz
        out[name] = (lho, csize, usize, method)
        p += 46 + fnlen + eflen + cmlen
    return out


# --------------------------------------------------------------------------- #
# I3S geometry decode                                                          #
# --------------------------------------------------------------------------- #
def decode_geometry(blob: bytes) -> tuple[int, list[float], list[float]]:
    """I3S meshpyramids PerAttributeArray, ordering [position(f32x3), uv0(f32x2)].

    Returns (vertex_count, flat_positions, flat_uvs). Non-indexed triangle soup
    -> vertex_count is a multiple of 3 (triangle i = vertices 3i, 3i+1, 3i+2).
    """
    vcount, _fcount = struct.unpack("<II", blob[:8])
    p = 8
    pos = list(struct.unpack("<%df" % (vcount * 3), blob[p:p + vcount * 12]))
    p += vcount * 12
    uv = list(struct.unpack("<%df" % (vcount * 2), blob[p:p + vcount * 8]))
    return vcount, pos, uv


# --------------------------------------------------------------------------- #
# AOI math                                                                     #
# --------------------------------------------------------------------------- #
def polygon_from_ewkt(ewkt: str):
    """Parse `[SRID=4326;]POLYGON((...))` (WGS84, possibly with Z) and return a
    shapely Polygon in EPSG:25832 (X=easting, Y=northing, Z dropped)."""
    from shapely.wkt import loads as _wkt_loads
    from shapely.geometry import Polygon
    from pyproj import Transformer

    if ";" in ewkt:
        ewkt = ewkt.split(";", 1)[1]
    poly = _wkt_loads(ewkt)
    tf = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
    # Index c[0]/c[1] so POLYGON Z(...) (Google Earth always adds altitude)
    # survives — we work purely in 2D on the UTM grid.
    return Polygon([tf.transform(c[0], c[1]) for c in poly.exterior.coords])


def aabb_overlaps(node: dict, bbox: tuple[float, float, float, float]) -> bool:
    """2D AABB-vs-AABB overlap (inclusive). `node` has cx,cy,hx,hy; bbox is
    (minx, miny, maxx, maxy)."""
    return (node["cx"] + node["hx"] >= bbox[0] and node["cx"] - node["hx"] <= bbox[2]
            and node["cy"] + node["hy"] >= bbox[1] and node["cy"] - node["hy"] <= bbox[3])


def clip_triangles(wx: list[float], wy: list[float], polygon):
    """Keep triangles (consecutive vertex triples) whose centroid lies inside
    `polygon` (shapely). Returns (tris, used_vertices, remap) where tris is a
    list of (i0,i1,i2) original indices, used_vertices is the sorted unique set,
    and remap maps original index -> compact index."""
    from shapely.geometry import Point

    tris: list[tuple[int, int, int]] = []
    for ti in range(len(wx) // 3):
        i0, i1, i2 = 3 * ti, 3 * ti + 1, 3 * ti + 2
        cx = (wx[i0] + wx[i1] + wx[i2]) / 3.0
        cy = (wy[i0] + wy[i1] + wy[i2]) / 3.0
        if polygon.covers(Point(cx, cy)):
            tris.append((i0, i1, i2))
    used = sorted({v for t in tris for v in t})
    remap = {v: n for n, v in enumerate(used)}
    return tris, used, remap


# --------------------------------------------------------------------------- #
# Output: SubMesh + OBJ writer                                                 #
# --------------------------------------------------------------------------- #
@dataclass
class SubMesh:
    """One I3S leaf node's surviving geometry, ready to serialise.

    `verts` are anchor-relative EPSG:25832 (x=easting-anchorx, y=northing-anchory,
    z=height). `uvs` are already V-flipped (i.e. OBJ/GLB convention, origin
    bottom-left). `tris` index into `verts`. `jpeg` is the raw texture file.
    """
    node_id: int
    verts: list[tuple[float, float, float]]
    uvs: list[tuple[float, float]]
    tris: list[tuple[int, int, int]]
    jpeg: bytes


def write_obj(out_dir: str, submeshes: list[SubMesh], anchor: tuple[float, float]) -> None:
    """Write cutout.obj + cutout.mtl + tex/node_<id>.jpg. `anchor` is only
    recorded indirectly (verts are already anchor-relative); it is unused here
    but kept in the signature for symmetry with write_glb / meta.json."""
    tex_dir = os.path.join(out_dir, "tex")
    os.makedirs(tex_dir, exist_ok=True)
    obj = ["mtllib cutout.mtl"]
    mtl: list[str] = []
    vbase = 0
    for sm in submeshes:
        texname = f"node_{sm.node_id}.jpg"
        with open(os.path.join(tex_dir, texname), "wb") as fh:
            fh.write(sm.jpeg)
        mname = f"m{sm.node_id}"
        mtl += [f"newmtl {mname}", "Ka 1 1 1", "Kd 1 1 1", "d 1", "illum 1",
                f"map_Kd tex/{texname}", ""]
        obj.append(f"o node_{sm.node_id}")
        for x, y, z in sm.verts:
            obj.append("v %.4f %.4f %.4f" % (x, y, z))
        for u, v in sm.uvs:
            obj.append("vt %.6f %.6f" % (u, v))
        obj.append(f"usemtl {mname}")
        for a, b, c in sm.tris:
            ia, ib, ic = vbase + a + 1, vbase + b + 1, vbase + c + 1
            obj.append(f"f {ia}/{ia} {ib}/{ib} {ic}/{ic}")
        vbase += len(sm.verts)
    with open(os.path.join(out_dir, "cutout.obj"), "w") as fh:
        fh.write("\n".join(obj) + "\n")
    with open(os.path.join(out_dir, "cutout.mtl"), "w") as fh:
        fh.write("\n".join(mtl) + "\n")


# --------------------------------------------------------------------------- #
# Output: GLB writer (binary glTF 2.0)                                         #
# --------------------------------------------------------------------------- #
def _pad4(b: bytes, fill: bytes = b"\x00") -> bytes:
    return b + fill * ((4 - len(b) % 4) % 4)


def write_glb(out_path: str, submeshes: list[SubMesh], anchor: tuple[float, float]) -> None:
    """Write a single binary glTF 2.0 file. One mesh/material/image/node per
    submesh. POSITION is (easting, height, -northing) so the model is Y-up like
    every other glTF (Blender's importer applies its own Z-up correction)."""
    bin_parts: list[bytes] = []
    bin_len = 0
    buffer_views: list[dict] = []
    accessors: list[dict] = []
    images: list[dict] = []
    samplers = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]
    textures: list[dict] = []
    materials: list[dict] = []
    meshes: list[dict] = []
    nodes: list[dict] = []

    def add_view(blob: bytes, target: Optional[int] = None) -> int:
        nonlocal bin_len
        blob = _pad4(blob)
        bv = {"buffer": 0, "byteOffset": bin_len, "byteLength": len(blob)}
        if target is not None:
            bv["target"] = target
        buffer_views.append(bv)
        bin_parts.append(blob)
        bin_len += len(blob)
        return len(buffer_views) - 1

    for sm in submeshes:
        # ---- index buffer (u32) ----
        idx = b"".join(struct.pack("<III", a, b, c) for a, b, c in sm.tris)
        idx_bv = add_view(idx, target=34963)  # ELEMENT_ARRAY_BUFFER
        idx_count = len(sm.tris) * 3
        accessors.append({"bufferView": idx_bv, "componentType": 5125,  # UNSIGNED_INT
                          "count": idx_count, "type": "SCALAR"})
        idx_acc = len(accessors) - 1
        # ---- POSITION (f32x3, Y-up) ----
        ys = [(e, z, -n) for (e, n, z) in sm.verts]
        pos = b"".join(struct.pack("<fff", *v) for v in ys)
        pos_bv = add_view(pos, target=34962)  # ARRAY_BUFFER
        mins = [min(c[i] for c in ys) for i in range(3)]
        maxs = [max(c[i] for c in ys) for i in range(3)]
        accessors.append({"bufferView": pos_bv, "componentType": 5126,  # FLOAT
                          "count": len(ys), "type": "VEC3", "min": mins, "max": maxs})
        pos_acc = len(accessors) - 1
        # ---- TEXCOORD_0 (f32x2) ----
        uvb = b"".join(struct.pack("<ff", u, v) for u, v in sm.uvs)
        uv_bv = add_view(uvb, target=34962)
        accessors.append({"bufferView": uv_bv, "componentType": 5126,
                          "count": len(sm.uvs), "type": "VEC2"})
        uv_acc = len(accessors) - 1
        # ---- texture image ----
        img_bv = add_view(sm.jpeg)
        images.append({"bufferView": img_bv, "mimeType": "image/jpeg",
                       "name": f"node_{sm.node_id}"})
        textures.append({"sampler": 0, "source": len(images) - 1})
        materials.append({"name": f"m{sm.node_id}", "doubleSided": True,
                          "pbrMetallicRoughness": {
                              "baseColorTexture": {"index": len(textures) - 1},
                              "metallicFactor": 0.0, "roughnessFactor": 1.0}})
        meshes.append({"name": f"node_{sm.node_id}", "primitives": [{
            "attributes": {"POSITION": pos_acc, "TEXCOORD_0": uv_acc},
            "indices": idx_acc, "material": len(materials) - 1, "mode": 4}]})
        nodes.append({"name": f"node_{sm.node_id}", "mesh": len(meshes) - 1})

    bin_blob = _pad4(b"".join(bin_parts))
    gltf = {
        "asset": {"version": "2.0", "generator": "OpenMap_Unifier dommesh"},
        "extras": {"anchor_epsg25832": list(anchor)},
        "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes, "meshes": meshes,
        "materials": materials, "textures": textures, "images": images,
        "samplers": samplers, "accessors": accessors, "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(bin_blob)}],
    }
    json_blob = _pad4(json.dumps(gltf, separators=(",", ":")).encode("utf-8"), b" ")
    total = 12 + 8 + len(json_blob) + 8 + len(bin_blob)
    with open(out_path, "wb") as fh:
        fh.write(struct.pack("<4sII", b"glTF", 2, total))
        fh.write(struct.pack("<I4s", len(json_blob), b"JSON")); fh.write(json_blob)
        fh.write(struct.pack("<I4s", len(bin_blob), b"BIN\x00")); fh.write(bin_blob)


# --------------------------------------------------------------------------- #
# LosIndex — which flight-day Los covers a point                               #
# --------------------------------------------------------------------------- #
def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "OpenMap_Unifier/dommesh"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


class LosIndex:
    """The DOM-Mesh project-areas KML, parsed into (los_id, shapely-Polygon-in-25832).

    Pass `cached_kml_path` to load a local copy (and to cache a downloaded one);
    if it doesn't exist and `download=True`, the KML is fetched once from
    LOS_INDEX_KML_URL and written there.
    """
    def __init__(self, cached_kml_path: Optional[str] = None, download: bool = False):
        if cached_kml_path and os.path.exists(cached_kml_path):
            raw = Path(cached_kml_path).read_bytes()
        elif download:
            raw = _http_get(LOS_INDEX_KML_URL)
            if cached_kml_path:
                os.makedirs(os.path.dirname(cached_kml_path) or ".", exist_ok=True)
                Path(cached_kml_path).write_bytes(raw)
        else:
            raise FileNotFoundError(
                "Los index KML not available locally and download=False")
        self._polys = self._parse(raw)

    @staticmethod
    def _parse(raw: bytes):
        from shapely.geometry import Polygon
        from pyproj import Transformer
        tf = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
        root = ET.fromstring(raw)
        out = []
        for pm in (e for e in root.iter() if e.tag.endswith("Placemark")):
            name = next((c.text.strip() for c in pm.iter()
                         if c.tag.endswith("name") and c.text), None)
            coords_text = next((c.text.strip() for c in pm.iter()
                                if c.tag.endswith("coordinates") and c.text), None)
            if not name or not coords_text:
                continue
            pts = []
            for token in coords_text.split():
                parts = token.split(",")
                if len(parts) >= 2:
                    pts.append(tf.transform(float(parts[0]), float(parts[1])))
            if len(pts) >= 3:
                out.append((name, Polygon(pts)))
        return out

    def los_ids_for_point(self, easting: float, northing: float) -> list[str]:
        from shapely.geometry import Point
        p = Point(easting, northing)
        return [name for name, poly in self._polys if poly.covers(p)]


# --------------------------------------------------------------------------- #
# SlpkReader — HTTP-Range reader for a per-Los DSM_Mesh.slpk                    #
# --------------------------------------------------------------------------- #
def _payload_offset(local_header: bytes, local_offset: int) -> int:
    """Given the first >=30 bytes of a ZIP local file header located at
    `local_offset`, return the absolute offset of the stored payload."""
    assert local_header[:4] == b"PK\x03\x04", local_header[:4]
    fnlen, eflen = struct.unpack("<HH", local_header[26:30])
    return local_offset + 30 + fnlen + eflen


def _entries_from_tail(tail: bytes, base: int) -> dict[str, tuple[int, int, int, int]]:
    """Like parse_central_directory but for an archive *tail* that starts at
    absolute offset `base`; all returned local-header offsets are absolute.

    `tail` is the last N bytes of the archive starting at absolute byte `base`
    (i.e. file_size - len(tail)). We parse the EOCD64 locator/record from
    `tail`, compute the absolute cd_off/cd_size, slice the central directory
    as tail[cd_off-base : cd_off-base+cd_size], then run _parse_cd_records on
    it — the lho values inside the records are already absolute (no rebasing
    needed, they're used later as absolute byte offsets into the archive via
    Range requests).
    """
    loc = tail.rfind(_EOCD64_LOCATOR_SIG)
    if loc != -1:
        # EOCD64 locator: offset 8 holds the absolute offset of the EOCD64 record.
        eocd64_abs = struct.unpack("<Q", tail[loc + 8:loc + 16])[0]
        rec = eocd64_abs - base
        cd_size = struct.unpack("<Q", tail[rec + 40:rec + 48])[0]
        cd_off = struct.unpack("<Q", tail[rec + 48:rec + 56])[0]
    else:
        e = tail.rfind(_EOCD_SIG)
        cd_size = struct.unpack("<I", tail[e + 12:e + 16])[0]
        cd_off = struct.unpack("<I", tail[e + 16:e + 20])[0]
    cd = tail[cd_off - base:cd_off - base + cd_size]
    return _parse_cd_records(cd)


class SlpkReader:
    def __init__(self, losid: str, cache_root: str):
        self.losid = losid
        self.cache_dir = os.path.join(cache_root, losid)
        os.makedirs(self.cache_dir, exist_ok=True)
        self._mirrors = [f"{m}/p/dom-mesh-slpk/{losid}/DSM_Mesh.slpk" for m in SLPK_MIRRORS]
        self._size: Optional[int] = None
        self._entries: Optional[dict] = None
        self._nodes: Optional[list] = None
        self.bytes_fetched = 0

    # ---- low-level range I/O with mirror fallback ----
    def _request(self, headers: dict) -> tuple[bytes, dict]:
        last = None
        for url in self._mirrors:
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "OpenMap_Unifier/dommesh", **headers})
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = r.read()
                    self.bytes_fetched += len(data)
                    return data, dict(r.headers)
            except Exception as ex:  # noqa: BLE001 - we genuinely want to try the next mirror
                last = ex
        raise RuntimeError(f"all mirrors failed for {self.losid}: {last}")

    def _rng(self, a: int, b: int) -> bytes:
        data, _ = self._request({"Range": f"bytes={a}-{b}"})
        return data

    def file_size(self) -> int:
        if self._size is None:
            data, hdrs = self._request({"Range": "bytes=0-0"})
            cr = hdrs.get("Content-Range", "")
            self._size = int(cr.split("/")[-1]) if "/" in cr else None
            if not self._size:
                raise RuntimeError("server did not report file size via Content-Range")
        return self._size

    # ---- entries (ZIP64 central directory), cached ----
    def entries(self) -> dict[str, tuple[int, int, int, int]]:
        if self._entries is not None:
            return self._entries
        cache = os.path.join(self.cache_dir, "entries.json")
        if os.path.exists(cache):
            raw = json.loads(Path(cache).read_text())
            self._entries = {k: tuple(v) for k, v in raw.items()}
            return self._entries
        size = self.file_size()
        tail_len = min(size, 70 * 1024 * 1024)   # comfortably covers CD + EOCD records
        base = size - tail_len
        tail = self._rng(base, size - 1)
        self._entries = _entries_from_tail(tail, base)
        Path(cache).write_text(json.dumps({k: list(v) for k, v in self._entries.items()}))
        return self._entries

    # ---- read one stored entry by name ----
    def read_entry(self, name: str) -> bytes:
        off, csize, _usize, _method = self.entries()[name]
        hdr = self._rng(off, off + 30 + 512)     # local header + filename + (small) extra
        ds = _payload_offset(hdr, off)
        data = self._rng(ds, ds + csize - 1)
        assert len(data) == csize, (name, len(data), csize)
        return gzip.decompress(data) if name.endswith(".gz") else data

    # ---- leaf node OBB list, cached ----
    def nodes(self) -> list[dict]:
        if self._nodes is not None:
            return self._nodes
        cache = os.path.join(self.cache_dir, "nodes.json")
        if os.path.exists(cache):
            self._nodes = json.loads(Path(cache).read_text())
            return self._nodes
        _scene = json.loads(self.read_entry("3dSceneLayer.json.gz"))
        out: list[dict] = []
        page = 0
        while True:
            try:
                pg = json.loads(self.read_entry(f"nodepages/{page}.json.gz"))
            except Exception:
                break
            for nd in pg.get("nodes", []):
                if "mesh" not in nd or nd.get("children"):
                    continue
                obb = nd["obb"]
                c, h = obb["center"], obb["halfSize"]
                mesh = nd["mesh"]
                out.append({
                    "i": nd.get("index", nd.get("resourceId", page)),
                    "cx": c[0], "cy": c[1], "cz": c[2],
                    "hx": h[0], "hy": h[1], "hz": h[2],
                    "geom_res": mesh.get("geometry", {}).get("resource"),
                    "mat_res": mesh.get("material", {}).get("resource"),
                })
            page += 1
        self._nodes = out
        Path(cache).write_text(json.dumps(out))
        return self._nodes
