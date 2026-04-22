
import os
import math
import requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from shapely.wkt import loads
from shapely.geometry import Polygon, box
from pyproj import Transformer
import threading
import time

# Import proxy manager (optional - falls back to direct connection)
try:
    from backend.proxy_manager import ProxyManager, get_proxy_manager
    PROXY_AVAILABLE = True
except ImportError:
    try:
        from proxy_manager import ProxyManager, get_proxy_manager
        PROXY_AVAILABLE = True
    except ImportError:
        PROXY_AVAILABLE = False
        ProxyManager = None
        get_proxy_manager = None

# =============================================================================
# Bayern Open Data dataset catalog
# =============================================================================
# Single source of truth for which datasets the GUI offers.
#
# Raw tiles live on Bayernwolke's CDN. The URL shape is:
#   https://download1.bayernwolke.de/a/<url_key>/<url_subpath>/<tile_id><ext>
# but the three pieces are NOT the same across datasets:
#
#   | dataset | url_subpath | grid_km | tile_prefix | ext   |
#   |---------|-------------|---------|-------------|-------|
#   | dop20   | data        | 1       | "32"        | .tif  |  (verified)
#   | dop40   | data        | 1       | "32"        | .tif  |  (verified)
#   | dgm1    | data        | 1       | "32"        | .tif  |  (verified)
#   | dgm5    | data        | 2       | ""          | .tif  |  (grid/prefix fixed)
#   | lod2    | citygml     | 2       | ""          | .gml  |  (verified)
#   | laser   | data        | 1       | "32"        | .laz  |  (unverified)
#
# The earlier catalog assumed every dataset shared the DOP20 layout, which
# produced 404s for LoD2 and DGM5 (bug report: "lod2 and laz also don't work").
# Tile IDs are derived from easting/northing km in EPSG:25832:
#   "32672_5424" = zone 32 + 672 km E + 5424 km N     (1 km grid)
#   "704_5322"   = 704 km E + 5322 km N, stepped by 2 (2 km grid)
#
# License: Bayerische Vermessungsverwaltung — CC BY 4.0
# Attribution (recommended): "Datenquelle: Bayerische Vermessungsverwaltung
#                              – www.geodaten.bayern.de"
#
# Fields per entry:
#   label        — human-readable name
#   category     — group for UI (height, ortho, buildings, laser, wms_render)
#   description  — short blurb for the GUI
#   ext          — file extension downloaded
#   resolution   — ground sample distance / LoD, for user info
#   kind         — "raw" (direct tile file) or "wms" (rendered tile)
#   # Raw-only:
#   url_key      — first segment under /a/ on bayernwolke.de
#   url_subpath  — second segment (optional, default "data")
#   grid_km      — tile edge in km (optional, default 1)
#   tile_prefix  — prefix on the tile ID (optional, default "32")
#   verified     — True if the URL layout has been confirmed against the
#                  actual server (optional, default True); unverified entries
#                  emit a warning so the user knows a 404 is expected.
#   # WMS-only:
#   base_url, layer, mime — used by generate_relief_tiles()
# -----------------------------------------------------------------------------
BAYERN_DATASETS = {
    # ---- HEIGHT / TERRAIN (raw) ----
    "dgm1": {
        "label": "DGM1 — Digital Terrain Model (Height, 1 m)",
        "category": "height",
        "description": "Bare-earth elevation, 1m grid, GeoTIFF. THIS is real height data for Blender/3D.",
        "ext": ".tif",
        "resolution": "1 m / pixel",
        "pixel_size_m": 1.0,
        "avg_tile_mb": 4,
        "kind": "raw",
        "url_key": "dgm1",
    },
    "dgm5": {
        "label": "DGM5 — Digital Terrain Model (Height, 5 m)",
        "category": "height",
        "description": "Coarser 5m grid, 2 km tiles — useful for large areas where DGM1 would be too big.",
        "ext": ".tif",
        "resolution": "5 m / pixel",
        "pixel_size_m": 5.0,
        "avg_tile_mb": 0.8,  # 2 km tile at 5 m ~= 400x400 px ~= <1 MB
        "kind": "raw",
        "url_key": "dgm5",
        "grid_km": 2,
        "tile_prefix": "",
    },
    # ---- ORTHOPHOTOS (raw) ----
    "dop20": {
        "label": "DOP20 RGB — Orthophoto 20 cm (Highest quality)",
        "category": "ortho",
        "description": "Raw RGB aerial imagery, 20cm/px, GeoTIFF. Large files (~300 MB/tile).",
        "ext": ".tif",
        "resolution": "20 cm / pixel",
        "pixel_size_m": 0.2,
        "avg_tile_mb": 300,
        "kind": "raw",
        "url_key": "dop20",
    },
    "dop40": {
        "label": "DOP40 RGB — Orthophoto 40 cm",
        "category": "ortho",
        "description": "Raw RGB aerial imagery, 40cm/px, GeoTIFF. ~4x smaller than DOP20.",
        "ext": ".tif",
        "resolution": "40 cm / pixel",
        "pixel_size_m": 0.4,
        "avg_tile_mb": 75,
        "kind": "raw",
        "url_key": "dop40",
    },
    # ---- 3D BUILDINGS ----
    "lod2": {
        "label": "LoD2 — 3D building models (CityGML)",
        "category": "buildings",
        "description": "CityGML with building volumes at Level-of-Detail 2 (roof shapes), 2 km tiles.",
        "ext": ".gml",
        "resolution": "2 km tiles",
        "avg_tile_mb": 3,
        "kind": "raw",
        "url_key": "lod2",
        "url_subpath": "citygml",
        "grid_km": 2,
        "tile_prefix": "",
    },
    # ---- LASER / LIDAR ----
    "laser": {
        "label": "Laser — Raw LiDAR point cloud (LAZ)",
        "category": "laser",
        "description": "Compressed LAS (LAZ) — the raw point cloud DGM1 is derived from. Very large (~800 MB/tile).",
        "ext": ".laz",
        "resolution": "1 km tiles",
        "avg_tile_mb": 800,
        "kind": "raw",
        "url_key": "laser",
        # Path layout not yet confirmed against the live server. If this
        # still 404s, the user should paste a working URL from
        # https://geodaten.bayern.de/opengeodata/OpenDataDetail.html?pn=laserdaten
        # so we can pin the correct url_subpath / tile_prefix.
        "verified": False,
    },
    # ---- WMS-RENDERED (visual) ----
    "relief_wms": {
        "label": "Relief (hillshade WMS)",
        "category": "wms_render",
        "description": "Stylised shaded-relief rendering. Visual only — not elevation numbers.",
        "ext": ".tiff",
        "resolution": "WMS render",
        "kind": "wms",
        "base_url": "https://geoservices.bayern.de/pro/wms/dgm/v1/relief",
        "layer": "by_relief_schraeglicht",
        "mime": "image/tiff",
    },
    "dop40_wms": {
        "label": "DOP40 (WMS quick preview)",
        "category": "wms_render",
        "description": "WMS-rendered orthophoto preview. Faster but lower fidelity than raw DOP40.",
        "ext": ".jpg",
        "resolution": "WMS render",
        "kind": "wms",
        "base_url": "https://geoservices.bayern.de/od/wms/dop/v1/dop40",
        "layer": "by_dop40c",
        "mime": "image/jpeg",
    },
}

