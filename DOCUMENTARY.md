# OpenMap Unifier — Technical Documentary

**Tested on:** 2026-04-07  
**Python:** 3.10.6  
**Branch:** main (commit `7cfa4bd`)

---

## What This Project Is

**OpenMap Unifier** is a Windows desktop + web tool for downloading open geodata from Bavaria's public geoportal ([geoservices.bayern.de](https://geoservices.bayern.de) and [bayernwolke.de](https://download1.bayernwolke.de)).

The core workflow is:
1. User draws a polygon in Google Earth and exports it as a KML file.
2. The tool extracts the coordinates from that file.
3. The tool uses those coordinates to figure out which 1 km × 1 km grid tiles overlap the area.
4. It downloads those tiles (elevation data, satellite imagery, LIDAR, etc.) in parallel.

It ships as **two interfaces**: a desktop GUI (customtkinter) and a FastAPI web server. Both share the same backend logic.

---

## Project Structure

```
OpenMap_Unifier/
├── backend/
│   ├── geometry.py          # KML → EWKT polygon parser
│   ├── downloader.py        # Download engine + tile URL generator
│   └── proxy_manager.py     # Corporate proxy auto-detection & config
├── gui.py                   # Desktop GUI (customtkinter)
├── app.py                   # FastAPI web server
├── templates/index.html     # Web UI (single-page)
├── static/
│   ├── script.js            # Frontend: drag-drop, upload, progress polling
│   └── style.css            # Glassmorphism dark design
├── requirements.txt         # Core dependencies
├── requirements-web.txt     # Core + FastAPI stack
├── setup.bat                # Python detection + venv setup
├── run.bat                  # Launch GUI
├── run_web.bat              # Launch web server
├── run_local.bat            # Offline GUI mode
├── download_libraries.bat   # Cache wheels for offline deployment
│
├── Utility / Dev Scripts:
│   ├── check_layers.py
│   ├── check_wms.py
│   ├── extract_polygon.py
│   ├── download_metalink.py
│   ├── download_relief_tiles.py
│   ├── test_tiff.py
│   └── test_wms_params.py
│
├── Images/                  # Help guide screenshots (embedded in GUI tab)
├── downloads/               # Default output directory
├── downloads_satellite/     # Satellite tile output
└── downloads_relief/        # Relief tile output
```

---

## Backend Modules

### `backend/geometry.py` — Polygon Extraction

**Class:** `PolygonExtractor`  
**Method:** `extract_from_kml(content_bytes=None, file_path=None)`

Parses a Google Earth KML/XML file and extracts the first `<coordinates>` block. Coordinates in KML are stored as `longitude,latitude,altitude` triplets; the altitude is discarded. Output is EWKT format: `SRID=4326;POLYGON((lon lat, ...))`.

**Tested behavior (all verified ✓):**

| Input | Result |
|---|---|
| Valid KML with polygon | `SRID=4326;POLYGON((11.5 48.1, ...))` |
| Invalid XML (not parseable) | `(None, "syntax error: line 1, column 0")` |
| Valid XML but no `<coordinates>` tag | `(None, "No coordinates found in KML/XML.")` |
| Empty bytes | `(None, "No content or file provided")` |

**Limitation:** Only extracts the **first** polygon found. Multi-polygon KML files are silently truncated to the first one.

---

### `backend/downloader.py` — Download Engine

**Class:** `MapDownloader(download_dir="downloads", proxy_manager=None)`

#### `download_file(url, file_name, progress_callback=None)`

Downloads a file with streaming (65 KB chunks). If the file already exists, it skips it immediately (basic resume support). The progress callback receives: `(filename, percent, status_text, speed_str, eta_str)`.

**Stop/Cancel:** Uses `self.stop_event` (a plain `bool`, not `threading.Event`). Set `downloader.stop_event = True` from another thread to cancel. The current chunk finishes, the partial file is left on disk, and the function returns `False`. **The partial file is not cleaned up automatically.**

**Tested behavior (verified ✓):**

