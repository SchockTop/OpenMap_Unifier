"""
OSM Downloader — downloads OpenStreetMap data via Overpass API.

Usage:
    downloader = OSMDownloader(download_dir="downloads_osm")
    bbox = downloader.calculate_bbox(polygon_wkt, buffer_meters=500)
    results = downloader.download_selected(polygon_wkt, ["Roads & Paths", "Buildings"], buffer_meters=500)
"""

import json
import math
import os
import time

import requests
from pyproj import Transformer


# ---------------------------------------------------------------------------
# Layer definitions
# ---------------------------------------------------------------------------

LAYERS = {
    "Roads & Paths": {
        "description": "Roads, streets, footpaths, cycleways",
        "query_parts": [
            'way["highway"]{bbox}',
            'relation["highway"]{bbox}',
        ],
        "fg_color": "#e67e22",
    },
    "Buildings": {
        "description": "Building footprints (includes height / level tags for 3D)",
        "query_parts": [
            'way["building"]{bbox}',
            'relation["building"]{bbox}',
        ],
        "fg_color": "#8e44ad",
    },
    "Land Use": {
        "description": "Residential, industrial, forest, farmland, parks, leisure",
        "query_parts": [
            'way["landuse"]{bbox}',
            'relation["landuse"]{bbox}',
            'way["leisure"]{bbox}',
            'relation["leisure"]{bbox}',
        ],
        "fg_color": "#27ae60",
    },
    "Water": {
        "description": "Rivers, streams, canals, lakes, reservoirs",
        "query_parts": [
            'way["waterway"]{bbox}',
            'relation["waterway"]{bbox}',
            'way["natural"="water"]{bbox}',
            'relation["natural"="water"]{bbox}',
            'node["natural"="water"]{bbox}',
        ],
        "fg_color": "#2980b9",
    },
    "Natural Features": {
        "description": "Forests, cliffs, rocks, beaches, wetlands, vegetation",
        "query_parts": [
            'node["natural"]{bbox}',
            'way["natural"]{bbox}',
            'relation["natural"]{bbox}',
        ],
        "fg_color": "#16a085",
    },
    "Amenities & POI": {
        "description": "Restaurants, hospitals, schools, parking, shops, tourism",
        "query_parts": [
            'node["amenity"]{bbox}',
            'way["amenity"]{bbox}',
            'node["shop"]{bbox}',
            'node["tourism"]{bbox}',
            'way["tourism"]{bbox}',
        ],
        "fg_color": "#e74c3c",
    },
    "Public Transport": {
        "description": "Bus stops, train stations, railway lines, tram, subway",
        "query_parts": [
            'node["public_transport"]{bbox}',
            'way["railway"]{bbox}',
            'node["railway"]{bbox}',
            'relation["route"~"bus|train|tram|subway|rail"]{bbox}',
        ],
        "fg_color": "#f39c12",
    },
    "Administrative": {
        "description": "City, district and municipality boundaries",
        "query_parts": [
            'relation["boundary"="administrative"]{bbox}',
        ],
        "fg_color": "#7f8c8d",
    },
}

# Layer display order
LAYER_ORDER = [
    "Roads & Paths",
    "Buildings",
    "Land Use",
    "Water",
    "Natural Features",
    "Amenities & POI",
    "Public Transport",
    "Administrative",
]

# Default selected layers
DEFAULT_LAYERS = {"Roads & Paths", "Buildings", "Land Use", "Water"}

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Mirror endpoints used as fallbacks when the primary rejects the request
# (e.g. 406 Not Acceptable from a CDN / upstream proxy, or 5xx outages).
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]

# HTTP status codes that should trigger a retry (either same endpoint or mirror).
# 406 = Not Acceptable (usually missing/unsupported Accept header upstream)
# 429 = Too Many Requests, 502/503/504 = transient gateway issues
# 407 is intentionally NOT retryable — it means the local proxy rejected our
# credentials, so hitting another Overpass mirror won't help.
RETRYABLE_STATUS = {406, 408, 429, 500, 502, 503, 504}

