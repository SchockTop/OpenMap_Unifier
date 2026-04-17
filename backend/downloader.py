
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
            
            with open(target_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=65536):
                    if self.stop_event:
                        if progress_callback:
                            progress_callback(file_name, 0, "Cancelled", "-", "-")
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
            
            if progress_callback:
                progress_callback(file_name, 100, "Completed", "-", "-")
            return True
        except Exception as e:
            msg = str(e)
            print(f"[ERROR] Download failed for {file_name}: {msg}")
            if progress_callback:
                progress_callback(file_name, 0, f"Error: {msg}", "-", "-")
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
        Generates URLs for raw data tiles (1km x 1km) based on the standard OpenData naming convention.
        Grid aligned to 1000m steps in EPSG:25832.
        Nomenclature often: 32<East_km>_<North_km> (e.g., 32672_5424)
        """
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
            
            files = []
            
            # Base URLs (Best Guess/Standard)
            base_urls = {
                "dgm1": ("https://download1.bayernwolke.de/a/dgm1/data", ".tif"),
                "dop20": ("https://download1.bayernwolke.de/a/dop20/data", ".tif"),
                "dop40": ("https://download1.bayernwolke.de/a/dop40/data", ".tif"),
                "lod2": ("https://download1.bayernwolke.de/a/lod2/data", ".zip"),
                "laser": ("https://download1.bayernwolke.de/a/laser/data", ".laz")
            }

            base_url, ext = base_urls.get(dataset, ("", ""))
            # DGM1 is typically .tif (already set above)
            
            for x in range(start_x, end_x, grid_res):
                for y in range(start_y, end_y, grid_res):
                    tile_box = box(x, y, x + grid_res, y + grid_res)
                    if projected_poly.intersects(tile_box):
                        # Naming Scheme: 32 + (x/1000 defined as 3 digits) + (y/1000 defined as 4 digits)
                        # Example X=672000 -> 672. Y=5424000 -> 5424.
                        # Combined: 32672_5424
                        
                        east_km = int(x / 1000)
                        north_km = int(y / 1000)
                        
                        tile_id = f"32{east_km}_{north_km}"
                        
                        file_name = f"{tile_id}{ext}"
                        url = f"{base_url}/{file_name}"
                        files.append((file_name, url))
                        
            return files
        except Exception as e:
            print(f"[ERROR] generating raw grid: {e}")
            return []