| Scenario | Result |
|---|---|
| Normal download | File saved, returns `True` |
| File already exists | Returns `True`, callback with `"Skipped (Exists)"` |
| `stop_event = True` mid-download | Returns `False`, partial file left on disk |
| Server returns HTTP error | Exception raised, returns `False` |

---

#### `generate_relief_tiles(polygon_wkt, layer, format_ext, high_res)`

Given an EWKT polygon (WGS84), generates a list of `(filename, wms_url)` pairs for 1 km × 1 km WMS tiles.

**Coordinate transformation:** Uses pyproj to convert WGS84 (EPSG:4326) → UTM Zone 32N (EPSG:25832). Grid is snapped to 1000 m boundaries using floor/ceil.

**Tile naming:** `{layer}_{easting}_{northing}.{ext}` e.g. `by_relief_schraeglicht_686000_5330000.tiff`

**Supported layers:**
- `by_relief_schraeglicht` → Relief hillshading, WMS endpoint: `geoservices.bayern.de/pro/wms/dgm/v1/relief` (requires account/auth? — see Notes)
- `by_dop40c` → DOP40 satellite imagery, WMS endpoint: `geoservices.bayern.de/od/wms/dop/v1/dop40`

**Resolution modes:**
- Standard: `WIDTH=2000&HEIGHT=2000` (~2 MB per tile for TIFF)
- High-res: `WIDTH=5906&HEIGHT=5906` (300 DPI equivalent — larger files, slower)

**Verified with test polygon** `11.5°–11.51° lon, 48.1°–48.11° lat`:
- 2 tiles generated, 1 successfully downloaded as 4.67 MB TIFF ✓

---

#### `generate_1km_grid_files(polygon_wkt, dataset)`

Generates download URLs for raw 1 km × 1 km grid files directly from Bavaria's file server (`download1.bayernwolke.de`).

**File naming:** `32{east_km}_{north_km}.{ext}` — e.g. `32686_5330.tif`

**Supported datasets (tested URL structure ✓):**

| Dataset | Format | Resolution | URL pattern |
|---|---|---|---|
| `dgm1` | `.tif` | 1 m DEM | `/a/dgm1/data/32XXX_YYYY.tif` |
| `dop20` | `.tif` | 20 cm aerial | `/a/dop20/data/32XXX_YYYY.tif` |
| `dop40` | `.tif` | 40 cm aerial | `/a/dop40/data/32XXX_YYYY.tif` |
| `lod2` | `.zip` | 3D buildings | `/a/lod2/data/32XXX_YYYY.zip` |
| `laser` | `.laz` | LIDAR point cloud | `/a/laser/data/32XXX_YYYY.laz` |

**Live availability tested:**
- `dop20` → HTTP 200, file size ~69 MB per tile ✓
- `dgm1` → HTTP 404 for the test tile (file may not exist for all tiles) — no error handling, download will fail silently

---

#### `parse_metalink(file_path)`

Parses a `.meta4` (Metalink 4) XML file. Supports any XML namespace via `tag.endswith()` matching. Returns `[(filename, url), ...]`.

**Tested behavior (verified ✓):**
- Valid `.meta4` with namespace → correctly extracts files
- Invalid XML → returns `[]`, logs error

---

#### `format_bytes(size)` — Known Bug

Uses `while size > power` (strict greater-than). This means exact power-of-1024 boundaries display at the previous unit:

| Input | Actual output | Expected |
|---|---|---|
| 1024 bytes | `1024.00 B` | `1.00 KB` |
| 1048576 bytes (1 MB) | `1024.00 KB` | `1.00 MB` |
| 1073741824 bytes (1 GB) | `1024.00 MB` | `1.00 GB` |

**Fix:** Change `while size > power:` to `while size >= power:`.

---

#### `format_time(seconds)`

Works correctly. Examples: `0s`, `1s`, `59s`, `1m 0s`, `1m 30s`.  
**Note:** `3600s` displays as `60m 0s` (does not convert to hours). Not a bug per se, but large ETAs will show e.g. `120m 0s` instead of `2h 0m`.

