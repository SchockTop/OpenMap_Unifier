
import sys
import os
import math
import requests
from shapely.wkt import loads
from shapely.geometry import Polygon, box
from pyproj import Transformer
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

def parse_wkt_polygon(wkt_string):
    """Parses WKT string, handles likely input modifications like SRID prefix."""
    # Remove SRID=...; if present
    if ";" in wkt_string:
        wkt_string = wkt_string.split(";", 1)[1]
    return loads(wkt_string)

def generate_tile_urls(polygon_wkt, output_srid=25832):
    """
    Generates download URLs for 1km x 1km tiles intersecting the polygon.
    Assumes the portal grid aligns with 1000m steps in EPSG:25832.
    """
    
    # 1. Parse Input Polygon (Assumed WGS84 EPSG:4326 based on user context)
    poly = parse_wkt_polygon(polygon_wkt)
    
    # 2. Project to EPSG:25832 (UTM32N)
    # The portal uses UTM32N for the BBOX requests
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{output_srid}", always_xy=True)
    
    # Project the polygon (index c[0]/c[1] so POLYGON Z inputs with altitude
    # still work — we only care about the 2D footprint for tile selection).
    projected_poly = Polygon([transformer.transform(c[0], c[1]) for c in poly.exterior.coords])
    
    # 3. Calculate Bounding Box of the projected polygon
    minx, miny, maxx, maxy = projected_poly.bounds
    
    # 4. Align to 1km grid
    # Round down min to nearest 1000, round up max to nearest 1000
    grid_res = 1000
    
    start_x = math.floor(minx / grid_res) * grid_res
    start_y = math.floor(miny / grid_res) * grid_res
    end_x = math.ceil(maxx / grid_res) * grid_res
    end_y = math.ceil(maxy / grid_res) * grid_res
    
    tiles = []
    
    # Iterate through the grid
    for x in range(start_x, end_x, grid_res):
        for y in range(start_y, end_y, grid_res):
            # Create a box for this tile
            tile_box = box(x, y, x + grid_res, y + grid_res)
            
            # Check if tile intersects the polygon
            # We use intersects() to capture any tile barely touching or inside
            if projected_poly.intersects(tile_box):
                # Construct URL parameters
                # Based on: https://geoservices.bayern.de/pro/wms/dgm/v1/relief?service=wms&version=1.1.1&request=GetMap&format=image/tiff&transparent=true&layers=by_relief_schraeglicht&srs=EPSG:25832&STYLES=&DPI=300&MAP_RESOLUTION=300&FORMAT_OPTIONS=dpi:300&WIDTH=5906&HEIGHT=5906&BBOX=668000,5424000,669000,5425000
                
                # Filename logic from example: 668000_5424000.tiff
                file_name = f"{int(x)}_{int(y)}.tiff"
                
                url = (
                    "https://geoservices.bayern.de/pro/wms/dgm/v1/relief"
                    "?service=wms&version=1.1.1&request=GetMap"
                    "&format=image/tiff&transparent=true"
                    "&layers=by_relief_schraeglicht"
                    "&srs=EPSG:25832"
                    "&STYLES="
                    "&DPI=300&MAP_RESOLUTION=300&FORMAT_OPTIONS=dpi:300"
                    "&WIDTH=5906&HEIGHT=5906"
                    f"&BBOX={int(x)},{int(y)},{int(x+grid_res)},{int(y+grid_res)}"
                )
                
                tiles.append((file_name, url))
                
    return tiles

def download_tiles(tiles, output_dir="downloads_relief"):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    print(f"preparing to download {len(tiles)} tiles...")
    
    def download_one(file_name, url):
        path = os.path.join(output_dir, file_name)
        if os.path.exists(path):
            return "Skipped"

        try:
            resp = requests.get(url, stream=True)
            resp.raise_for_status()
            
            # Simple write without progress bar per file to avoid clutter if many files
            # But user liked progress, so let's stick to simple download and main progress bar
            with open(path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return "Downloaded"
        except Exception as e:
            return f"Error: {e}"

    with ThreadPoolExecutor(max_workers=5) as executor:
        # Wrap with tqdm for overall progress
        futures = {executor.submit(download_one, fname, url): fname for fname, url in tiles}
        
        for future in tqdm(as_completed(futures), total=len(tiles), desc="Downloading Tiles"):
            pass
            
    print("Download complete.")

if __name__ == "__main__":
    # User provided polygon that was "too big"
    # SRID=4326;POLYGON((11.29809649 48.98286661,11.29754709 48.95095144,11.40331032 48.9504143,11.4024862 48.98160878,11.29809649 48.98286661))
    
    # Check for CLI arg, else use default
    if len(sys.argv) > 1:
        poly_input = sys.argv[1]
    else:
        # Default to the "problematic" polygon from user request
        poly_input = "SRID=4326;POLYGON((11.29809649 48.98286661,11.29754709 48.95095144,11.40331032 48.9504143,11.4024862 48.98160878,11.29809649 48.98286661))"
        
    try:
        tiles = generate_tile_urls(poly_input)
        print(f"Generated {len(tiles)} unique tile URLs.")
        download_tiles(tiles)
    except Exception as e:
        print(f"Failed: {e}")