BAYERN_CATEGORY_LABELS = {
    "height":     "Height / Terrain (raw elevation)",
    "ortho":      "Orthophotos (aerial imagery)",
    "buildings":  "3D Buildings",
    "laser":      "Laser / LiDAR",
    "wms_render": "Visual renders (WMS)",
}


class MapDownloader:
    def __init__(self, download_dir="downloads", proxy_manager=None):
        self.download_dir = download_dir
        if not os.path.exists(download_dir):
            try:
                os.makedirs(download_dir)
            except:
                pass 
        self.stop_event = False
        
        # Proxy support
        self.proxy_manager = proxy_manager
        self._session = None

    def format_bytes(self, size):
        power = 2**10
        n = 0
        power_labels = {0 : '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
        while size >= power and n < 4:
            size /= power
            n += 1
        return f"{size:.2f} {power_labels[n]}B"

    def format_time(self, seconds):
        if seconds < 60:
            return f"{int(seconds)}s"
        m, s = divmod(seconds, 60)
        return f"{int(m)}m {int(s)}s"

    def download_file(self, url, file_name, progress_callback=None):
        """Download a single tile. ``url`` may be a string or a list of mirror
        URLs — mirrors are tried in order and only a 4xx/5xx or network failure
        causes a fallback. A successful download short-circuits."""
        urls = [url] if isinstance(url, str) else list(url)
        if not urls:
            if progress_callback:
                progress_callback(file_name, 0, "Error: no URL", "-", "-")
            return False

        target_path = os.path.join(self.download_dir, file_name)
        part_path = target_path + ".part"

        dir_name = os.path.dirname(target_path)
        if dir_name and not os.path.exists(dir_name):
             try:
                 os.makedirs(dir_name)
             except:
                 pass

        if os.path.exists(target_path):
            if progress_callback:
                progress_callback(file_name, 100, "Skipped (Exists)", "-", "-")
            return True

        # Clean up any leftover .part from a prior interrupted run — we restart
        # from zero rather than attempt a resumable download (servers don't
        # always honour Range, and the complexity isn't worth it here).
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass

        last_error_msg = None
        for attempt_idx, current_url in enumerate(urls):
            if self.stop_event:
                return False
            mirror_note = "" if len(urls) == 1 else f" (mirror {attempt_idx + 1}/{len(urls)})"
            if progress_callback:
                progress_callback(file_name, 0, f"Connecting...{mirror_note}", "-", "-")

            ok, last_error_msg = self._try_single_url(
                current_url, file_name, part_path, target_path, progress_callback, mirror_note)
            if ok:
                return True
            if self.stop_event:
                # Cancel propagates — don't keep trying mirrors.
                return False

        # All mirrors exhausted.
        if last_error_msg:
            print(f"[ERROR] Download failed for {file_name}: {last_error_msg}")
            if progress_callback:
                progress_callback(file_name, 0, last_error_msg, "-", "-")
        return False

    def _try_single_url(self, url, file_name, part_path, target_path,
                        progress_callback, mirror_note):
        """Attempt one URL. Returns (True, None) on success, (False, error_str)
        on any failure — partial files are cleaned up either way."""
        start_time = time.time()
        try:
            # Get session with proxy config if available
            if self.proxy_manager:
                session = self.proxy_manager.get_session()
                response = session.get(url, stream=True, timeout=30)
            else:
                # Fallback to direct request
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                response = requests.get(url, stream=True, timeout=30, headers=headers)
            response.raise_for_status()
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(part_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=65536):
                    if self.stop_event:
                        if progress_callback:
                            progress_callback(file_name, 0, "Cancelled", "-", "-")
                        # Don't leave a partial around after cancel.
                        try:
                            f.close()
                            os.remove(part_path)
                        except OSError:
                            pass
                        return False, "Cancelled"

                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        if progress_callback and total_size > 0:
                            elapsed = time.time() - start_time
                            percent = int((downloaded / total_size) * 100)

                            speed = downloaded / elapsed if elapsed > 0 else 0
                            speed_str = f"{self.format_bytes(speed)}/s"

                            remaining = total_size - downloaded
                            eta = remaining / speed if speed > 0 else 0
                            eta_str = self.format_time(eta)

                            current_str = self.format_bytes(downloaded)
                            total_str = self.format_bytes(total_size)
                            status_msg = f"{current_str} / {total_str}{mirror_note}"

                            progress_callback(file_name, percent, status_msg, speed_str, eta_str)

            # Size-check: if server reported a total, ensure we got all of it.
            if total_size > 0 and downloaded != total_size:
                try:
                    os.remove(part_path)
                except OSError:
                    pass
                msg = f"Truncated: got {downloaded} of {total_size} bytes"
                print(f"[WARN] {file_name}: {msg}{mirror_note}")
                return False, msg

            # Atomic rename: .part -> final name. Only now is the tile visible
            # as "exists" to the skip-check on subsequent runs.
            try:
                os.replace(part_path, target_path)
            except OSError as e:
                msg = f"Rename failed: {e}"
                print(f"[ERROR] {file_name}: {msg}")
                # Local filesystem error — don't bother trying another mirror.
                return False, msg

            if progress_callback:
                progress_callback(file_name, 100, "Completed", "-", "-")
            return True, None
        except Exception as e:
            # Ensure no stale .part survives an exception.
            try:
                if os.path.exists(part_path):
                    os.remove(part_path)
            except OSError:
                pass
            # Classify via ProxyManager if available — otherwise fall back to str(e).
            if self.proxy_manager:
                try:
                    code, msg = self.proxy_manager.classify_error(e)
                    user_msg = f"[{code}] {msg}"
                except Exception:
                    user_msg = f"Error: {e}"
            else:
                user_msg = f"Error: {e}"
            print(f"[WARN] {file_name}{mirror_note}: {user_msg}")
            return False, user_msg

    def parse_metalink(self, file_path):
        """Parse a .meta4 and return [(name, [mirror_url, ...]), ...].

        Bayern's metalinks typically list download1.bayernwolke.de and
        download2.bayernwolke.de as mirrors. download_file() will fall
        through the list on failure, so one mirror being down no longer
        kills the batch."""
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            files = []
            for elem in root.iter():
                if not elem.tag.endswith('file'):
                    continue
                name = elem.get('name')
                urls = [
                    child.text.strip()
                    for child in elem
                    if child.tag.endswith('url') and child.text and child.text.strip()
                ]
                if name and urls:
                    files.append((name, urls))
            return files
        except Exception as e:
            print(f"[ERROR] Metalink parse error: {e}")
            return []

    def generate_relief_tiles(self, polygon_wkt, layer="by_relief_schraeglicht", format_ext="jpg", high_res=False):
        try:
            if ";" in polygon_wkt:
                polygon_wkt = polygon_wkt.split(";", 1)[1]
            
            poly = loads(polygon_wkt)
            transformer = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
            projected_poly = Polygon([transformer.transform(x, y) for x, y in poly.exterior.coords])
            
            minx, miny, maxx, maxy = projected_poly.bounds
            grid_res = 1000
            start_x = math.floor(minx / grid_res) * grid_res
            start_y = math.floor(miny / grid_res) * grid_res
            end_x = math.ceil(maxx / grid_res) * grid_res
            end_y = math.ceil(maxy / grid_res) * grid_res
            
            tiles = []
            
            # --- WMS CONFIGURATION ---
            # Default to Relief
            base_url = "https://geoservices.bayern.de/pro/wms/dgm/v1/relief"
            
            # Switch to DOP40 Open Data if requested
            if "dop" in layer.lower():
                base_url = "https://geoservices.bayern.de/od/wms/dop/v1/dop40"
                layer = "by_dop40c" # Hardcode the correct OpenData color layer
            
            for x in range(start_x, end_x, grid_res):
                for y in range(start_y, end_y, grid_res):
                    tile_box = box(x, y, x + grid_res, y + grid_res)
                    if projected_poly.intersects(tile_box):
                        # Determine MIME and Extension
                        if "relief" in layer:
                            mime = "image/tiff"
                            ext = "tiff"
                        else:
                            # Satellite (DOP)
                            if format_ext == "tif":
                                mime = "image/tiff"
                                ext = "tif"
                            else:
                                mime = "image/jpeg"
                                ext = "jpg"

                        file_name = f"{layer}_{int(x)}_{int(y)}.{ext}"
                        
                        # Set resolution based on high_res flag
                        if high_res:
                            # High-res mode: 300 DPI, ~5906px for 1km at 300 DPI
                            width = 5906
                            height = 5906
                            dpi_params = "&DPI=300&MAP_RESOLUTION=300&FORMAT_OPTIONS=dpi:300"
                        else:
                            # Standard mode: lower resolution for faster downloads
                            width = 2000
                            height = 2000
                            dpi_params = ""
                        
                        url = (
                            f"{base_url}?"
                            f"service=wms&version=1.1.1&request=GetMap"
                            f"&format={mime}&transparent=true"
                            f"&layers={layer}"
                            f"&srs=EPSG:25832&STYLES="
                            f"&WIDTH={width}&HEIGHT={height}{dpi_params}"
                            f"&BBOX={int(x)},{int(y)},{int(x+grid_res)},{int(y+grid_res)}"
                        )
                        tiles.append((file_name, url))
            return tiles
        except Exception as e:
            print(f"[ERROR] generating tiles: {e}")
            return []

    def generate_1km_grid_files(self, polygon_wkt, dataset="dgm1"):
        """
        Build a (filename, url) list for every raw Bayern tile that intersects
        the polygon. Per-dataset URL layout (path, grid size, tile prefix,
        extension) comes from BAYERN_DATASETS — see the comment on that dict
        for the per-dataset table.

        The function name is historical; the grid is not necessarily 1 km.
        """
        try:
            if ";" in polygon_wkt:
                polygon_wkt = polygon_wkt.split(";", 1)[1]

            meta = BAYERN_DATASETS.get(dataset)
            if not meta or meta.get("kind") != "raw":
                print(f"[WARN] Unknown or non-raw Bayern dataset '{dataset}' — nothing to generate.")
                return []

            url_key = meta["url_key"]
            ext = meta["ext"]
            url_subpath = meta.get("url_subpath", "data")
            grid_km = meta.get("grid_km", 1)
            tile_prefix = meta.get("tile_prefix", "32")
            if not meta.get("verified", True):
                print(f"[WARN] Bayern dataset '{dataset}' URL layout is NOT verified — "
                      "404s are possible. If so, please report a working sample URL.")

            poly = loads(polygon_wkt)
            transformer = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
            projected_poly = Polygon([transformer.transform(x, y) for x, y in poly.exterior.coords])

            grid_res = 1000 * grid_km
            minx, miny, maxx, maxy = projected_poly.bounds
            start_x = math.floor(minx / grid_res) * grid_res
            start_y = math.floor(miny / grid_res) * grid_res
            end_x = math.ceil(maxx / grid_res) * grid_res
            end_y = math.ceil(maxy / grid_res) * grid_res

            base_url = f"https://download1.bayernwolke.de/a/{url_key}/{url_subpath}"
            files = []
            for x in range(start_x, end_x, grid_res):
                for y in range(start_y, end_y, grid_res):
                    tile_box = box(x, y, x + grid_res, y + grid_res)
                    if not projected_poly.intersects(tile_box):
                        continue
                    east_km = int(x // 1000)
                    north_km = int(y // 1000)
                    tile_id = f"{tile_prefix}{east_km}_{north_km}"
                    file_name = f"{tile_id}{ext}"
                    url = f"{base_url}/{file_name}"
                    files.append((file_name, url))

            return files
        except Exception as e:
            print(f"[ERROR] generating raw grid: {e}")
            return []
