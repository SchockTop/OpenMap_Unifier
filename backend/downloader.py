
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
# All raw tile datasets follow the same 1km x 1km grid (EPSG:25832) and the
# URL pattern: https://<mirror>/a/<url_path>/<tile_id><ext>
# where <tile_id> is derived from easting/northing km (e.g. "32672_5424") and
# <url_path> is the ENTIRE path between /a/ and the tile filename. The shape
# varies by dataset — DOP tiles live under .../data/, DGM tiles do not:
#   DOP20  -> /a/dop20/data/32672_5424.tif    url_path = "dop20/data"
#   DGM1   -> /a/dgm/dgm1/32672_5424.tif      url_path = "dgm/dgm1"
#   DGM5   -> /a/dgm/dgm5/32672_5424.tif      url_path = "dgm/dgm5"
# Confirmed against Bavaria's opendata metalinks (.meta4) — the DGM entries
# do NOT include a /data/ segment, which is what was breaking the download.
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
#   # For raw:
#   #   url_path     — full path under /a/ on bayernwolke.de (may contain slashes)
#   #   grid_km      — tile size in km (default 1). DGM5 is 2 km on the AdV grid.
#   #   tile_prefix  — string prepended to "<east_km>_<north_km>" in the filename.
#   #                  DOP uses "32" (UTM-zone marker), DGM uses "" — confirmed
#   #                  against Bavaria's live metalinks (poly2metalink output).
#   # For wms: base_url, layer, mime are used by generate_relief_tiles()
# -----------------------------------------------------------------------------
BAYERN_RAW_MIRRORS = [
    "https://download1.bayernwolke.de",
    "https://download2.bayernwolke.de",
]

