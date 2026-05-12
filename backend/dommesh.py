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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