---

### `backend/proxy_manager.py` — Proxy Management

**Class:** `ProxyManager`

Handles corporate proxy detection and configuration. On this test machine (no proxy), auto-detection correctly reported "Windows proxy is disabled in registry" and set `enabled=False`.

**Detection priority:**
1. Environment variables (`HTTP_PROXY`, `HTTPS_PROXY`, etc.)
2. Windows Registry (`HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings`)
3. `urllib.request.getproxies()`

**Auth modes:** None, Basic (user:password in URL), NTLM (requires optional `requests-ntlm` package — not installed by default).

**Config persistence:** Saved to `proxy_config.json`. Passwords are intentionally **not saved**.

**Tested behavior (verified ✓):**
- Auto-detect on machine with no proxy → `enabled=False`, `proxy_url="Direct Connection"`
- `get_status()` returns correct dict
- `get_session()` returns a `requests.Session` (cached, reused across calls)

---

## Desktop GUI (`gui.py`)

**Framework:** customtkinter 5.x  
**Window:** 1100×800 px, dark mode, dark-blue theme

### Tab 1: Map Tools

**Left panel — Polygon Extraction:**
- "Load KML File" button → file dialog → calls `PolygonExtractor`
- "Paste from Clipboard" → reads clipboard content → calls `PolygonExtractor`
- Displays EWKT result in text area
- "Copy" button → copies polygon to clipboard

**Right panel — Data Downloads:**

Each button generates a file list and then downloads in parallel with `ThreadPoolExecutor(max_workers=3)`.

| Button | Backend call | Output dir |
|---|---|---|
| Download Relief | `generate_relief_tiles(layer="by_relief_schraeglicht")` | `downloads_relief/` |
| Download DOP40 WMS | `generate_relief_tiles(layer="by_dop40c", format_ext=<selected>)` | `downloads_satellite/` |
| Download DOP20 (raw) | `generate_1km_grid_files(dataset="dop20")` | `downloads_satellite/` |
| Load .meta4 | `parse_metalink()` then bulk download | `downloads/` |

High-res checkbox controls the WMS resolution for Relief/DOP40 tiles.

**Proxy indicator:** Shows green dot if proxy enabled, gray if direct. Opens `ProxySettingsDialog` modal.

**Bottom — Download Manager:**
- Scrollable list, one row per file
- Shows: filename, progress bar, status text, speed, ETA
- Updates in real-time via `self.after()` callbacks
- Up to 3 concurrent downloads

### Tab 2: Help & Guide

Scrollable instructions for the Google Earth → KML workflow, with embedded screenshots from `Images/`. Images referenced:
- `Images/Polygon_Symbol.png`
- `Images/Save_Symbol.png`
- `Images/CopyElement_Symbol.png`

### Tab 3: Console

Redirects `sys.stdout` and `sys.stderr` to a read-only text widget. Helpful for debugging — all print statements from the backend appear here. Output is also echoed to the real terminal.

---

## Web Server (`app.py`)

**Framework:** FastAPI + Uvicorn  
**Default address:** `http://127.0.0.1:8000`

### Endpoints — Tested ✓

| Method | Path | Function |
|---|---|---|
| `GET` | `/` | Serves `templates/index.html` |
| `POST` | `/analyze-kml` | Upload KML → returns `{"polygon": "SRID=4326;POLYGON((...))"}` |
| `POST` | `/start-download-relief` | Form field `polygon` → starts tiled WMS downloads |
| `GET` | `/progress` | Returns `{filename: {percent, status}, ...}` |

**`GET /`** — HTTP 200, 2920 bytes, serves correct HTML ✓

**`POST /analyze-kml`** — fully functional ✓
- Valid KML → `{"polygon": "SRID=4326;POLYGON(...)"}` HTTP 200
- Invalid XML → `{"error": "syntax error: line 1, column 0"}` HTTP 400

