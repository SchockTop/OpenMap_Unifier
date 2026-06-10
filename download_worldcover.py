#!/usr/bin/env python3
"""
Download ESA WorldCover 10 m land-cover (11 classes, 2021) for a drawn polygon —
free weak labels for training (built-up / tree / grass / water / crop / bare ...).

Source: public ESA WorldCover S3 (no login / no API key / no Hugging Face). With
rasterio the tile is cropped to the polygon; otherwise the ~100 MB tile is fetched
whole.

Usage:
    python download_worldcover.py "POLYGON((11.55 48.12, 11.57 48.12, 11.57 48.14, 11.55 48.14, 11.55 48.12))"
    python download_worldcover.py region.wkt --out downloads_worldcover --hist
"""
import argparse
import os
import sys

from backend.worldcover_downloader import WorldCoverDownloader


def read_polygon(arg: str) -> str:
    if os.path.isfile(arg):
        return open(arg, "r", encoding="utf-8").read().strip()
    return arg


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("polygon", help="WKT polygon string OR path to a .wkt file (EPSG:4326 lon/lat)")
    p.add_argument("--out", default="downloads_worldcover")
    p.add_argument("--max-size", type=int, default=4096)
    p.add_argument("--hist", action="store_true", help="print the land-cover class histogram")
    args = p.parse_args(argv)

    wkt = read_polygon(args.polygon)
    dl = WorldCoverDownloader(download_dir=args.out)

    def cb(name, pct, status, *_):
        print(f"  {name}: {status}")

    path = dl.fetch(wkt, max_size=args.max_size, progress_callback=cb)
    print(f"[OK] WorldCover -> {path}")
    if args.hist:
        try:
            print("[INFO] land-cover classes:", dl.class_histogram(path))
        except Exception as e:
            print(f"[WARN] could not read histogram (needs rasterio): {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
