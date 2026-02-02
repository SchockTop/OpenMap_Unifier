
from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.requests import Request
import uvicorn
import shutil
import os
import asyncio
from typing import List

from backend.geometry import PolygonExtractor
from backend.downloader import MapDownloader

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Global state for progress tracking (simple dictionary for demo purposes)
# In production, use Redis or robust state management
progress_state = {}

class ProgressManager:
    @staticmethod
    async def update_progress(file_name, percent, status):
        progress_state[file_name] = {"percent": percent, "status": status}

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/analyze-kml")
async def analyze_kml(file: UploadFile = File(...)):
    content = await file.read()
    ewkt, error = PolygonExtractor.extract_from_kml(content_bytes=content)
    if error:
        return JSONResponse(status_code=400, content={"error": error})
    return {"polygon": ewkt}

@app.post("/start-download-metalink")
async def start_download_metalink(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    content = await file.read()
    downloader = MapDownloader()
    
    files_to_download = downloader.parse_metalink(content)
    if not files_to_download:
        return JSONResponse(status_code=400, content={"error": "No files found in metalink"})
    
    # Initialize progress
    for fname, _ in files_to_download:
        progress_state[fname] = {"percent": 0, "status": "Pending"}
        
    background_tasks.add_task(run_metalink_download, files_to_download, downloader)
    
    return {"message": "Download started", "file_count": len(files_to_download)}

async def run_metalink_download(files, downloader):
    # Limit concurrency
    semaphore = asyncio.Semaphore(5)
    
    async def task(fname, url):
        async with semaphore:
            await downloader.download_file(url, fname, ProgressManager.update_progress)

    await asyncio.gather(*[task(f, u) for f, u in files])

@app.post("/start-download-relief")
async def start_download_relief(background_tasks: BackgroundTasks, polygon: str = Form(...)):
    downloader = MapDownloader(download_dir="downloads_relief")
    tiles = downloader.generate_relief_tiles(polygon)
    
    if not tiles:
        return JSONResponse(status_code=400, content={"error": "No tiles found for polygon"})
        
    # Initialize progress
    for fname, _ in tiles:
        progress_state[fname] = {"percent": 0, "status": "Pending"}
        
    background_tasks.add_task(run_relief_download, tiles, downloader)
    
    return {"message": "Download started", "tile_count": len(tiles)}

async def run_relief_download(tiles, downloader):
    semaphore = asyncio.Semaphore(5)
    async def task(fname, url):
        async with semaphore:
            await downloader.download_file(url, fname, ProgressManager.update_progress)
            
    await asyncio.gather(*[task(f, u) for f, u in tiles])

@app.get("/progress")
async def get_progress():
    return progress_state

if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
