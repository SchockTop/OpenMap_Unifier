"""
Worldfile / .prj generator for Bayern Open Data raw tiles.

Bayern's raw GeoTIFFs (DGM1, DGM5, DOP20, DOP40) historically ship without
internal GeoTIFF georef tags, which breaks Blender GIS batch import with:

    IOError: Unable to read georef infos from worldfile or geotiff tags

The tile IDs themselves encode the position in EPSG:25832. The format is:

    32<east_km>_<north_km>.<ext>        e.g. "32672_5424.tif"

where east_km = easting in kilometres (3 digits), north_km = northing in
kilometres (4 digits). The tile covers a 1 km x 1 km square. Combined with
the dataset-specific pixel size, that's everything needed for a worldfile.

Writing a ``.tfw`` sidecar + a ``.prj`` with the EPSG:25832 WKT makes every
raw tile readable by Blender GIS, QGIS, GDAL, etc. without any other tooling.
"""

import os
import re

# Official WKT for EPSG:25832 (ETRS89 / UTM zone 32N) — stable, used by GDAL.
EPSG_25832_WKT = (
    'PROJCS["ETRS89 / UTM zone 32N",'
    'GEOGCS["ETRS89",DATUM["European_Terrestrial_Reference_System_1989",'
    'SPHEROID["GRS 1980",6378137,298.257222101]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
    'PROJECTION["Transverse_Mercator"],'
    'PARAMETER["latitude_of_origin",0],'
    'PARAMETER["central_meridian",9],'
    'PARAMETER["scale_factor",0.9996],'
    'PARAMETER["false_easting",500000],'
    'PARAMETER["false_northing",0],'
    'UNIT["metre",1],AXIS["Easting",EAST],AXIS["Northing",NORTH],'
    'AUTHORITY["EPSG","25832"]]'
)

_TILE_ID_RE = re.compile(r"^32(\d{3})_(\d{4})$")


def parse_tile_id(filename):
    """Given e.g. '32672_5424.tif' return (east_km=672, north_km=5424) or None."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    m = _TILE_ID_RE.match(stem)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def tfw_path_for(tif_path):
    """Return the .tfw path alongside a .tif (or .tiff)."""
    base, _ = os.path.splitext(tif_path)
    return base + ".tfw"


def prj_path_for(tif_path):
    base, _ = os.path.splitext(tif_path)
    return base + ".prj"


def write_worldfile(tif_path, pixel_size_m, top_left_x, top_left_y):
    """
    Write a standard .tfw worldfile next to `tif_path`.

    Worldfile lines (see ESRI spec):
      1: pixel width in x
      2: rotation about y axis
      3: rotation about x axis
      4: pixel height in y (negative — origin is top-left)
      5: x coordinate of upper-left pixel CENTRE
      6: y coordinate of upper-left pixel CENTRE
    """
    # ESRI convention: worldfile references the CENTRE of the upper-left pixel,
    # not the corner. Shift by half a pixel.
    cx = top_left_x + pixel_size_m / 2.0
    cy = top_left_y - pixel_size_m / 2.0
    out = tfw_path_for(tif_path)
    with open(out, "w", encoding="ascii", newline="\n") as f:
        f.write(f"{pixel_size_m}\n")
        f.write("0.0\n")
        f.write("0.0\n")
        f.write(f"-{pixel_size_m}\n")
        f.write(f"{cx}\n")
        f.write(f"{cy}\n")
    return out


def write_prj(tif_path, wkt=EPSG_25832_WKT):
    """Write the companion .prj (EPSG:25832 WKT)."""
    out = prj_path_for(tif_path)
    with open(out, "w", encoding="ascii") as f:
        f.write(wkt)
    return out


def write_sidecars_for_bayern_tile(tif_path, pixel_size_m):
    """
    Generate .tfw + .prj for a Bayern raw tile based on its filename.

    Returns (tfw_path, prj_path) or (None, None) if the filename doesn't
    match the `32<east_km>_<north_km>` scheme.
    """
    parsed = parse_tile_id(tif_path)
    if not parsed:
        return None, None
    east_km, north_km = parsed
    # Tile is 1 km x 1 km. Top-left corner = (east_km*1000, (north_km+1)*1000).
    top_left_x = east_km * 1000.0
    top_left_y = (north_km + 1) * 1000.0
    tfw = write_worldfile(tif_path, pixel_size_m, top_left_x, top_left_y)
    prj = write_prj(tif_path)
    return tfw, prj


def generate_for_folder(folder, pixel_size_m, extensions=(".tif", ".tiff")):
    """
    Walk `folder` and generate .tfw + .prj for every matching Bayern raw tile.

    Returns (count_generated, count_skipped_not_matching).
    """
    generated = 0
    skipped = 0
    if not os.path.isdir(folder):
        return 0, 0
    for root, _, files in os.walk(folder):
        for f in files:
            if not f.lower().endswith(extensions):
                continue
            path = os.path.join(root, f)
            tfw, _ = write_sidecars_for_bayern_tile(path, pixel_size_m)
            if tfw:
                generated += 1
            else:
                skipped += 1
    return generated, skipped