**`POST /start-download-relief`** — functional ✓
- Creates tile list, initializes progress state, queues background task
- Response: `{"message": "Download started", "tile_count": N}`
- Progress immediately visible at `/progress`

**`GET /progress`** — functional ✓
- Returns current state of all tracked files
- Frontend polls every 1 second

### Endpoints — Broken

**`POST /start-download-metalink`** — **BROKEN** (always returns HTTP 400)

**Root cause:** `parse_metalink(content)` is called with raw `bytes` from `await file.read()`, but the method internally calls `ET.parse(file_path)` which expects a **file path string**, not bytes. `ET.parse(bytes_object)` raises `OSError: [Errno 22] Invalid argument`.

**Fix:** Save bytes to a `tempfile.NamedTemporaryFile` first, or replace `ET.parse()` with `ET.fromstring()` in `parse_metalink`.

---

### Bugs in Web Server Background Tasks

Both `run_metalink_download` and `run_relief_download` have the same two bugs:

**Bug 1: Awaiting a synchronous function**
```python
# In app.py — BROKEN
await downloader.download_file(url, fname, ProgressManager.update_progress)
```
`download_file` is a regular synchronous method (not `async def`). Awaiting it raises `TypeError: object NoneType can't be used in 'await' expression` (the return value of a sync function is not awaitable). This means downloads triggered from the web server do **not actually run**.

**Fix:** Use `asyncio.get_event_loop().run_in_executor(None, ...)` to run the blocking download in a thread pool.

**Bug 2: Progress callback signature mismatch**
```python
# download_file calls:  callback(filename, percent, status, speed, eta)   — 5 args
# ProgressManager has: update_progress(file_name, percent, status)         — 3 args
```
Even if the await issue were fixed, the callback would fail with `TypeError: update_progress() takes 3 positional arguments but 5 were given`.

**Fix:** Update `ProgressManager.update_progress` to accept and discard `*args`, or add `speed` and `eta` parameters.

---

## Connectivity — Live Test Results

All tested 2026-04-07:

| Service | Result |
|---|---|
| `geoservices.bayern.de` | HTTP 200 ✓ |
| DOP40 WMS `GetCapabilities` | HTTP 200, 10526 bytes ✓ |
| Relief WMS tile download (TIFF) | HTTP 200, 4.67 MB ✓ |
| `download1.bayernwolke.de/a/dop20/data/32686_5330.tif` | HTTP 200, 69.48 MB ✓ |
| `download1.bayernwolke.de/a/dgm1/data/32686_5330.tif` | HTTP 404 (tile may not exist) |

---

## All Dependencies

### Installed and working ✓

| Package | Purpose |
|---|---|
| `customtkinter` | Modern tkinter GUI wrapper |
| `Pillow` | Image loading for help guide screenshots |
| `requests` | HTTP client for all downloads |
| `shapely` | Polygon geometry (used in WKT parsing) |
| `pyproj` | EPSG:4326 → EPSG:25832 coordinate transforms |
| `tqdm` | Progress bars in CLI utility scripts |
| `packaging` | Version comparison |
| `fastapi` | Web framework |
| `uvicorn` | ASGI server |
| `python-multipart` | File upload parsing |
| `jinja2` | HTML template rendering |

### Not installed (optional)

| Package | Purpose |
|---|---|
| `requests-ntlm` | NTLM proxy authentication (corporate Windows domains) |

---

## Frontend Web UI

**Design:** Glassmorphism dark UI (`#0f172a` background, blue `#3b82f6` accents, `backdrop-filter: blur`)

**Three cards:**
1. **Polygon Extraction** — drag-drop KML zone, EWKT output textarea, copy button
2. **Data Downloader** — metalink drag-drop zone, relief download button
3. **Process Status** — auto-updating progress list (1-second polling)

**JavaScript behavior:**
- Drag-drop and click-to-upload both supported
- Polls `/progress` every second while any download is active
- Stops polling when all files are at 100% or "Completed"
- Note: Due to the backend bugs described above, the download buttons will **not trigger actual downloads** from the web interface currently.

