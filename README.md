# OpenMap Unifier

A desktop application for downloading and processing geodata from Bayern's OpenGeodata portal.

## Features

- **Polygon Extraction**: Extract coordinates from Google Earth KML/XML files
- **Satellite Imagery**: Download DOP40 aerial imagery tiles
- **Relief Data**: Download shaded relief tiles
- **Metalink Downloads**: Bulk download from .meta4 files
- **Web Interface**: Optional FastAPI-based web server

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