# Supported output formats.
# Key = internal id, value = (display label, file extension, Overpass [out:] type)
OUTPUT_FORMATS = {
    "geojson": ("GeoJSON (.geojson)", "geojson", "json"),
    "osm":     ("OSM XML (.osm)",     "osm",     "xml"),
}
DEFAULT_OUTPUT_FORMAT = "geojson"


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class OSMDownloader:

    def __init__(self, download_dir="downloads_osm", proxy_manager=None,
                 output_format=DEFAULT_OUTPUT_FORMAT):
        self.download_dir = download_dir
        os.makedirs(download_dir, exist_ok=True)
        self.proxy_manager = proxy_manager
        self.stop_event = False
        self._session = None
        self.output_format = output_format if output_format in OUTPUT_FORMATS else DEFAULT_OUTPUT_FORMAT

    # ------------------------------------------------------------------
    # Session / proxy
    # ------------------------------------------------------------------

    def _get_session(self):
        # Always re-fetch from the proxy manager so that proxy settings changed
        # in the UI (auto-detect, manual update, disable) take effect on the
        # next download without needing an app restart.
        if self.proxy_manager:
            session = self.proxy_manager.get_session()
            if session is not self._session:
                self._session = session
        elif self._session is None:
            self._session = requests.Session()

        # Always enforce a standards-compliant User-Agent. Some Overpass
        # mirrors / upstream CDNs reject requests with missing or unusual
        # User-Agent strings (seen as HTTP 406 or 403).
        self._session.headers.update({
            "User-Agent": "OpenMapUnifier/1.0 (+https://github.com/schocktop/openmap_unifier)",
        })
        return self._session

    @staticmethod
    def _request_headers(out_type):
        """Build per-request headers matching the requested Overpass output format.

        Overpass dispatchers / CDNs occasionally return 406 Not Acceptable when
        the Accept header is absent or doesn't match the [out:...] format in
        the query, so we always send an explicit Accept.
        """
        if out_type == "xml":
            accept = "application/osm3s+xml, application/xml;q=0.9, */*;q=0.1"
        else:
            accept = "application/json, */*;q=0.1"
        return {
            "Accept": accept,
            "Accept-Encoding": "gzip, deflate",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        }

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def calculate_bbox(self, polygon_wkt, buffer_meters=0):
        """
        Parse polygon WKT (EWKT or plain WKT) and return
        (south, west, north, east) bounding box.

        Optionally expand by buffer_meters in every direction (UTM-based).
        """
        coords_str = polygon_wkt.strip()
        if ";" in coords_str:
            coords_str = coords_str.split(";", 1)[1].strip()

        start = coords_str.index("((") + 2
        end = coords_str.rindex("))")
        inner = coords_str[start:end]

        pairs = [p.strip().split() for p in inner.split(",") if p.strip()]
        lons = [float(p[0]) for p in pairs if len(p) >= 2]
        lats = [float(p[1]) for p in pairs if len(p) >= 2]

        if not lons or not lats:
            raise ValueError("Could not parse coordinates from polygon WKT")

        minlon, maxlon = min(lons), max(lons)
        minlat, maxlat = min(lats), max(lats)

        if buffer_meters > 0:
            to_utm = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
            to_wgs = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)

            x_min, y_min = to_utm.transform(minlon, minlat)
            x_max, y_max = to_utm.transform(maxlon, maxlat)

            x_min -= buffer_meters
            y_min -= buffer_meters
            x_max += buffer_meters
            y_max += buffer_meters

            minlon, minlat = to_wgs.transform(x_min, y_min)
            maxlon, maxlat = to_wgs.transform(x_max, y_max)

        # Overpass convention: south, west, north, east
        return (minlat, minlon, maxlat, maxlon)

    def estimate_area_km2(self, bbox):
        """Rough bounding-box area in km² (good enough for timeout estimation)."""
        south, west, north, east = bbox
        lat_mid = (south + north) / 2
        km_per_deg_lon = 111.32 * math.cos(math.radians(lat_mid))
        km_per_deg_lat = 111.32
        width = (east - west) * km_per_deg_lon
        height = (north - south) * km_per_deg_lat
        return max(0.0, width * height)

    # ------------------------------------------------------------------
    # Overpass query builder
    # ------------------------------------------------------------------

    def _timeout_for_area(self, area_km2):
        if area_km2 < 25:
            return 45
        if area_km2 < 200:
            return 90
        if area_km2 < 1000:
            return 180
        return 300

    def build_query(self, layer_name, bbox, out_type="json"):
        """
        Build an Overpass QL query string for *layer_name* within *bbox*.
        `out_type` is either "json" (→ GeoJSON pipeline) or "xml" (→ native .osm).
        Returns (query_str, timeout_seconds).
        """
        south, west, north, east = bbox
        bbox_str = f"({south:.6f},{west:.6f},{north:.6f},{east:.6f})"

        area_km2 = self.estimate_area_km2(bbox)
        timeout = self._timeout_for_area(area_km2)

        parts = LAYERS[layer_name]["query_parts"]
        inner = ";\n  ".join(p.replace("{bbox}", bbox_str) for p in parts)

        if out_type == "xml":
            # Standard OSM XML: recurse-down ("(._;>;);") so referenced nodes
            # are included. Produces files compatible with JOSM, Train3D, etc.
            query = (
                f"[out:xml][timeout:{timeout}];\n"
                f"(\n  {inner};\n);\n"
                f"(._;>;);\n"
                f"out meta;"
            )
        else:
            query = f"[out:json][timeout:{timeout}];\n(\n  {inner};\n);\nout geom;"

        return query, timeout

    # ------------------------------------------------------------------
    # Overpass → GeoJSON conversion
    # ------------------------------------------------------------------

    def overpass_to_geojson(self, data, layer_name=""):
        """Convert an Overpass API JSON response dict to a GeoJSON FeatureCollection."""
        features = []
        for element in data.get("elements", []):
            feature = self._element_to_feature(element)
            if feature is not None:
                features.append(feature)
        return {
            "type": "FeatureCollection",
            "name": layer_name,
            "features": features,
        }

    def _element_to_feature(self, element):
        etype = element.get("type")
        tags = element.get("tags", {})
        props = {"osm_id": element.get("id"), "osm_type": etype}
        props.update(tags)

        try:
            if etype == "node":
                if "lat" not in element or "lon" not in element:
                    return None
                geom = {
                    "type": "Point",
                    "coordinates": [element["lon"], element["lat"]],
                }

            elif etype == "way":
                pts = element.get("geometry", [])
                if len(pts) < 2:
                    return None
                coords = [[pt["lon"], pt["lat"]] for pt in pts]
                # Closed ring (4+ unique points + closing point) → Polygon
                if len(coords) >= 4 and coords[0] == coords[-1]:
                    geom = {"type": "Polygon", "coordinates": [coords]}
                else:
                    geom = {"type": "LineString", "coordinates": coords}

            elif etype == "relation":
                outer_rings, inner_rings = [], []
                for member in element.get("members", []):
                    if member.get("type") != "way":
                        continue
                    pts = member.get("geometry", [])
                    if not pts:
                        continue
                    coords = [[pt["lon"], pt["lat"]] for pt in pts]
                    if member.get("role") == "inner":
                        inner_rings.append(coords)
                    else:
                        outer_rings.append(coords)

                if not outer_rings:
                    return None

                if len(outer_rings) == 1:
                    geom = {
                        "type": "Polygon",
                        "coordinates": [outer_rings[0]] + inner_rings,
                    }
                else:
                    geom = {
                        "type": "MultiPolygon",
                        "coordinates": [[ring] for ring in outer_rings],
                    }

            else:
                return None

            return {"type": "Feature", "geometry": geom, "properties": props}

        except Exception:
            return None

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_layer(self, layer_name, bbox, progress_callback=None):
        """
        Download one OSM layer via Overpass and save as GeoJSON.

        progress_callback(layer_name, percent:int, status:str, speed:str, eta:str)

        Returns (success: bool, filepath_or_error: str).
        """
        if self.stop_event:
            return False, "Cancelled"

        safe = (
            layer_name.lower()
            .replace(" ", "_")
            .replace("&", "and")
            .replace("/", "_")
        )

        fmt_key = self.output_format if self.output_format in OUTPUT_FORMATS else DEFAULT_OUTPUT_FORMAT
        _label, file_ext, out_type = OUTPUT_FORMATS[fmt_key]
        out_file = os.path.join(self.download_dir, f"{safe}.{file_ext}")

        if os.path.exists(out_file):
            if progress_callback:
                progress_callback(layer_name, 100, "Skipped (exists)", "-", "-")
            return True, out_file

        def cb(pct, status, speed="-", eta="-"):
            if progress_callback:
                progress_callback(layer_name, pct, status, speed, eta)

        cb(5, "Building query...")

        query, timeout = self.build_query(layer_name, bbox, out_type=out_type)
        area_km2 = self.estimate_area_km2(bbox)
        cb(10, f"Querying Overpass ({area_km2:.0f} km2)...")

        t0 = time.time()
        try:
            session = self._get_session()
            headers = self._request_headers(out_type)

            # Try the primary endpoint, then mirrors, with back-off on
            # transient / upstream errors (including 406 Not Acceptable).
            endpoints = list(dict.fromkeys([OVERPASS_URL, *OVERPASS_MIRRORS]))
            max_attempts_per_endpoint = 2
            response = None
            last_status = None
            last_error = None

            for ep_index, endpoint in enumerate(endpoints):
                for attempt in range(1, max_attempts_per_endpoint + 1):
                    if self.stop_event:
                        cb(0, "Cancelled")
                        return False, "Cancelled"
                    try:
                        # verify / CA bundle / proxy auth all inherited from
                        # the proxy_manager session.
                        response = session.post(
                            endpoint,
                            data={"data": query},
                            headers=headers,
                            timeout=timeout + 60,
                            stream=True,
                        )
                    except requests.exceptions.RequestException as e:
                        last_error = e
                        response = None
                        print(f"[OSM] {layer_name}: network error on {endpoint}: {e}")
                        break  # try next mirror

                    last_status = response.status_code
                    if response.status_code < 400:
                        break  # success

                    if response.status_code in RETRYABLE_STATUS:
                        # Drain and close so the connection can be reused.
                        try:
                            response.close()
                        except Exception:
                            pass

                        is_last_endpoint = ep_index == len(endpoints) - 1
                        is_last_attempt = attempt == max_attempts_per_endpoint
                        if is_last_endpoint and is_last_attempt:
                            break  # give up, will raise_for_status below

                        wait = 3 * attempt
                        host = endpoint.split("/")[2]
                        cb(
                            10,
                            f"HTTP {response.status_code} from {host}, "
                            f"retrying ({attempt}/{max_attempts_per_endpoint})...",
                        )
                        print(
                            f"[OSM] {layer_name}: HTTP {response.status_code} "
                            f"from {endpoint}, waiting {wait}s (attempt {attempt})"
                        )
                        time.sleep(wait)
                        continue

                    # Non-retryable 4xx → stop immediately
                    break

                if response is not None and response.status_code < 400:
                    break  # don't try further mirrors

            if response is None:
                # All endpoints failed with network errors
                raise last_error if last_error else requests.exceptions.RequestException(
                    "No response from any Overpass endpoint"
                )

            response.raise_for_status()

            chunks = []
            total_bytes = 0
            for chunk in response.iter_content(chunk_size=65536):
                if self.stop_event:
                    cb(0, "Cancelled")
                    return False, "Cancelled"
                if chunk:
                    chunks.append(chunk)
                    total_bytes += len(chunk)
                    elapsed = time.time() - t0
                    mb = total_bytes / 1_048_576
                    speed = f"{mb/elapsed:.1f} MB/s" if elapsed > 0.1 else "-"
                    cb(30, f"Receiving... {mb:.1f} MB", speed)

            raw = b"".join(chunks)
            cb(70, "Parsing response...")

            if fmt_key == "osm":
                text = raw.decode("utf-8", errors="replace")
                lo = text.lower()
                if "runtime error" in lo and ("out of memory" in lo or "timeout" in lo):
                    msg = "Server error: runtime out-of-memory or timeout"
                    cb(0, msg)
                    return False, msg

                cb(90, "Saving OSM XML...")
                with open(out_file, "w", encoding="utf-8") as f:
                    f.write(text)

                elapsed_total = time.time() - t0
                size_mb = os.path.getsize(out_file) / 1_048_576
                cb(
                    100,
                    f"Done — {size_mb:.1f} MB OSM XML",
                    f"{elapsed_total:.1f}s",
                    "-",
                )
                print(
                    f"[OSM] {layer_name}: {size_mb:.2f} MB OSM XML "
                    f"({elapsed_total:.1f}s) -> {out_file}"
                )
                return True, out_file

            data = json.loads(raw.decode("utf-8"))

            remark = data.get("remark", "")
            if remark:
                lo = remark.lower()
                if "out of memory" in lo or "timeout" in lo:
                    msg = f"Server error: {remark[:120]}"
                    cb(0, msg)
                    return False, msg

            cb(80, "Converting to GeoJSON...")
            geojson = self.overpass_to_geojson(data, layer_name)
            count = len(geojson["features"])

            cb(90, f"Saving {count} features...")
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(geojson, f, ensure_ascii=False, separators=(",", ":"))

            elapsed_total = time.time() - t0
            size_mb = os.path.getsize(out_file) / 1_048_576
            cb(
                100,
                f"Done — {count} features, {size_mb:.1f} MB",
                f"{elapsed_total:.1f}s",
                "-",
            )
            print(
                f"[OSM] {layer_name}: {count} features, {size_mb:.2f} MB "
                f"({elapsed_total:.1f}s) -> {out_file}"
            )
            return True, out_file

        except requests.exceptions.Timeout:
            msg = "Timed out — try a smaller area"
            cb(0, msg)
            return False, msg
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            detail = ""
            try:
                body = (e.response.text or "")[:200].strip().replace("\n", " ")
                if body:
                    detail = f" — {body}"
            except Exception:
                pass

            hints = {
                400: "Invalid Overpass query",
                403: "Blocked by server — check proxy / User-Agent",
                404: "Endpoint not found",
                406: "Server rejected Accept header — all Overpass mirrors failed",
                407: ("Proxy rejected credentials — open Proxy Settings, "
                      "re-enter username/password (NTLM users: try Basic "
                      "auth or run a local cntlm relay)"),
                413: "Query too large — reduce area or buffer",
                429: "Rate-limited — wait a moment and retry",
                504: "Server timed out — try a smaller area",
            }
            hint = hints.get(code, "Server error")
            msg = f"HTTP {code}: {hint}{detail}"
            cb(0, msg)
            print(f"[OSM] {layer_name}: {msg}")
            # On 407 print a non-secret diagnostic snapshot so the user can
            # see exactly what proxy/auth/env state was in effect.
            if code == 407 and self.proxy_manager:
                try:
                    self.proxy_manager.diagnose()
                except Exception:
                    pass
            return False, msg
        except json.JSONDecodeError as e:
            msg = f"Bad server response: {e}"
            cb(0, msg)
            return False, msg
        except requests.exceptions.RequestException as e:
            # Use unified classifier from proxy_manager when available,
            # so OSM errors read the same as Bayern downloads.
            if self.proxy_manager and hasattr(self.proxy_manager, "classify_error"):
                try:
                    code, user_msg = self.proxy_manager.classify_error(e)
                    msg = f"[{code}] {user_msg}"
                except Exception:
                    msg = f"Network error: {e}"
            else:
                msg = f"Network error: {e}"
            print(f"[OSM] {layer_name}: {msg}")
            cb(0, msg)
            return False, msg
        except Exception as e:
            if self.proxy_manager and hasattr(self.proxy_manager, "classify_error"):
                try:
                    code, user_msg = self.proxy_manager.classify_error(e)
                    msg = f"[{code}] {user_msg}"
                except Exception:
                    msg = f"Error: {e}"
            else:
                msg = f"Error: {e}"
            print(f"[OSM] {layer_name}: {msg}")
            cb(0, msg)
            return False, msg

    def download_selected(self, polygon_wkt, layer_names, buffer_meters=0, progress_callback=None):
        """
        Download a list of OSM layers for the given polygon area.

        Returns dict: {layer_name: (success, filepath_or_error)}
        """
        bbox = self.calculate_bbox(polygon_wkt, buffer_meters)
        area_km2 = self.estimate_area_km2(bbox)
        print(
            f"[OSM] bbox=({bbox[0]:.4f},{bbox[1]:.4f},{bbox[2]:.4f},{bbox[3]:.4f}) "
            f"area={area_km2:.1f} km²  buffer={buffer_meters}m"
        )
        print(f"[OSM] Layers: {', '.join(layer_names)}")

        results = {}
        for i, name in enumerate(layer_names):
            if self.stop_event:
                results[name] = (False, "Cancelled")
                continue
            # Polite 2-second gap between consecutive queries
            if i > 0:
                time.sleep(2)
            results[name] = self.download_layer(name, bbox, progress_callback)

        return results
