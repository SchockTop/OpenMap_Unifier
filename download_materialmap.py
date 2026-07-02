#!/usr/bin/env python3
"""
Download the full materialmap input stack for an AOI — proxy-aware.

Fetches everything the materialmap classifier pipeline (IR-Unity-Research /
ReadSearch repo) consumes, through the same ProxyManager the GUI uses:

    DGM1         bare-earth height, 1 m GeoTIFF        (raw bayernwolke tiles)
    DOM20        surface model, 20 cm GeoTIFF          (raw bayernwolke tiles)
                 -> nDSM = DOM20 - DGM1
    DOP20 CIR    near-infrared orthophoto (WMS render)
    DOP20        raw RGB orthophoto (optional, ~300 MB/tile)
    Laser        raw LiDAR point cloud LAZ (optional, ~800 MB/tile)

For Sentinel-2 (real SWIR) use download_sentinel2.py.

Usage:
    python download_materialmap.py "POLYGON((11.53 48.09, 11.58 48.09, 11.58 48.12, 11.53 48.12, 11.53 48.09))"
    python download_materialmap.py region.wkt --datasets dgm1 dom20 dop20cir_wms laser
    # the P53 bulk-Bayern footprint, written in the layout materialmap expects
    # (datasets/bayern_ndsm/dom20_<e>_<n>.tif / dgm1_<e>_<n>.tif):
    python download_materialmap.py --km-tiles "689,5333 690,5333 691,5333" \
        --materialmap-layout --out ../ReadSearch/research_bot/materialmap/datasets

Proxy: saved proxy_config.json is loaded automatically (configure once via the
GUI's proxy dialog, or pass --proxy). --test checks connectivity and exits.
"""
import argparse
import os
import re
import shutil
import sys

from backend.downloader import MapDownloader, BAYERN_DATASETS
from backend.proxy_manager import get_proxy_manager

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_DATASETS = ["dgm1", "dom20", "dop20cir_wms"]
RAW_CHOICES = [k for k, m in BAYERN_DATASETS.items() if m.get("kind") == "raw"]
WMS_CHOICES = [k for k, m in BAYERN_DATASETS.items() if m.get("kind") == "wms"]

# materialmap's exp_p05/bulk scripts read km-tile heights from
# datasets/bayern_ndsm/{dom20,dgm1}_<east>_<north>.tif
MATERIALMAP_RENAMES = {
    "dgm1": (re.compile(r"^(\d{3})_(\d{4})\.tif$"), "dgm1_{e}_{n}.tif"),
    "dom20": (re.compile(r"^32(\d{3})_(\d{4})_20_DOM\.tif$"), "dom20_{e}_{n}.tif"),
}


def read_polygon(arg: str) -> str:
    if os.path.isfile(arg):
        return open(arg, "r", encoding="utf-8").read().strip()
    return arg


def km_tiles_to_polygon(spec: str) -> str:
    """WGS84 WKT for a set of 1 km tiles ("689,5333 690,5333").

    The km box is inset by 1 m so grid snapping + reprojection round-trip
    cannot pull in edge-touching neighbour tiles.
    """
    from pyproj import Transformer

    tiles = []
    for part in spec.replace(";", " ").split():
        e, n = part.split(",")
        tiles.append((int(e), int(n)))
    if not tiles:
        raise ValueError("--km-tiles is empty")
    minx = min(e for e, _ in tiles) * 1000 + 1
    miny = min(n for _, n in tiles) * 1000 + 1
    maxx = (max(e for e, _ in tiles) + 1) * 1000 - 1
    maxy = (max(n for _, n in tiles) + 1) * 1000 - 1
    tr = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)
    corners = [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy), (minx, miny)]
    pts = ", ".join(f"{lon:.7f} {lat:.7f}" for lon, lat in (tr.transform(x, y) for x, y in corners))
    return f"POLYGON(({pts}))"


