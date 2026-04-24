"""
Smoke test for every Bayern map type in the catalog.

For each entry in BAYERN_DATASETS we do two things:

  1. Offline check — build the URL via the downloader's own code path
     (generate_1km_grid_files for raw tiles, generate_relief_tiles for WMS)
     using a tiny well-covered polygon near Munich, and verify the URL
     structure matches what we expect for that dataset. This is what
     regressed on dgm1 / dgm5 before — the URL was /a/dgm5/data/ instead
     of /a/dgm/dgm5/data/.

  2. Live check — send an HTTP HEAD request to the generated URL (or GET
     for WMS, since some WMS servers don't accept HEAD). A 200 or 404
     both count as "server reachable with the right path shape": 404
     just means the specific tile doesn't exist in that corner of the
     grid, which is fine — what we're guarding against is the entire
     host/path being wrong (DNS, 400, 403).

Run:   python test_map_types.py
       python test_map_types.py --offline   # skip network calls

Exit code is non-zero if any dataset fails.
"""

import sys
import unittest
from urllib.parse import urlparse, parse_qs

import requests

from backend.downloader import (
    BAYERN_DATASETS,
    BAYERN_RAW_MIRRORS,
    MapDownloader,
)


# Small polygon in the middle of Bavaria (near München) — big enough to
# cover at least one 1 km UTM tile, small enough to stay cheap.
MUNICH_POLYGON_WKT = (
    "SRID=4326;POLYGON(("
    "11.50 48.10, 11.51 48.10, 11.51 48.11, 11.50 48.11, 11.50 48.10"
    "))"
)

HEAD_TIMEOUT = 15
# Live checks treat these codes as "server + path are OK":
#   200 — file exists
#   404 — path is valid, this particular tile just isn't there
#   405 — HEAD not allowed (some WMS), caller should fall back to GET
LIVE_OK_STATUSES = {200, 404, 405}


def build_raw_url(dataset_key, tile_id="32672_5424", mirror=None):
    """Construct a raw tile URL the same way the downloader does."""
    meta = BAYERN_DATASETS[dataset_key]
    url_path = meta.get("url_path") or meta.get("url_key")
    host = mirror or BAYERN_RAW_MIRRORS[0]
    return f"{host}/a/{url_path}/{tile_id}{meta['ext']}"


class TestCatalogShape(unittest.TestCase):
    """Offline checks — run without network."""

    def test_every_entry_has_required_fields(self):
        for key, meta in BAYERN_DATASETS.items():
            with self.subTest(dataset=key):
                self.assertIn("label", meta)
                self.assertIn("category", meta)
                self.assertIn("kind", meta)
                self.assertIn(meta["kind"], {"raw", "wms"})
                if meta["kind"] == "raw":
                    self.assertTrue(
                        meta.get("url_path") or meta.get("url_key"),
                        f"{key}: raw datasets need url_path",
                    )
                    self.assertTrue(
                        meta["ext"].startswith("."),
                        f"{key}: ext must start with '.'",
                    )
                else:  # wms
                    self.assertIn("base_url", meta)
                    self.assertIn("layer", meta)
                    self.assertIn("mime", meta)

    def test_dgm_uses_grouped_path_without_data_segment(self):
        # Regression guard for the height-download bug. DGM tiles live at
        #   /a/dgm/dgm1/<tile>.tif   and   /a/dgm/dgm5/<tile>.tif
        # — the dgm/ group prefix IS present, and the /data/ segment is NOT
        # (this was confirmed against Bavaria's published .meta4 metalinks).
        for key in ("dgm1", "dgm5"):
            with self.subTest(dataset=key):
                url = build_raw_url(key)
                self.assertIn(f"/a/dgm/{key}/", url, url)
                self.assertNotIn(
                    f"/a/dgm/{key}/data/",
                    url,
                    f"{key}: URL must NOT contain /data/ — metalinks put tiles"
                    f" directly under /a/dgm/{key}/. Got: {url}",
                )
                self.assertTrue(url.endswith(".tif"), url)

    def test_dgm5_snaps_to_2km_grid(self):
        # DGM5 tiles only exist on the 2 km AdV grid (even km coords).
        # Stepping at 1 km gives us phantom tiles like 32725_5431 that 404.
        # Guard: every generated DGM5 tile's easting/northing must be even.
        dl = MapDownloader(download_dir="downloads_test")
        # Big enough polygon to span several 2 km tiles.
        poly = (
            "SRID=4326;POLYGON(("
            "11.50 48.10, 11.55 48.10, 11.55 48.14, 11.50 48.14, 11.50 48.10"
            "))"
        )
        files = dl.generate_1km_grid_files(poly, dataset="dgm5")
        self.assertTrue(files, "dgm5 produced no tiles")
        for fname, _url in files:
            # fname looks like "32724_5430.tif" — strip "32" and ".tif",
            # split on "_", both halves must be even km.
            stem = fname.rsplit(".", 1)[0]
            self.assertTrue(stem.startswith("32"), fname)
            east_km, north_km = stem[2:].split("_")
            self.assertEqual(
                int(east_km) % 2, 0,
                f"{fname}: easting {east_km} must be even for 2 km grid",
            )
            self.assertEqual(
                int(north_km) % 2, 0,
                f"{fname}: northing {north_km} must be even for 2 km grid",
            )

    def test_dop_keeps_data_segment(self):
        # Sister guard: DOP20/DOP40 DO have /data/ in the path (verified
        # against the repo's dop20rgb.meta4). Make sure our refactor didn't
        # strip it for the datasets that need it.
        for key in ("dop20", "dop40"):
            with self.subTest(dataset=key):
                url = build_raw_url(key)
                self.assertIn(f"/a/{key}/data/", url, url)

    def test_generate_1km_grid_files_for_every_raw_dataset(self):
        dl = MapDownloader(download_dir="downloads_test")
        for key, meta in BAYERN_DATASETS.items():
            if meta["kind"] != "raw":
                continue
            with self.subTest(dataset=key):
                files = dl.generate_1km_grid_files(MUNICH_POLYGON_WKT, dataset=key)
                self.assertTrue(files, f"{key}: no tiles generated")
                fname, url = files[0]
                # url_path is the full segment between /a/ and the tile file.
                # We expect the URL to end in /a/<url_path>/<tile><ext>.
                url_path = meta.get("url_path") or meta.get("url_key")
                self.assertIn(f"/a/{url_path}/", url, url)
                self.assertTrue(
                    url.endswith(f"/{fname}"),
                    f"{key}: url {url!r} should end with /{fname}",
                )
                self.assertTrue(
                    url.endswith(meta["ext"]),
                    f"{key}: url {url!r} should end with {meta['ext']!r}",
                )
                self.assertTrue(
                    fname.endswith(meta["ext"]),
                    f"{key}: filename {fname!r} should end with {meta['ext']!r}",
                )

    def test_generate_relief_tiles_for_every_wms_dataset(self):
        dl = MapDownloader(download_dir="downloads_test")
        for key, meta in BAYERN_DATASETS.items():
            if meta["kind"] != "wms":
                continue
            with self.subTest(dataset=key):
                # format_ext carries a hint for DOP ("tif" vs default jpg);
                # for relief the generator picks the right mime on its own.
                format_ext = "tif" if meta["mime"] == "image/tiff" else "jpg"
                tiles = dl.generate_relief_tiles(
                    MUNICH_POLYGON_WKT,
                    layer=meta["layer"],
                    format_ext=format_ext,
                )
                self.assertTrue(tiles, f"{key}: no tiles generated")
                fname, url = tiles[0]
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                self.assertEqual(qs.get("request"), ["GetMap"])
                self.assertIn(meta["layer"], qs.get("layers", [""])[0])