---

## What Works

| Feature | Status |
|---|---|
| KML polygon extraction (GUI) | ✓ Works |
| KML polygon extraction (Web API) | ✓ Works |
| WMS relief tile download (GUI) | ✓ Works |
| WMS DOP40 tile download (GUI) | ✓ Works |
| Raw grid file URL generation | ✓ Works |
| Metalink file parsing (library) | ✓ Works |
| Metalink download (GUI) | ✓ Works |
| Proxy auto-detection | ✓ Works |
| File skip/resume | ✓ Works |
| Download cancel | ✓ Works (partial file left on disk) |
| Progress tracking (GUI) | ✓ Works |
| Setup scripts (setup.bat) | ✓ Works |

## What Doesn't Work

| Feature | Status | Root Cause |
|---|---|---|
| `/start-download-metalink` endpoint | ✗ Always returns HTTP 400 | `parse_metalink` receives `bytes` instead of file path |
| Web server background downloads | ✗ Never execute | `await` on synchronous `download_file` |
| Web server progress updates | ✗ Would throw on callback | Signature mismatch: 5 args passed, 3 expected |
| `format_bytes` at exact 1024 boundaries | Minor bug | `>` instead of `>=` threshold |
| Partial file cleanup on cancel | Missing | Partial files left on disk with no cleanup |
| Hours in `format_time` | Minor | Caps at minutes (e.g. `120m 0s` instead of `2h 0m`) |

---

## Bug Fix Summary

### 1. `format_bytes` off-by-one (`backend/downloader.py`)
```python
# Before (buggy)
while size > power:
# After
while size >= power:
```

### 2. `/start-download-metalink` bytes vs path (`app.py`)
```python
# Before (buggy)
content = await file.read()
files_to_download = downloader.parse_metalink(content)

# After
import tempfile, os
content = await file.read()
with tempfile.NamedTemporaryFile(delete=False, suffix='.meta4') as tmp:
    tmp.write(content)
    tmp_path = tmp.name
files_to_download = downloader.parse_metalink(tmp_path)
os.unlink(tmp_path)
```

### 3. Sync function awaited in background tasks (`app.py`)
```python
# Before (buggy)
await downloader.download_file(url, fname, ProgressManager.update_progress)

# After
loop = asyncio.get_event_loop()
await loop.run_in_executor(None, downloader.download_file, url, fname, ProgressManager.update_progress)
```

### 4. Progress callback signature mismatch (`app.py`)
```python
# Before (buggy)
@staticmethod
async def update_progress(file_name, percent, status):

# After
@staticmethod
def update_progress(file_name, percent, status, speed=None, eta=None):
    progress_state[file_name] = {"percent": percent, "status": status}
```
(Also remove `async` since it's not a coroutine and isn't awaited.)

---

## Coordinate System Notes

All user-facing input/output uses **WGS84 (EPSG:4326)** — the standard GPS coordinate system used by Google Earth.

Internal processing converts to **UTM Zone 32N (EPSG:25832)** for metric grid calculations. At 48°N latitude, 1 degree of longitude ≈ 7.45 km and 1 degree of latitude ≈ 11.1 km. The 1 km grid tiles at UTM boundaries cover a slightly different area than a degree-based bounding box, which is why the number of tiles can seem surprising (a 0.1° × 0.1° polygon may overlap 100+ 1 km tiles after coordinate transformation).

---

## Deployment Notes

**Online setup:** `run.bat` → auto-runs `setup.bat` if venv is missing → installs from PyPI.

**Offline deployment:**
1. Run `download_libraries.bat` on an internet-connected machine → caches all `.whl` files to `libraries/`
2. Copy entire folder to target machine (Python must be installed separately)
3. Run `run_local.bat` → installs from `libraries/` without internet

**Web server:** `run_web.bat` → starts on `http://127.0.0.1:8000`. No authentication — local access only by default.
