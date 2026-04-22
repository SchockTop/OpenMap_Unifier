"""Programmatic API for the OpenMap_Unifier downloader.

This module is the "give me coordinates, get tiles back" surface the GUI
eats — but exposed as pure functions so scripts, notebooks, and the test
suite can drive the downloader without touching Tk.

Everything here is a thin wrapper over ``backend.downloader``; no new
business logic lives in here except the ``probe_dataset`` helper, which
HEAD-requests alternative URL layouts so we can figure out the correct
``url_path`` for a dataset whose live layout we haven't confirmed yet.

Typical shell usage:
    python -m backend.api list
    python -m backend.api tile       --dataset dgm1  --east 672  --north 5424
    python -m backend.api urls       --dataset dgm5  --bbox 11.50,48.10,11.52,48.12
    python -m backend.api probe      --dataset dgm1  --east 672  --north 5424
    python -m backend.api download   --dataset dop20 --bbox 11.50,48.10,11.52,48.12 --out-dir downloads_dop20
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Iterable

from shapely.geometry import Polygon, box
from shapely.wkt import loads as loads_wkt

from backend.downloader import (
    BAYERN_DATASETS,
    MapDownloader,
    tile_id_for,
    tile_url_for,
)


# -------- dataset introspection --------------------------------------------

def list_datasets(category: str | None = None, kind: str | None = None) -> dict[str, dict[str, Any]]:
    """Return a filtered copy of the dataset catalog.

    ``category`` filters by category (height, ortho, buildings, laser, wms_render).
    ``kind`` filters by kind ("raw" or "wms").
    """
    out = {}
    for key, meta in BAYERN_DATASETS.items():
        if category and meta.get("category") != category:
            continue
        if kind and meta.get("kind") != kind:
            continue
        out[key] = dict(meta)
    return out


# -------- URL builders ------------------------------------------------------

def tile_url(dataset: str, east_km: int, north_km: int, *, url_path_override: str | None = None) -> str:
    """Return the download URL for one raw-tile at (east_km, north_km).

    Example: ``tile_url("dop20", 672, 5424)`` →
    ``https://download1.bayernwolke.de/a/dop20/data/32672_5424.tif``
    """
    return tile_url_for(dataset, east_km, north_km, url_path_override=url_path_override)


def tile_filename(dataset: str, east_km: int, north_km: int) -> str:
    """Return the tile filename (without URL), e.g. ``32672_5424.tif``."""
    return tile_id_for(dataset, east_km, north_km)


def urls_for_polygon(polygon_wkt: str, dataset: str) -> list[tuple[str, str]]:
    """Return ``[(filename, url), ...]`` for every raw tile intersecting the polygon.

    ``polygon_wkt`` may be plain WKT or EWKT (``SRID=4326;POLYGON(...)``).
    The polygon coordinates are assumed to be EPSG:4326 (lon, lat).
    """
    return MapDownloader().generate_1km_grid_files(polygon_wkt, dataset=dataset)


def urls_for_bbox(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float, dataset: str
) -> list[tuple[str, str]]:
    """Return ``[(filename, url), ...]`` for every raw tile intersecting the bbox (WGS84)."""
    if min_lon >= max_lon or min_lat >= max_lat:
        raise ValueError(
            f"invalid bbox: min_lon/min_lat must be < max_lon/max_lat "
            f"(got {min_lon},{min_lat},{max_lon},{max_lat})"
        )
    poly = Polygon.from_bounds(min_lon, min_lat, max_lon, max_lat)
    return urls_for_polygon(poly.wkt, dataset)


# -------- probe -------------------------------------------------------------

def probe_dataset(
    dataset: str,
    east_km: int,
    north_km: int,
    *,
    candidates: Iterable[str] | None = None,
    timeout: float = 10.0,
    proxy_manager=None,
) -> list[dict[str, Any]]:
    """HEAD-request alternative URL layouts for one known tile.

    Returns a list of ``{url, status, ok, note}`` dicts, one per candidate,
    in the order tried. The first dict with ``ok=True`` is the path that
    should be in ``url_path`` for this dataset.

    ``candidates`` defaults to the dataset's ``probe_candidates`` list (plus
    its current ``url_path`` as a sanity entry).
    """
    meta = BAYERN_DATASETS[dataset]
    if meta.get("kind") != "raw":
        raise ValueError(f"{dataset!r} is not a raw-tile dataset")

    if candidates is None:
        declared = meta.get("probe_candidates", [])
        current = meta.get("url_path")
        # Put the catalog's current url_path first so "the default still works"
        # shows up clearly, then any other probe candidates.
        seen = set()
        ordered = []
        for c in ([current] + list(declared)) if current else list(declared):
            if c and c not in seen:
                ordered.append(c)
                seen.add(c)
        candidates = ordered

    if proxy_manager is None:
        try:
            from backend.proxy_manager import get_proxy_manager
            proxy_manager = get_proxy_manager()
        except Exception:
            proxy_manager = None

    if proxy_manager is not None:
        session = proxy_manager.get_session()
    else:
        import requests
        session = requests.Session()
        session.headers.update({"User-Agent": "OpenMap_Unifier/probe"})

    results: list[dict[str, Any]] = []
    for candidate in candidates:
        url = tile_url(dataset, east_km, north_km, url_path_override=candidate)
        entry: dict[str, Any] = {"url": url, "url_path": candidate}
        try:
            resp = session.head(url, timeout=timeout, allow_redirects=True)
            entry["status"] = resp.status_code
            entry["ok"] = 200 <= resp.status_code < 300
            entry["note"] = resp.reason or ""
        except Exception as e:
            entry["status"] = None
            entry["ok"] = False
            entry["note"] = f"{type(e).__name__}: {e}"
        results.append(entry)
    return results


# -------- download ----------------------------------------------------------

def download_tiles(
    dataset: str,
    *,
    polygon_wkt: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    out_dir: str | None = None,
    progress=None,
    proxy_manager=None,
) -> dict[str, Any]:
    """Download every tile for ``dataset`` that intersects the given polygon or bbox.

    Returns ``{'requested': N, 'ok': M, 'failed': [filenames]}``.
    """
    if (polygon_wkt is None) == (bbox is None):
        raise ValueError("Pass exactly one of polygon_wkt= or bbox=")

    if bbox is not None:
        urls = urls_for_bbox(*bbox, dataset=dataset)
    else:
        urls = urls_for_polygon(polygon_wkt, dataset)

    d = MapDownloader(
        download_dir=out_dir or f"downloads_bayern/{dataset}",
        proxy_manager=proxy_manager,
    )
    failed: list[str] = []
    for fname, url in urls:
        ok = d.download_file(url, fname, progress)
        if not ok:
            failed.append(fname)
    return {"requested": len(urls), "ok": len(urls) - len(failed), "failed": failed}


# -------- CLI ---------------------------------------------------------------

def _parse_bbox(raw: str) -> tuple[float, float, float, float]:
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be 'min_lon,min_lat,max_lon,max_lat'")
    return tuple(float(p) for p in parts)  # type: ignore[return-value]


def _cmd_list(args) -> int:
    data = list_datasets(category=args.category, kind=args.kind)
    print(json.dumps(data, indent=2, default=str))
    return 0


def _cmd_tile(args) -> int:
    url = tile_url(args.dataset, args.east, args.north)
    print(url)
    return 0


def _cmd_urls(args) -> int:
    if args.bbox:
        pairs = urls_for_bbox(*args.bbox, dataset=args.dataset)
    elif args.polygon:
        pairs = urls_for_polygon(args.polygon, args.dataset)
    else:
        print("need --bbox or --polygon", file=sys.stderr)
        return 2
    for fname, url in pairs:
        print(f"{fname}\t{url}")
    print(f"# {len(pairs)} tile(s)", file=sys.stderr)
    return 0


def _cmd_probe(args) -> int:
    results = probe_dataset(args.dataset, args.east, args.north, timeout=args.timeout)
    any_ok = False
    for r in results:
        marker = "OK" if r["ok"] else "XX"
        status = r["status"] if r["status"] is not None else "ERR"
        note = r["note"] if r["note"] else ""
        print(f"  [{marker}] {status:>4}  url_path={r['url_path']!r:<24}  {r['url']}  {note}")
        any_ok = any_ok or r["ok"]
    return 0 if any_ok else 1


def _cmd_download(args) -> int:
    kwargs: dict[str, Any] = {}
    if args.bbox:
        kwargs["bbox"] = args.bbox
    elif args.polygon:
        kwargs["polygon_wkt"] = args.polygon
    else:
        print("need --bbox or --polygon", file=sys.stderr)
        return 2
    kwargs["out_dir"] = args.out_dir
    result = download_tiles(args.dataset, **kwargs)
    print(json.dumps(result, indent=2))
    return 0 if not result["failed"] else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="backend.api")
    sub = p.add_subparsers(dest="cmd", required=True)

    lp = sub.add_parser("list", help="dump the dataset catalog as JSON")
    lp.add_argument("--category")
    lp.add_argument("--kind", choices=["raw", "wms"])
    lp.set_defaults(func=_cmd_list)

    tp = sub.add_parser("tile", help="print the URL for a single (east_km, north_km) tile")
    tp.add_argument("--dataset", required=True)
    tp.add_argument("--east", type=int, required=True, help="easting in km, EPSG:25832")
    tp.add_argument("--north", type=int, required=True, help="northing in km, EPSG:25832")
    tp.set_defaults(func=_cmd_tile)

    up = sub.add_parser("urls", help="list every tile URL intersecting a polygon/bbox")
    up.add_argument("--dataset", required=True)
    up.add_argument("--bbox", type=_parse_bbox, help="min_lon,min_lat,max_lon,max_lat (WGS84)")
    up.add_argument("--polygon", help="WKT / EWKT polygon in WGS84")
    up.set_defaults(func=_cmd_urls)

    pp = sub.add_parser("probe", help="HEAD-test all candidate URL layouts for a dataset")
    pp.add_argument("--dataset", required=True)
    pp.add_argument("--east", type=int, required=True)
    pp.add_argument("--north", type=int, required=True)
    pp.add_argument("--timeout", type=float, default=10.0)
    pp.set_defaults(func=_cmd_probe)

    dp = sub.add_parser("download", help="download all tiles intersecting a polygon/bbox")
    dp.add_argument("--dataset", required=True)
    dp.add_argument("--bbox", type=_parse_bbox)
    dp.add_argument("--polygon")
    dp.add_argument("--out-dir")
    dp.set_defaults(func=_cmd_download)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
