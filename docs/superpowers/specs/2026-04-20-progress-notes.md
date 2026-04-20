# Overnight Progress Notes — 2026-04-20

Branch: `auto/proxy-bayern-ux-rework`
All work committed on this branch, pushed to origin. Open a PR to merge into `main`.

## Sub-project 1 — Proxy fixes & diagnostics  ✅

Acceptance criteria from `2026-04-20-proxy-fixes-design.md`:

1. **Manual proxy config persists across restart.** Fixed in `gui.py` — `auto_detect()` only runs when the user chose auto mode or no saved config exists. Was: unconditional, clobbered saved settings on every launch.
2. **CA bundle (.pem) works for both Bayern and OSM.** New `ssl_verify` + `ca_bundle_path` fields in `ProxyConfig`, applied centrally in `ProxyManager.get_session()`. Both downloaders inherit the same session. `.pem` file picker added to the Proxy Settings dialog.
3. **407 shows as classified message, not raw traceback.** New `ProxyManager.classify_error()` maps exceptions to `PROXY_AUTH / SSL / PROXY / TIMEOUT / DNS / HTTP / OTHER`. All six classes unit-verified. `MapDownloader` and `OSMDownloader` route exceptions through the classifier — progress row now shows `[PROXY_AUTH] Proxy rejected credentials (407). …`.
4. **Test Connection covers both endpoints.** New `test_connections()` returns Bayern + OSM results; dialog button renders both in the status label.
5. **OSM tab no longer has its own SSL checkbox.** Removed; replaced with a one-line pointer to Proxy Settings.

### Known residual risks

- **Default upgrade:** users whose pre-upgrade workaround was `ssl_verify=False` on the OSM tab will find `ssl_verify=True` by default after upgrade. They re-tick it once in the new unified dialog. Documented in the design spec.
- **No automated tests.** Manually validate by:
  1. Set manual proxy with a fake host → quit → relaunch → dialog shows saved host+user.
  2. Point CA bundle at your `.pem` → DOP20 download succeeds.
  3. Fire a wrong password → progress row shows `[PROXY_AUTH]` prefix.
  4. Test Connection shows both Bayern and OSM.

## Sub-project 2 — Bayern dataset rework  ✅

The core complaint was that "Relief" (WMS hillshade) was not actual height data. Replaced with a proper dataset catalog.

### `BAYERN_DATASETS` catalog in `backend/downloader.py`

| Key         | Category   | Kind | Notes                                    |
|-------------|------------|------|------------------------------------------|
| dgm1        | height     | raw  | **1m GeoTIFF — real elevation**. Default-checked. |
| dgm5        | height     | raw  | 5m GeoTIFF, coarser / smaller.           |
| dop20       | ortho      | raw  | 20cm RGB orthophoto (existing).          |
| dop40       | ortho      | raw  | 40cm RGB orthophoto.                     |
| lod2        | buildings  | raw  | CityGML, 2km tiles.                      |
| laser       | laser      | raw  | LAZ point cloud.                         |
| relief_wms  | wms_render | wms  | Shaded-relief (old "Relief" — kept, visual only). |
| dop40_wms   | wms_render | wms  | Quick DOP40 preview.                     |

### URL pattern

Raw tiles: `https://download1.bayernwolke.de/a/<url_key>/data/<tile_id><ext>` where `<tile_id>` is `32<easting_km>_<northing_km>` in EPSG:25832. Verified for DOP20 against the repo's existing `dop20rgb.meta4`; DGM1/DOP40/LoD2/laser assumed consistent (confirmed by `mueckl/opendata_bayern_download`).

### GUI

- New scrollable, grouped checkbox picker driven entirely by the catalog.
- DGM1 default-checked. Each row shows description + resolution + file extension.
- Per-dataset output goes to `downloads_bayern/<key>/` so raw GeoTIFFs, LAZ, and WMS renders don't mix.
- CC BY 4.0 attribution text shown directly below the picker.