BAYERN_DATASETS = {
    # ---- HEIGHT / TERRAIN (raw) ----
    # NOTE: DGM tiles live under the "dgm/" group prefix on bayernwolke —
    # not the flat /a/dgm1/ path used for DOP. The metalink index at
    # geodaten.bayern.de/odd/a/dgm/dgm1/ confirms this grouping.
    "dgm1": {
        # Tile filenames for DGM1 have NO "32" UTM-zone prefix — verified
        # against a live metalink from poly2metalink, which lists files
        # like "729_5433.tif" at https://download1.bayernwolke.de/a/dgm/dgm1/.
        "label": "DGM1 — Digital Terrain Model (Height, 1 m)",
        "category": "height",
        "description": "Bare-earth elevation, 1m grid, GeoTIFF. THIS is real height data for Blender/3D.",
        "ext": ".tif",
        "resolution": "1 m / pixel",
        "pixel_size_m": 1.0,
        "avg_tile_mb": 4,
        "kind": "raw",
        "url_path": "dgm/dgm1",
        "tile_prefix": "",
    },
    "dgm5": {
        # DGM5 also drops the "32" UTM prefix (same /a/dgm/ group as DGM1).
        # Bavaria's DGM5 ships on the 2 km AdV tile grid per their docs,
        # so grid_km=2 keeps us on even-km coords. If a live metalink
        # shows 1 km spacing, set grid_km=1.
        "label": "DGM5 — Digital Terrain Model (Height, 5 m)",
        "category": "height",
        "description": "Coarser 5m grid on 2 km AdV tiles — useful for large areas where DGM1 would be too big.",
        "ext": ".tif",
        "resolution": "5 m / pixel",
        "pixel_size_m": 5.0,
        "avg_tile_mb": 0.8,
        "kind": "raw",
        "url_path": "dgm/dgm5",
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
        "url_path": "dop20/data",
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
        "url_path": "dop40/data",
    },
    # ---- 3D BUILDINGS ----
    "lod2": {
        "label": "LoD2 — 3D building models (CityGML)",
        # LoD2 lives at /a/lod2/citygml/<east>_<north>.gml on the 2 km AdV
        # grid — verified against the live metalink at
        # https://geodaten.bayern.de/odd/a/lod2/citygml/meta/metalink/09.meta4
        # Marienplatz (UTM ~691, 5334) snaps to even km -> 690_5334.gml
        # which downloads as ~150 MB. Was 404'ing on /lod2/data/ + .zip.
        "category": "buildings",
        "description": "CityGML with building volumes at Level-of-Detail 2 (roof shapes). 2 km tiles.",
        "ext": ".gml",
        "resolution": "2 km tiles",
        "avg_tile_mb": 50,
        "kind": "raw",
        "url_path": "lod2/citygml",
        "grid_km": 2,
        "tile_prefix": "",
    },
    # ---- LASER / LIDAR ----
    "laser": {
        "label": "Laser — Raw LiDAR point cloud (LAZ)",
        "category": "laser",
        "description": "Compressed LAS (LAZ) — the raw point cloud DGM1 is derived from. Very large (~800 MB/tile).",
        "ext": ".laz",
        "resolution": "point cloud",
        "avg_tile_mb": 800,
        "kind": "raw",
        "url_path": "laser/data",
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

        if progress_callback:
            progress_callback(file_name, 0, "Connecting...", "-", "-")

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
                        return False

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
                            status_msg = f"{current_str} / {total_str}"

                            progress_callback(file_name, percent, status_msg, speed_str, eta_str)

            # Size-check: if server reported a total, ensure we got all of it.
            if total_size > 0 and downloaded != total_size:
                try:
                    os.remove(part_path)
                except OSError:
                    pass
                msg = f"Truncated: got {downloaded} of {total_size} bytes"
                print(f"[ERROR] {file_name}: {msg}")
                if progress_callback:
                    progress_callback(file_name, 0, msg, "-", "-")
                return False

            # Atomic rename: .part -> final name. Only now is the tile visible
            # as "exists" to the skip-check on subsequent runs.
            try:
                os.replace(part_path, target_path)
            except OSError as e:
                msg = f"Rename failed: {e}"
                print(f"[ERROR] {file_name}: {msg}")
                if progress_callback:
                    progress_callback(file_name, 0, msg, "-", "-")
                return False

            if progress_callback:
                progress_callback(file_name, 100, "Completed", "-", "-")
            return True
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
            print(f"[ERROR] Download failed for {file_name}: {user_msg}")
            if progress_callback:
                progress_callback(file_name, 0, user_msg, "-", "-")
            return False

    def parse_metalink(self, file_path):
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            files = []
            for elem in root.iter():
                if elem.tag.endswith('file'):
                    name = elem.get('name')
                    url = None
                    for child in elem:
                        if child.tag.endswith('url'):
                            url = child.text
                            break
                    if name and url:
                        files.append((name, url))
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
            # Index c[0]/c[1] instead of unpacking `for x, y in ...` so we
            # survive POLYGON Z(lon lat alt ...) inputs. KML polygons from
            # Google Earth often include a zero altitude per vertex; we
            # always work in 2D on the EPSG:25832 grid, so drop Z here.
            projected_poly = Polygon([transformer.transform(c[0], c[1]) for c in poly.exterior.coords])
            
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
        Generate URLs for raw data tiles that intersect the polygon.

        Grid step is per-dataset: DOP/DGM1 tiles are 1 km x 1 km, DGM5 (and
        other AdV 2 km datasets) step by 2 km. We snap to the dataset's grid
        so we never emit tile IDs that don't exist on the server.
        Nomenclature: 32<East_km>_<North_km> in EPSG:25832, e.g. "32672_5424".
        """
        try:
            if ";" in polygon_wkt:
                polygon_wkt = polygon_wkt.split(";", 1)[1]

            poly = loads(polygon_wkt)
            transformer = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
            # Index c[0]/c[1] instead of unpacking `for x, y in ...` so we
            # survive POLYGON Z(lon lat alt ...) inputs. KML polygons from
            # Google Earth often include a zero altitude per vertex; we
            # always work in 2D on the EPSG:25832 grid, so drop Z here.
            projected_poly = Polygon([transformer.transform(c[0], c[1]) for c in poly.exterior.coords])

            # Derive base URL, extension, and grid step from the catalog.
            meta = BAYERN_DATASETS.get(dataset)
            if not meta or meta.get("kind") != "raw":
                print(f"[WARN] Unknown or non-raw Bayern dataset '{dataset}' — nothing to generate.")
                return []
            # url_path is the ENTIRE path segment between /a/ and the tile filename.
            # Accept legacy "url_key" as a fallback.
            url_path = meta.get("url_path") or meta.get("url_key")
            ext = meta["ext"]
            base_url = f"{BAYERN_RAW_MIRRORS[0]}/a/{url_path}"

            grid_km = int(meta.get("grid_km", 1))
            grid_res = grid_km * 1000
            # "32" UTM-zone prefix for DOP, empty for DGM — default matches
            # the historical behaviour so DOP catalog entries don't have to
            # opt in.
            tile_prefix = meta.get("tile_prefix", "32")

            minx, miny, maxx, maxy = projected_poly.bounds
            start_x = math.floor(minx / grid_res) * grid_res
            start_y = math.floor(miny / grid_res) * grid_res
            end_x = math.ceil(maxx / grid_res) * grid_res
            end_y = math.ceil(maxy / grid_res) * grid_res

            files = []

            for x in range(start_x, end_x, grid_res):
                for y in range(start_y, end_y, grid_res):
                    tile_box = box(x, y, x + grid_res, y + grid_res)
                    if projected_poly.intersects(tile_box):
                        # Naming: <tile_prefix><east_km>_<north_km><ext>.
                        # DOP:  "32672_5424.tif"  (tile_prefix="32")
                        # DGM:  "672_5424.tif"    (tile_prefix="")
                        east_km = int(x / 1000)
                        north_km = int(y / 1000)
                        tile_id = f"{tile_prefix}{east_km}_{north_km}"

                        file_name = f"{tile_id}{ext}"
                        url = f"{base_url}/{file_name}"
                        files.append((file_name, url))
                        
            return files
        except Exception as e:
            print(f"[ERROR] generating raw grid: {e}")
            return []
