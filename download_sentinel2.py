#!/usr/bin/env python3
"""
Download Sentinel-2 satellite imagery (incl. real SHORT-WAVE INFRARED / SWIR)
for a drawn polygon — the band Bavaria's aerial DOP does not provide.

Source: public AWS Earth-Search STAC + sentinel-cogs S3 (no login / no API key /
no Hugging Face — works behind a corporate proxy). With rasterio installed each
band is cropped to the polygon; otherwise the whole tile is downloaded.

Usage:
    python download_sentinel2.py "POLYGON((11.55 48.12, 11.57 48.12, 11.57 48.14, 11.55 48.14, 11.55 48.12))"
    python download_sentinel2.py region.wkt --bands red green blue nir swir16 swir22 \
        --date 2023-06-01/2023-09-30 --max-cloud 15 --out downloads_sentinel2 --indices
"""
import argparse
import os
import sys

from backend.sentinel2_downloader import (
    Sentinel2Downloader, compute_index, INDEX_FORMULAS, DEFAULT_BANDS,
)


def read_polygon(arg: str) -> str:
    if os.path.isfile(arg):
        return open(arg, "r", encoding="utf-8").read().strip()
    return arg


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("polygon", help="WKT polygon string OR path to a .wkt file (EPSG:4326 lon/lat)")
    p.add_argument("--bands", nargs="+", default=list(DEFAULT_BANDS),
                   help=f"asset keys (default: {' '.join(DEFAULT_BANDS)}); swir16=B11, swir22=B12")
    p.add_argument("--date", default="2023-06-01/2023-09-30", help="YYYY-MM-DD/YYYY-MM-DD")
    p.add_argument("--max-cloud", type=float, default=20.0)
    p.add_argument("--max-size", type=int, default=2048, help="downsample long edge to this many px")
    p.add_argument("--out", default="downloads_sentinel2")
    p.add_argument("--indices", action="store_true", help="also compute NDVI/NDBI/MNDWI/NBR/NDMI as .tif")
    args = p.parse_args(argv)

    wkt = read_polygon(args.polygon)
    dl = Sentinel2Downloader(download_dir=args.out)
    items = dl.search(wkt, date_range=args.date, max_cloud=args.max_cloud, limit=5)
    if not items:
        print("[ERROR] No Sentinel-2 scenes found for that polygon/date/cloud filter.")
        return 1
    item = items[0]
    cc = item["properties"].get("eo:cloud_cover", "?")
    print(f"[INFO] best scene: {item['id']}  cloud={cc}%  date={item['properties'].get('datetime','?')}")

    def cb(name, pct, status, *_):
        print(f"  {name}: {status}")

    bands = dl.download_bands(item, wkt, bands=args.bands, max_size=args.max_size, progress_callback=cb)
    print(f"[OK] downloaded {len(bands)} band(s) -> {args.out}")

    if args.indices:
        try:
            import rasterio
        except Exception:
            print("[WARN] --indices needs rasterio; skipping.")
            return 0
        have = set(bands)
        for name, needed in {"ndvi": {"nir", "red"}, "ndbi": {"swir16", "nir"},
                             "mndwi": {"green", "swir16"}, "nbr": {"nir", "swir22"},
                             "ndmi": {"nir", "swir16"}}.items():
            if needed <= have:
                arr = compute_index(bands, name)
                ref = bands[next(iter(needed))]
                with rasterio.open(ref) as s:
                    prof = s.profile.copy()
                prof.update(dtype="float32", count=1,
                            height=arr.shape[0], width=arr.shape[1])
                out = os.path.join(args.out, f"{item['id']}_{name}.tif")
                with rasterio.open(out, "w", **prof) as d:
                    d.write(arr.astype("float32"), 1)
                print(f"  index {name} -> {os.path.basename(out)}  ({INDEX_FORMULAS[name].split('#')[0].strip()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