def _network_can_reach_bayern():
    """Probe a known-good DOP20 tile; skip the live suite if the environment
    can't even see the server (sandbox allowlist, offline CI, etc.)."""
    probe = build_raw_url("dop20", tile_id="32672_5424")
    try:
        r = requests.head(probe, timeout=HEAD_TIMEOUT, allow_redirects=True)
    except requests.RequestException:
        return False
    return r.status_code in LIVE_OK_STATUSES


@unittest.skipIf("--offline" in sys.argv, "offline mode requested")
@unittest.skipUnless(
    _network_can_reach_bayern() if "--offline" not in sys.argv else False,
    "Can't reach bayernwolke/geoservices — check network or use --offline",
)
class TestCatalogLiveReachability(unittest.TestCase):
    """Live HTTP checks — skip with --offline, or when network is unreachable."""

    def _head_ok(self, url):
        try:
            r = requests.head(url, timeout=HEAD_TIMEOUT, allow_redirects=True)
        except requests.RequestException as e:
            self.fail(f"HEAD {url} raised {e!r}")
        if r.status_code == 405:
            # Server refused HEAD — retry with a ranged GET that pulls
            # only the first byte so we don't waste bandwidth.
            try:
                r = requests.get(
                    url,
                    timeout=HEAD_TIMEOUT,
                    headers={"Range": "bytes=0-0"},
                    stream=True,
                )
                r.close()
            except requests.RequestException as e:
                self.fail(f"GET {url} raised {e!r}")
        self.assertIn(
            r.status_code,
            LIVE_OK_STATUSES,
            f"{url} returned HTTP {r.status_code} "
            f"(body starts: {r.text[:200]!r})",
        )

    def test_every_raw_dataset_is_reachable(self):
        # Use the tile ID from the existing dop20rgb.meta4 — confirmed to
        # exist for DOP20 and to be in Bavaria's coverage area. DGM/LoD2
        # may 404 for this exact tile, which is fine (path-shape only).
        tile_id = "32672_5424"
        for key, meta in BAYERN_DATASETS.items():
            if meta["kind"] != "raw":
                continue
            with self.subTest(dataset=key):
                url = build_raw_url(key, tile_id=tile_id)
                self._head_ok(url)

    def test_every_wms_dataset_is_reachable(self):
        dl = MapDownloader(download_dir="downloads_test")
        for key, meta in BAYERN_DATASETS.items():
            if meta["kind"] != "wms":
                continue
            with self.subTest(dataset=key):
                format_ext = "tif" if meta["mime"] == "image/tiff" else "jpg"
                tiles = dl.generate_relief_tiles(
                    MUNICH_POLYGON_WKT,
                    layer=meta["layer"],
                    format_ext=format_ext,
                )
                self.assertTrue(tiles)
                _, url = tiles[0]
                # WMS servers generally don't accept HEAD — go straight to
                # a streamed GET and bail out after the status line.
                try:
                    r = requests.get(url, timeout=HEAD_TIMEOUT, stream=True)
                    r.close()
                except requests.RequestException as e:
                    self.fail(f"GET {url} raised {e!r}")
                self.assertIn(
                    r.status_code,
                    LIVE_OK_STATUSES,
                    f"{url} returned HTTP {r.status_code}",
                )


if __name__ == "__main__":
    # Strip our custom flag so unittest doesn't choke on it.
    argv = [a for a in sys.argv if a != "--offline"]
    unittest.main(argv=argv, verbosity=2)
