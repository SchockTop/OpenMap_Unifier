# OpenMap Unifier

A desktop application for downloading and processing geodata from Bayern's OpenGeodata portal.

## Features

- **Polygon Extraction**: Extract coordinates from Google Earth KML/XML files
- **Satellite Imagery**: Download DOP40 aerial imagery tiles
- **Relief Data**: Download shaded relief tiles
- **Metalink Downloads**: Bulk download from .meta4 files
- **Web Interface**: Optional FastAPI-based web server
- **DOM-Mesh 3D cutout**: Cut a small textured photogrammetry-mesh slice (OBJ + GLB)
  out of Bayern's DOM-Mesh from a Google Earth KML polygon — range-fetched, no
  multi-GB download. (`backend/dommesh.py`; "DOM-Mesh — Photogrammetric 3D city mesh"
  in the Bayern picker / `POST /start-download-dommesh`.)
- **Infrared (DOP20 CIR)**: Near-infrared / color-infrared aerial imagery, 20 cm —
  vegetation glows red, water reads dark. Bavaria's only free IR imagery
  (WMS `by_dop20cir`; in the Bayern picker under "Infrared"). There is no raw CIR
  tile and no short-wave IR in Bavaria's aerial data — for real SWIR use Sentinel-2.
- **Sentinel-2 (satellite + real SWIR)**: True multispectral satellite imagery
  incl. short-wave infrared (B11/B12) and NIR, with derived indices
  (NDVI/NDBI/MNDWI/NBR/NDMI). Free, no login, no Hugging Face — works behind a
  corporate proxy. (`backend/sentinel2_downloader.py`, `python download_sentinel2.py <polygon>`.)
- **ESA WorldCover (land cover)**: Free global 10 m land-cover labels (11 classes) —
  weak training labels to complement OSM land-use.
  (`backend/worldcover_downloader.py`, `python download_worldcover.py <polygon>`.)
- **DOM20 (surface model)**: First-return surface elevation (roofs, canopy), 20 cm
  GeoTIFF tiles. DOM20 − DGM1 = nDSM (object height above ground) — the height cue
  the materialmap classifier uses. (Bayern picker category *Height*.)
- **materialmap stack CLI**: One command for everything the materialmap pipeline
  (ReadSearch repo) consumes — DGM1 + DOM20 (+ NIR/CIR, raw DOP20, LiDAR LAZ) —
  through the same proxy config as the GUI, optionally renamed into the layout the
  materialmap scripts read. (`python download_materialmap.py <polygon>`.)

### New map sources — usage

All take the **same polygon** (WKT string or a `.wkt` file, EPSG:4326 lon/lat). The
Bayern CIR layer downloads through the existing GUI/Web picker (category *Infrared*).
Sentinel-2 and WorldCover have standalone CLIs (and `backend/` modules for the app):

```bash
# Sentinel-2: true-colour + NIR + SWIR, cropped to the polygon, with indices
python download_sentinel2.py region.wkt --bands red green blue nir swir16 swir22 \
       --date 2023-06-01/2023-09-30 --max-cloud 15 --indices

# ESA WorldCover land-cover labels, cropped to the polygon
python download_worldcover.py region.wkt --hist
```

Cropping to the polygon uses `rasterio` when installed (`pip install rasterio`);
without it the whole satellite/land-cover tile is downloaded instead. The core
Bayern tile/WMS downloads need no GDAL.

## Requirements

- **Windows 10/11** (x64)
- **Python 3.10 or newer** with tkinter (included with standard Python installer from python.org)

> **Note**: You must install Python from [python.org](https://python.org). During installation, ensure:
> - ✅ "Add Python to PATH" is checked
> - ✅ "tcl/tk and IDLE" is selected (usually enabled by default)

## Quick Start

### First-Time Setup

1. **Install Python** (if not already installed):
   - Download from https://www.python.org/downloads/
   - Run installer with "Add Python to PATH" checked
   - Accept default options (includes tkinter)

2. **Double-click `setup.bat`** to create the virtual environment and install dependencies

3. **Run the application** with `run.bat`

### Running the Application

| Script | Description |
|--------|-------------|
| `run.bat` | Launch the GUI application |
| `run_web.bat` | Start the web server (http://127.0.0.1:8000) |
| `run_local.bat` | Offline-only mode (no internet required) |

## Offline Deployment

To deploy to a machine without internet access:

1. On a machine **with** internet, run:
   ```
   download_libraries.bat
   ```

2. Copy the entire project folder (including `libraries/`) to the target machine

3. On the target machine:
   - Install Python 3.12 from https://python.org
   - Run `run_local.bat`

## Project Structure

```
OpenMap_Unifier/
├── backend/              # Core logic modules
│   ├── downloader.py     # File download engine
│   └── geometry.py       # Polygon extraction
├── libraries/            # Offline wheel cache
├── venv/                 # Virtual environment (created by setup)
├── Images/               # Help guide images
├── static/               # Web server static files
├── templates/            # Web server templates
├── gui.py                # Desktop GUI application
├── app.py                # FastAPI web server
├── requirements.txt      # Core dependencies
├── requirements-web.txt  # Web server dependencies
├── setup.bat             # First-time setup script
├── run.bat               # Run GUI application
├── run_web.bat           # Run web server
├── run_local.bat         # Offline-only mode
└── download_libraries.bat # Update offline cache
```

## Dependencies

| Package | Purpose |
|---------|---------|
| customtkinter | Modern GUI framework |
| Pillow | Image processing |
| requests | HTTP client |
| shapely | Geometry operations |
| pyproj | Coordinate transformations |
| tqdm | Progress bars |

## Troubleshooting

### "Python with tkinter not found"

Python must be installed from python.org with tkinter support:
1. Download from https://python.org/downloads
2. Run the installer
3. Ensure "tcl/tk and IDLE" is checked in optional features
4. Ensure "Add Python to PATH" is checked
5. Run `setup.bat` again

### "No module named tkinter"

Your Python installation is missing tkinter. Reinstall Python:
1. Open Windows Settings → Apps → Installed Apps
2. Find Python 3.x and click Modify
3. Click "Modify" again
4. Ensure "tcl/tk and IDLE" is checked
5. Complete the installation

### GUI doesn't start

- Check the Console tab for error messages
- Ensure your Windows display scaling is set correctly
- Try running from Command Prompt: `venv\Scripts\python.exe gui.py`

### Offline installation fails

- Ensure `libraries/` folder contains all wheel files
- Run `download_libraries.bat` on a machine with internet
- Copy the entire `libraries/` folder to the target machine

## License

This project uses open data from [geodaten.bayern.de](https://geodaten.bayern.de/opengeodata/).
