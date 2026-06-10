"""
Sentinel-2 downloader — true satellite imagery incl. real SHORT-WAVE INFRARED
(SWIR), which Bavaria's aerial DOP does NOT provide.

Source: the public AWS Earth-Search STAC (`sentinel-2-l2a`, Cloud-Optimised
GeoTIFFs on `sentinel-cogs` S3). **No login, no API key, no Hugging Face** — it
is plain HTTPS, so it works behind a corporate proxy. Bands provided per item:
  red/green/blue (10 m), nir/nir08 (10 m), rededge1-3 (20 m),
  swir16 = B11 ~1610 nm (20 m), swir22 = B12 ~2190 nm (20 m).

SWIR unlocks indices RGB+NIR cannot compute: NDBI (built-up), MNDWI (water),
NBR (burn), NDMI (moisture) — useful for material/vegetation discrimination.

Cropping to the drawn polygon uses ``rasterio`` (windowed /vsicurl read) when it
is installed; otherwise the whole-tile COG is downloaded over HTTPS and a note is
printed. Searching/indices need only ``requests`` + ``shapely``/``pyproj``.
"""
from __future__ import annotations

import os
from typing import Iterable

import requests
from shapely.wkt import loads as _loads

try:
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds as _window_from_bounds
    _HAVE_RASTERIO = True
except Exception:
    _HAVE_RASTERIO = False

STAC_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
COLLECTION = "sentinel-2-l2a"
_UA = {"User-Agent": "OpenMap-Unifier/Sentinel2 (+https://github.com/SchockTop/OpenMap_Unifier)"}

# asset key -> human note. swir16=B11, swir22=B12.
DEFAULT_BANDS = ("red", "green", "blue", "nir", "swir16", "swir22")

# SWIR/NIR index formulas (asset keys), documented for the user.
INDEX_FORMULAS = {
    "ndvi": "(nir - red) / (nir + red)",
    "ndwi": "(green - nir) / (green + nir)",
    "ndbi": "(swir16 - nir) / (swir16 + nir)        # built-up (needs SWIR)",
    "mndwi": "(green - swir16) / (green + swir16)     # water vs built-up (needs SWIR)",
    "nbr": "(nir - swir22) / (nir + swir22)          # burn (needs SWIR)",
    "ndmi": "(nir - swir16) / (nir + swir16)          # moisture (needs SWIR)",
}


def polygon_bbox_4326(polygon_wkt: str) -> tuple[float, float, float, float]:
    """(minx, miny, maxx, maxy) lon/lat bbox of a WKT polygon (drops any Z)."""
    if ";" in polygon_wkt:
        polygon_wkt = polygon_wkt.split(";", 1)[1]
    poly = _loads(polygon_wkt)
    return tuple(poly.bounds)  # type: ignore[return-value]