def build_proxy_manager(args):
    pm = get_proxy_manager(config_dir=SCRIPT_DIR)  # loads saved proxy_config.json
    cfg = pm.config
    if args.proxy:
        cfg.enabled = True
        cfg.auto_detect = False
        cfg.proxy_url = args.proxy
        if args.proxy_user:
            cfg.auth_type = "basic"
            cfg.username = args.proxy_user
            cfg.password = args.proxy_password or ""
    elif cfg.auto_detect or (not cfg.enabled and not cfg.proxy_url):
        pm.auto_detect()  # same rule as the GUI: don't clobber a saved manual config
    if args.ca_bundle:
        cfg.ca_bundle_path = args.ca_bundle
    if args.no_verify:
        cfg.ssl_verify = False
    return pm


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("polygon", nargs="?",
                   help="WKT polygon string OR path to a .wkt file (EPSG:4326 lon/lat)")
    p.add_argument("--km-tiles",
                   help='explicit 1 km tiles instead of a polygon: "689,5333 690,5333"')
    p.add_argument("--datasets", nargs="+", default=list(DEFAULT_DATASETS),
                   choices=sorted(set(RAW_CHOICES + WMS_CHOICES)),
                   help=f"default: {' '.join(DEFAULT_DATASETS)}")
    p.add_argument("--out", default="downloads_materialmap",
                   help="output root (one subfolder per dataset)")
    p.add_argument("--materialmap-layout", action="store_true",
                   help="rename DGM1/DOM20 tiles into <out>/bayern_ndsm/ as "
                        "dgm1_<e>_<n>.tif / dom20_<e>_<n>.tif (what the "
                        "materialmap scripts read)")
    p.add_argument("--proxy", help="proxy URL, e.g. http://proxy.corp:8080 "
                                   "(otherwise saved config / auto-detect)")
    p.add_argument("--proxy-user")
    p.add_argument("--proxy-password")
    p.add_argument("--ca-bundle", help=".pem for TLS-inspecting proxies")
    p.add_argument("--no-verify", action="store_true", help="skip TLS verification (last resort)")
    p.add_argument("--test", action="store_true", help="test proxy connectivity and exit")
    args = p.parse_args(argv)

    pm = build_proxy_manager(args)
    if args.test:
        results = pm.test_connections()
        ok = all(r.get("success") for r in results.values()) if isinstance(results, dict) else bool(results)
        for name, r in (results.items() if isinstance(results, dict) else []):
            print(f"  {name}: {'OK' if r.get('success') else r.get('message', 'FAILED')}")
        return 0 if ok else 1

    if args.km_tiles:
        wkt = km_tiles_to_polygon(args.km_tiles)
        print(f"[INFO] km-tiles -> {wkt}")
    elif args.polygon:
        wkt = read_polygon(args.polygon)
    else:
        p.error("give a polygon (WKT/.wkt file) or --km-tiles")

    downloader = MapDownloader(download_dir=args.out, proxy_manager=pm)
    failed = 0
    for ds in args.datasets:
        meta = BAYERN_DATASETS[ds]
        ds_dir = os.path.join(args.out, ds)
        os.makedirs(ds_dir, exist_ok=True)
        downloader.download_dir = ds_dir
        if meta.get("kind") == "raw":
            files = downloader.generate_1km_grid_files(wkt, dataset=ds)
        else:
            files = downloader.generate_wms_tiles(wkt, dataset=ds)
        est = meta.get("avg_tile_mb")
        est_txt = f" (~{est * len(files)} MB)" if est else ""
        print(f"[INFO] {ds}: {len(files)} tile(s){est_txt} -> {ds_dir}")
        for file_name, url in files:
            if not downloader.download_file(url, file_name):
                failed += 1

    if args.materialmap_layout:
        ndsm_dir = os.path.join(args.out, "bayern_ndsm")
        os.makedirs(ndsm_dir, exist_ok=True)
        moved = 0
        for ds, (pattern, template) in MATERIALMAP_RENAMES.items():
            ds_dir = os.path.join(args.out, ds)
            if not os.path.isdir(ds_dir):
                continue
            for name in sorted(os.listdir(ds_dir)):
                m = pattern.match(name)
                if not m:
                    continue
                dest = os.path.join(ndsm_dir, template.format(e=m.group(1), n=m.group(2)))
                if not os.path.exists(dest):
                    shutil.copy2(os.path.join(ds_dir, name), dest)
                moved += 1
        print(f"[INFO] materialmap layout: {moved} height tile(s) -> {ndsm_dir}")

    if failed:
        print(f"[ERROR] {failed} download(s) failed.")
        return 1
    print("[OK] all downloads complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