## Sub-project 3 — UX additions  ✅

New **Downloads** tab showing:

- Every known output folder (Bayern, OSM, legacy) with file count + total size.
- Per-folder **Open** (OS file manager) and **Clear** (delete contents, keep folder) buttons.
- Confirmation dialog on Clear shows count + size before destructive action.
- Totals row at the bottom.
- License / attribution panel covering OSM (ODbL v1.0) and Bayern (CC BY 4.0) — verbatim attribution strings, with share-alike and keep-open reminders.

Legacy folders (`downloads_relief`, `downloads_satellite`, `downloads_dop20`) are listed only when they exist on disk, so they don't clutter a fresh install.

Also added `.gitignore` for `__pycache__/`, `downloads_*/`, `proxy_config.json`, and local Claude settings — untracking the tracked `.pyc` files in the process.

## Bonus: Blender GIS batch-import fix  ✅

The error you hit — `IOError: Unable to read georef infos from worldfile or geotiff tags` — is because Bayern's raw GeoTIFFs ship without internal georef tags. Blender GIS couldn't batch-import them.

Added `backend/worldfile.py` — reads the Bayern tile filename (which encodes position in EPSG:25832), combines with dataset pixel size, writes:

- **`.tfw`** — ESRI worldfile (6 lines: pixel size, rotations, top-left centre coords)
- **`.prj`** — EPSG:25832 WKT

These get auto-written after every raw Bayern download. There's also a `.tfw` button on every Bayern raw-tile row in the Downloads tab so you can regenerate sidecars for folders downloaded before this change.

Unit-verified: DGM1 tile `32672_5424` → top-left pixel centre `(672000.5, 5424999.5)` at 1m. DOP20 tile at 0.2m → `(672000.1, 5425999.9)`. QGIS / Blender GIS / GDAL all read `.tfw + .prj` sidecars natively.

## Bonus: download robustness

- **Atomic writes**: downloads go to `<file>.part`, renamed only after size verification. Prevents the "cancelled mid-download, left a partial, next run skipped it" failure mode.
- **Pre-flight size estimate**: when the estimated total download exceeds 2 GB (e.g. DOP20 across a larger polygon), a confirmation dialog lists tile count + estimated size per dataset before anything downloads. Small pulls go through with no friction.

## Commit log on this branch

```
e66c3ad feat(bayern): pre-flight size estimate + confirm dialog for big downloads
05fc7df fix(downloader): atomic .part write, size-check, no partials on cancel/error
3b325ed feat(bayern): auto-write .tfw + .prj sidecars for Blender GIS batch import
1491d5b docs: overnight progress notes — all 3 sub-projects complete
f3026ac chore: add .gitignore, untrack __pycache__, ignore local downloads + creds
5d182e8 feat(ux): downloads overview tab with per-folder clear + license panel
20fd6d0 feat(bayern): catalog-driven dataset picker — real height data (DGM1)
643ebb7 feat(proxy): classified error diagnostics + multi-target test
d1552f4 feat(proxy): unified SSL verify + CA bundle in ProxyConfig
63813b2 fix(proxy): don't clobber saved manual config on startup
728f9d6 osm: add ssl_verify toggle, test-connection button, classified errors (baseline)
c66820d docs: add proxy fixes & diagnostics design spec (sub-project 1/3)
```

## Opening the PR

The `gh` CLI isn't on PATH in this environment. Open the PR manually:

    https://github.com/SchockTop/OpenMap_Unifier/pull/new/auto/proxy-bayern-ux-rework

Repo has moved from `Kleinschock/OpenMap_Unifier` to `SchockTop/OpenMap_Unifier` — GitHub redirects, both URLs work.

## What I did NOT touch

- `app.py` (Flask web variant) — design spec scoped to desktop `gui.py`. Apply the same changes there in a follow-up.
- `check_layers.py`, `check_wms.py`, `test_*.py` helper scripts — untouched.
- No attempt to verify live downloads (no corporate proxy / network access in the sandbox).