class Sentinel2Downloader:
    def __init__(self, download_dir: str = "downloads_sentinel2", proxy_manager=None):
        self.download_dir = download_dir
        os.makedirs(download_dir, exist_ok=True)
        self.proxy_manager = proxy_manager

    def _session(self):
        if self.proxy_manager:
            return self.proxy_manager.get_session()
        s = requests.Session()
        s.headers.update(_UA)
        return s

    def search(
        self,
        polygon_wkt: str,
        date_range: str = "2023-06-01/2023-09-30",
        max_cloud: float = 20.0,
        limit: int = 5,
    ) -> list[dict]:
        """STAC search for the least-cloudy scenes over the polygon.

        ``date_range`` is "YYYY-MM-DD/YYYY-MM-DD". Returns a list of STAC item
        dicts sorted by increasing cloud cover.
        """
        minx, miny, maxx, maxy = polygon_bbox_4326(polygon_wkt)
        start, end = date_range.split("/")
        body = {
            "collections": [COLLECTION],
            "bbox": [minx, miny, maxx, maxy],
            "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
            "query": {"eo:cloud_cover": {"lt": max_cloud}},
            "limit": limit,
        }
        r = self._session().post(STAC_SEARCH_URL, json=body, timeout=60)
        r.raise_for_status()
        feats = r.json().get("features", [])
        feats.sort(key=lambda f: f.get("properties", {}).get("eo:cloud_cover", 100.0))
        return feats

    @staticmethod
    def asset_href(item: dict, band: str) -> str | None:
        a = item.get("assets", {}).get(band)
        return a.get("href") if a else None

    def download_bands(
        self,
        item: dict,
        polygon_wkt: str,
        bands: Iterable[str] = DEFAULT_BANDS,
        max_size: int = 2048,
        progress_callback=None,
    ) -> dict[str, str]:
        """Download the requested bands for one STAC item, cropped to the polygon.

        With rasterio: windowed /vsicurl read of just the polygon bbox -> small
        GeoTIFF per band. Without rasterio: the whole-tile COG is fetched over
        HTTPS (large) and saved as-is. Returns {band: local_path}.
        """
        item_id = item.get("id", "s2")
        out: dict[str, str] = {}
        bbox = polygon_bbox_4326(polygon_wkt)
        for band in bands:
            href = self.asset_href(item, band)
            if not href:
                print(f"[WARN] item {item_id} has no asset '{band}' — skipping.")
                continue
            dst = os.path.join(self.download_dir, f"{item_id}_{band}.tif")
            if os.path.exists(dst):
                out[band] = dst
                continue
            if progress_callback:
                progress_callback(f"{item_id}_{band}", 0, "Fetching...", "-", "-")
            try:
                if _HAVE_RASTERIO:
                    self._windowed_read(href, bbox, dst, max_size)
                else:
                    self._whole_cog(href, dst)
                out[band] = dst
                if progress_callback:
                    progress_callback(f"{item_id}_{band}", 100, "Completed", "-", "-")
            except Exception as e:
                print(f"[ERROR] {band}: {e}")
                if progress_callback:
                    progress_callback(f"{item_id}_{band}", 0, f"Error: {e}", "-", "-")
        return out

    def _windowed_read(self, href, bbox_4326, dst, max_size):
        """Crop the COG to the polygon bbox via a single windowed /vsicurl read."""
        # GDAL needs the proxy's CA or unsafe-SSL in some corporate setups; the
        # env var GDAL_HTTP_UNSAFESSL=YES is the documented escape hatch.
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_USE_HEAD="NO"):
            with rasterio.open(href) as src:
                left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, *bbox_4326)
                win = _window_from_bounds(left, bottom, right, top, transform=src.transform)
                data = src.read(1, window=win)
                # Optional downsample to max_size on the long edge.
                if max(data.shape) > max_size and max(data.shape) > 0:
                    import numpy as np
                    step = int(np.ceil(max(data.shape) / max_size))
                    data = data[::step, ::step]
                transform = src.window_transform(win)
                profile = src.profile.copy()
                profile.update(height=data.shape[0], width=data.shape[1],
                               transform=transform, count=1, driver="GTiff")
            with rasterio.open(dst, "w", **profile) as out:
                out.write(data, 1)

    def _whole_cog(self, href, dst):
        print(f"[INFO] rasterio not installed -> downloading whole Sentinel-2 tile "
              f"(large) for {os.path.basename(dst)}. Install rasterio to crop to the polygon.")
        with self._session().get(href, stream=True, timeout=120) as r:
            r.raise_for_status()
            tmp = dst + ".part"
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    if chunk:
                        f.write(chunk)
            os.replace(tmp, dst)


def _nearest_resample(arr, shape):
    """Nearest-neighbour resample a 2-D array to ``shape`` (numpy-only).

    Sentinel-2 bands have different native resolutions (10 m red/nir vs 20 m
    swir16/swir22), so index maths must put them on a common grid first.
    """
    import numpy as np
    h, w = shape
    ri = (np.linspace(0, arr.shape[0] - 1, h)).round().astype(int)
    ci = (np.linspace(0, arr.shape[1] - 1, w)).round().astype(int)
    return arr[np.ix_(ri, ci)]


def compute_index(bands: dict, name: str):
    """Compute a named index (see INDEX_FORMULAS) from a {band: path} mapping
    of GeoTIFFs read with rasterio. Bands of differing resolution are resampled
    to the finer (larger) grid. Returns a float32 numpy array."""
    if not _HAVE_RASTERIO:
        raise RuntimeError("rasterio is required to compute indices")
    name = name.lower()
    need = {
        "ndvi": ("nir", "red"), "ndwi": ("green", "nir"),
        "ndbi": ("swir16", "nir"), "mndwi": ("green", "swir16"),
        "nbr": ("nir", "swir22"), "ndmi": ("nir", "swir16"),
    }[name]
    arrs = {}
    for b in set(need):
        with rasterio.open(bands[b]) as s:
            arrs[b] = s.read(1).astype("float32")
    # Common grid = the finer (largest) of the two band shapes.
    target = max((arrs[b].shape for b in need), key=lambda s: s[0] * s[1])
    a, c = need
    A = _nearest_resample(arrs[a], target) if arrs[a].shape != target else arrs[a]
    C = _nearest_resample(arrs[c], target) if arrs[c].shape != target else arrs[c]
    return (A - C) / (A + C + 1e-6)
