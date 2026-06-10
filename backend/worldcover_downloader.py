"""
ESA WorldCover downloader — global 10 m land-cover (11 classes), 2021 v200.

Source: the public ESA WorldCover S3 bucket (eu-central-1). **No login, no API
key, no Hugging Face** — plain HTTPS, proxy-friendly. Tiles are 3deg x 3deg COGs
named by their SW corner, e.g. ``ESA_WorldCover_10m_2021_v200_N48E012_Map.tif``.

Useful as free *weak labels* for training (built-up / tree / grass / water / crop
/ bare ...), to complement OSM land-use. With ``rasterio`` the tile is windowed-
read and cropped to the drawn polygon; without it, the ~100 MB tile is fetched
whole.
"""
from __future__ import annotations

import math
import os

import requests
from shapely.wkt import loads as _loads

try:
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds as _window_from_bounds
    _HAVE_RASTERIO = True
except Exception:
    _HAVE_RASTERIO = False

S3_BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
_UA = {"User-Agent": "OpenMap-Unifier/WorldCover (+https://github.com/SchockTop/OpenMap_Unifier)"}

# WorldCover class code -> name.
WORLDCOVER_CLASSES = {
    10: "tree_cover", 20: "shrubland", 30: "grassland", 40: "cropland",
    50: "built_up", 60: "bare_sparse", 70: "snow_ice", 80: "permanent_water",
    90: "herbaceous_wetland", 95: "mangrove", 100: "moss_lichen",
}


def tile_name_for(lat: float, lon: float) -> str:
    """SW-corner tile name on the 3deg grid, e.g. (48.1, 11.5) -> 'N48E009'."""
    tlat = int(math.floor(lat / 3.0) * 3)
    tlon = int(math.floor(lon / 3.0) * 3)
    ns = "N" if tlat >= 0 else "S"
    ew = "E" if tlon >= 0 else "W"
    return f"{ns}{abs(tlat):02d}{ew}{abs(tlon):03d}"


def tile_url(lat: float, lon: float) -> str:
    return f"{S3_BASE}/ESA_WorldCover_10m_2021_v200_{tile_name_for(lat, lon)}_Map.tif"


def polygon_bbox_4326(polygon_wkt: str) -> tuple[float, float, float, float]:
    if ";" in polygon_wkt:
        polygon_wkt = polygon_wkt.split(";", 1)[1]
    return tuple(_loads(polygon_wkt).bounds)  # type: ignore[return-value]


class WorldCoverDownloader:
    def __init__(self, download_dir: str = "downloads_worldcover", proxy_manager=None):
        self.download_dir = download_dir
        os.makedirs(download_dir, exist_ok=True)
        self.proxy_manager = proxy_manager

    def _session(self):
        if self.proxy_manager:
            return self.proxy_manager.get_session()
        s = requests.Session()
        s.headers.update(_UA)
        return s

    def fetch(self, polygon_wkt: str, max_size: int = 2048, progress_callback=None) -> str:
        """Download the WorldCover land-cover covering the polygon, cropped to its
        bbox (with rasterio) or whole-tile (without). Returns the local path.

        Picks the tile from the polygon centroid; does NOT mosaic across the
        3deg tile boundary (a polygon straddling two tiles gets the centre one).
        """
        minx, miny, maxx, maxy = polygon_bbox_4326(polygon_wkt)
        clat, clon = (miny + maxy) / 2.0, (minx + maxx) / 2.0
        url = tile_url(clat, clon)
        dst = os.path.join(self.download_dir, f"worldcover_{tile_name_for(clat, clon)}.tif")
        if os.path.exists(dst):
            return dst
        if progress_callback:
            progress_callback(os.path.basename(dst), 0, "Fetching...", "-", "-")
        if _HAVE_RASTERIO:
            self._windowed(url, (minx, miny, maxx, maxy), dst, max_size)
        else:
            self._whole(url, dst)
        if progress_callback:
            progress_callback(os.path.basename(dst), 100, "Completed", "-", "-")
        return dst

    def _windowed(self, url, bbox_4326, dst, max_size):
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_USE_HEAD="NO"):
            with rasterio.open(url) as src:
                left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, *bbox_4326)
                win = _window_from_bounds(left, bottom, right, top, transform=src.transform)
                data = src.read(1, window=win)
                if max(data.shape) > max_size and max(data.shape) > 0:
                    import numpy as np
                    step = int(np.ceil(max(data.shape) / max_size))
                    data = data[::step, ::step]
                profile = src.profile.copy()
                profile.update(height=data.shape[0], width=data.shape[1],
                               transform=src.window_transform(win), count=1, driver="GTiff")
            with rasterio.open(dst, "w", **profile) as out:
                out.write(data, 1)

    def _whole(self, url, dst):
        print(f"[INFO] rasterio not installed -> downloading whole WorldCover tile "
              f"(~100 MB) for {os.path.basename(dst)}. Install rasterio to crop to the polygon.")
        with self._session().get(url, stream=True, timeout=180) as r:
            r.raise_for_status()
            tmp = dst + ".part"
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    if chunk:
                        f.write(chunk)
            os.replace(tmp, dst)

    @staticmethod
    def class_histogram(path: str) -> dict[str, int]:
        """{class_name: pixel_count} for a downloaded WorldCover GeoTIFF."""
        if not _HAVE_RASTERIO:
            raise RuntimeError("rasterio is required to read the WorldCover raster")
        import numpy as np
        with rasterio.open(path) as s:
            arr = s.read(1)
        vals, counts = np.unique(arr, return_counts=True)
        return {WORLDCOVER_CLASSES.get(int(v), f"class_{int(v)}"): int(c)
                for v, c in zip(vals, counts)}
