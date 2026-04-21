
import customtkinter as ctk
from PIL import Image
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import sys
import os
import time

import subprocess

from backend.geometry import PolygonExtractor
from backend.downloader import MapDownloader
from backend.osm_downloader import (
    OSMDownloader, LAYER_ORDER, DEFAULT_LAYERS, LAYERS as OSM_LAYERS,
    OUTPUT_FORMATS, DEFAULT_OUTPUT_FORMAT,
)

# Import proxy manager (optional)
try:
    from backend.proxy_manager import ProxyManager, get_proxy_manager
    PROXY_AVAILABLE = True
except ImportError:
    PROXY_AVAILABLE = False
    ProxyManager = None
    get_proxy_manager = None

# Set Theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# --- CONSOLE REDIRECTION ---
class ConsoleRedirect:
    def __init__(self, text_widget, original_stdout):
        self.text_widget = text_widget
        self.original_stdout = original_stdout

    def write(self, str_val):
        # 1. Write to REAL console immediately
        self.original_stdout.write(str_val)
        self.original_stdout.flush() # Force print to CMD
        
        # 2. Update GUI safely
        try:
            self.text_widget.configure(state="normal")
            self.text_widget.insert("end", str_val)
            self.text_widget.see("end")
            self.text_widget.configure(state="disabled")
        except:
            pass 

    def flush(self):
        self.original_stdout.flush()

class OpenMapUnifierApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("OpenMap Unifier")
        self.geometry("1100x800")
        
        # Initialize proxy manager
        self.proxy_manager = None
        if PROXY_AVAILABLE:
            self.proxy_manager = get_proxy_manager(config_dir=".")
            # Auto-detect proxy on startup
            self.proxy_manager.auto_detect()
        
        # Create downloader with proxy support
        self.downloader = MapDownloader(proxy_manager=self.proxy_manager)
        self.osm_downloader = OSMDownloader(proxy_manager=self.proxy_manager)
        
        # --- Tab View ---
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=20)
        
        self.tab_tools = self.tabview.add("Map Tools")
        self.tab_osm = self.tabview.add("OSM Data")
        self.tab_help = self.tabview.add("Help & Guide")
        self.tab_console = self.tabview.add("Console")

        self.setup_tools_tab()
        self.setup_osm_tab()
        self.setup_help_tab()
        self.setup_console_tab()

    def setup_console_tab(self):
        self.console_text = ctk.CTkTextbox(self.tab_console, font=("Consolas", 12))
        self.console_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.console_text.configure(state="disabled")
        
        # Redirect sys.stdout to this widget + real console
        sys.stdout = ConsoleRedirect(self.console_text, sys.__stdout__)
        sys.stderr = ConsoleRedirect(self.console_text, sys.__stderr__)
        
        print("[INIT] Console logging started.")

    def setup_tools_tab(self):
        self.tab_tools.grid_columnconfigure(0, weight=1)
        self.tab_tools.grid_columnconfigure(1, weight=1)
        self.tab_tools.grid_rowconfigure(0, weight=0) # Tools
        self.tab_tools.grid_rowconfigure(1, weight=1) # List

        # --- Left Panel: Extraction ---
        frame_left = ctk.CTkFrame(self.tab_tools)
        frame_left.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        ctk.CTkLabel(frame_left, text="1. Polygon Extraction", font=("Roboto", 18, "bold")).pack(pady=10)
        
        btn_frame = ctk.CTkFrame(frame_left, fg_color="transparent")
        btn_frame.pack(pady=5)
        
        ctk.CTkButton(btn_frame, text="Load .xml / .kml", command=self.load_kml).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Paste from Clipboard", command=self.paste_kml).pack(side="left", padx=5)
        
        self.text_polygon = ctk.CTkTextbox(frame_left, height=120)
        self.text_polygon.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkButton(frame_left, text="Copy Polygon", command=self.copy_polygon, fg_color="transparent", border_width=2).pack(pady=5)

        # --- Right Panel: Downloader Setup ---
        frame_right = ctk.CTkFrame(self.tab_tools)
        frame_right.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        
        ctk.CTkLabel(frame_right, text="2. Data Downloader", font=("Roboto", 18, "bold")).pack(pady=10)
        
        # --- Height Data Section ---
        frame_height = ctk.CTkFrame(frame_right, fg_color="gray20")
        frame_height.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_height, text="Height Data (Relief)", font=("Roboto", 14, "bold")).pack(pady=5)
        
        height_controls = ctk.CTkFrame(frame_height, fg_color="transparent")
        height_controls.pack(pady=5, fill="x", padx=5)
        
        btn_relief = ctk.CTkButton(height_controls, text="Download Relief", command=self.start_relief_download, fg_color="#8e44ad", hover_color="#9b59b6")
        btn_relief.pack(side="left", padx=5)

        self.chk_high_res_relief = ctk.CTkCheckBox(height_controls, text="High-Res (300 DPI)")
        self.chk_high_res_relief.pack(side="left", padx=10)

        ctk.CTkButton(height_controls, text="Open Folder", width=110, height=28,
                      fg_color="gray30", hover_color="gray40",
                      command=lambda: self._open_folder("downloads_relief")).pack(side="right", padx=5)
        
        # --- Satellite Data Section ---
        frame_sat = ctk.CTkFrame(frame_right, fg_color="gray20")
        frame_sat.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_sat, text="Satellite Imagery", font=("Roboto", 14, "bold")).pack(pady=5)
        
        # DOP20 (Raw Files - Higher Quality)
        sat_row1 = ctk.CTkFrame(frame_sat, fg_color="transparent")
        sat_row1.pack(pady=3, fill="x", padx=5)
        
        btn_dop20 = ctk.CTkButton(sat_row1, text="Download DOP20 (Raw TIF)", command=self.start_dop20_download, fg_color="#27ae60", hover_color="#2ecc71")
        btn_dop20.pack(side="left", padx=5)
        ctk.CTkLabel(sat_row1, text="20cm/px, best quality", font=("Roboto", 11), text_color="gray60").pack(side="left", padx=5)

        ctk.CTkButton(sat_row1, text="Open Folder", width=110, height=28,
                      fg_color="gray30", hover_color="gray40",
                      command=lambda: self._open_folder("downloads_dop20")).pack(side="right", padx=5)
        
        # DOP40 (WMS Tiles)
        sat_row2 = ctk.CTkFrame(frame_sat, fg_color="transparent")
        sat_row2.pack(pady=3, fill="x", padx=5)
        
        btn_dop40 = ctk.CTkButton(sat_row2, text="Download DOP40 (WMS)", command=self.start_satellite_download, fg_color="#3498db", hover_color="#2980b9")
        btn_dop40.pack(side="left", padx=5)

        self.seg_format = ctk.CTkSegmentedButton(sat_row2, values=["JPG", "TIF"])
        self.seg_format.set("JPG")
        self.seg_format.pack(side="left", padx=5)

        ctk.CTkButton(sat_row2, text="Open Folder", width=110, height=28,
                      fg_color="gray30", hover_color="gray40",
                      command=lambda: self._open_folder("downloads_satellite")).pack(side="right", padx=5)
        
        # --- Mass Data Section ---
        frame_meta = ctk.CTkFrame(frame_right, fg_color="gray20")
        frame_meta.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_meta, text="Mass Data (.meta4)", font=("Roboto", 14, "bold")).pack(pady=5)
        meta_row = ctk.CTkFrame(frame_meta, fg_color="transparent")
        meta_row.pack(pady=10, fill="x", padx=5)
        ctk.CTkButton(meta_row, text="Select & Download .meta4", command=self.load_metalink).pack(side="left", padx=5)
        ctk.CTkButton(meta_row, text="Open Folder", width=110, height=28,
                      fg_color="gray30", hover_color="gray40",
                      command=lambda: self._open_folder("downloads")).pack(side="right", padx=5)

        # --- Proxy Settings Section ---
        frame_proxy = ctk.CTkFrame(frame_right, fg_color="gray20")
        frame_proxy.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_proxy, text="Network / Proxy", font=("Roboto", 14, "bold")).pack(pady=5)
        
        proxy_row = ctk.CTkFrame(frame_proxy, fg_color="transparent")
        proxy_row.pack(pady=5, fill="x", padx=5)
        
        # Proxy status indicator
        self.lbl_proxy_status = ctk.CTkLabel(proxy_row, text="⬤ Direct Connection", font=("Roboto", 11), text_color="gray60")
        self.lbl_proxy_status.pack(side="left", padx=5)
        
        btn_proxy = ctk.CTkButton(proxy_row, text="Proxy Settings", command=self.open_proxy_settings, fg_color="#555", hover_color="#666", width=120)
        btn_proxy.pack(side="right", padx=5)
        
        # Update proxy status display
        self.update_proxy_status()

        # --- Bottom Panel: Download Manager ---
        frame_bottom = ctk.CTkFrame(self.tab_tools)
        frame_bottom.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=10)
        
        ctk.CTkLabel(frame_bottom, text="Download Manager", font=("Roboto", 16, "bold")).pack(anchor="w", padx=10, pady=5)
        
        self.download_list = ctk.CTkScrollableFrame(frame_bottom)
        self.download_list.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.download_rows = {} # Map filename -> widgets

    def setup_help_tab(self):
        scroll = ctk.CTkScrollableFrame(self.tab_help)
        scroll.pack(fill="both", expand=True)
        
        ctk.CTkLabel(scroll, text="How to extract the correct Polygon from Google Earth", font=("Roboto", 24, "bold")).pack(pady=20)
        
        ctk.CTkLabel(scroll, text="1. Select the Polygon Tool", font=("Roboto", 18, "bold")).pack(pady=(20,5), anchor="w", padx=20)
        ctk.CTkLabel(scroll, text="Open Google Earth and click the 'Add Polygon' tool in the toolbar.", font=("Roboto", 14), text_color="gray70").pack(anchor="w", padx=20)
        self.load_image(scroll, "Images/Polygon_Symbol.png", (400, 300))

        ctk.CTkLabel(scroll, text="2. Draw and Save", font=("Roboto", 18, "bold")).pack(pady=(30,5), anchor="w", padx=20)
        ctk.CTkLabel(scroll, text="Draw your area on the map. Name it and click 'OK' to save it to your Places.", font=("Roboto", 14), text_color="gray70").pack(anchor="w", padx=20)
        self.load_image(scroll, "Images/Save_Symbol.png", (400, 300))

        ctk.CTkLabel(scroll, text="3. Copy XML", font=("Roboto", 18, "bold")).pack(pady=(30,5), anchor="w", padx=20)
        ctk.CTkLabel(scroll, text="Right-click your polygon in the sidebar (or click the 3 dots), and select Copy.", font=("Roboto", 14), text_color="gray70").pack(anchor="w", padx=20)
        ctk.CTkLabel(scroll, text="Then simply click 'Paste from Clipboard' in this app.", font=("Roboto", 14), text_color="yellow").pack(anchor="w", padx=20)
        self.load_image(scroll, "Images/CopyElement_Symbol.png", (500, 350))

    def load_image(self, parent, path, size):
        if os.path.exists(path):
            try:
                pil_img = Image.open(path)
                img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)
                ctk.CTkLabel(parent, image=img, text="").pack(pady=10, anchor="w", padx=40)
            except Exception as e:
                 ctk.CTkLabel(parent, text=f"[Image missing: {os.path.basename(path)}]").pack(pady=10)
        else:
             print(f"[WARN] Image file not found: {path}")
             ctk.CTkLabel(parent, text=f"[Image not found: {path}]").pack(pady=10)

    # --- Logic ---

    def load_kml(self):
        file_path = filedialog.askopenfilename(filetypes=[("KML/XML Files", "*.xml *.kml")])
        if file_path:
            print(f"[INFO] Loading KML from: {file_path}")
            ewkt, error = PolygonExtractor.extract_from_kml(file_path=file_path)
            self.handle_extraction_result(ewkt, error)
    
    def paste_kml(self):
        try:
            content = self.clipboard_get()
            print("[INFO] Pasted content from clipboard.")
            if content.strip().startswith("<"):
                ewkt, error = PolygonExtractor.extract_from_kml(content_bytes=content.encode('utf-8'))
                self.handle_extraction_result(ewkt, error)
            else:
                 messagebox.showerror("Error", "Clipboard content does not look like XML.")
        except Exception as e:
             print(f"[ERROR] Clipboard paste failed: {e}")
             messagebox.showerror("Error", f"Clipboard error: {e}")

    def handle_extraction_result(self, ewkt, error):
        if error:
            print(f"[ERROR] Extraction failed: {error}")
            messagebox.showerror("Extraction Failed", error)
        else:
            self.text_polygon.delete("1.0", "end")
            self.text_polygon.insert("1.0", ewkt)
            print("[SUCCESS] Polygon extracted.")
            self.add_download_row("System", "Polygon extracted successfully!", 100, "Done", "")

    def copy_polygon(self):
        content = self.text_polygon.get("1.0", "end").strip()
        if content:
            self.clipboard_clear()
            self.clipboard_append(content)
            print("[INFO] Polygon copied to clipboard.")
            self.add_download_row("System", "Polygon copied to clipboard.", 100, "Done", "")

    def load_metalink(self):
        file_path = filedialog.askopenfilename(filetypes=[("Metalink Files", "*.meta4")])
        if not file_path: return
        
        self.downloader.download_dir = "downloads" # Default for meta4
        # Ensure dir exists
        if not os.path.exists("downloads"):
             os.makedirs("downloads")

        print(f"[INFO] Parsing metalink: {os.path.basename(file_path)}")
        files = self.downloader.parse_metalink(file_path)
        
        if files:
            print(f"[INFO] Found {len(files)} files in metalink.")
            # Show ALL pending first
            for fname, url in files:
                self.add_download_row(fname, "Pending...", 0, "-", "-")
                
            self.add_download_row("Batch", f"Queued {len(files)} files...", 0, "Processing", "...")
            threading.Thread(target=self.run_downloads_batch, args=(files,), daemon=True).start()
        else:
             print("[ERROR] No files found in metalink.")
             messagebox.showerror("Error", "Could not parse any files from the metalink.\nCheck the console/log for details.")

    def start_relief_download(self):
        poly = self.text_polygon.get("1.0", "end").strip()
        if not poly:
            messagebox.showwarning("Warning", "Please extract a polygon first.")
            return

        high_res = self.chk_high_res_relief.get() == 1
        res_label = "High-Res 300 DPI" if high_res else "Standard"
        print(f"[INFO] Starting Relief Download ({res_label})...")
        self.downloader.download_dir = "downloads_relief"
        if not os.path.exists("downloads_relief"):
            os.makedirs("downloads_relief")
            
        self.add_download_row("Relief", f"Generating {res_label} tiles...", 0, "Calculating", "...")
        threading.Thread(target=self.run_relief_gen, args=(poly, "relief", "tiff", high_res), daemon=True).start()

    def start_satellite_download(self):
        poly = self.text_polygon.get("1.0", "end").strip()
        if not poly:
            messagebox.showwarning("Warning", "Please extract a polygon first.")
            return

        fmt = self.seg_format.get().lower()
        print(f"[INFO] Starting Satellite (DOP40 WMS) Download... Format: {fmt}")
        
        self.downloader.download_dir = "downloads_satellite"
        if not os.path.exists("downloads_satellite"):
            os.makedirs("downloads_satellite")
            
        self.add_download_row("DOP40", f"Generating DOP40 ({fmt}) tiles...", 0, "Calculating", "...")
        threading.Thread(target=self.run_relief_gen, args=(poly, "dop40", fmt, False), daemon=True).start()

    def start_dop20_download(self):
        """Download raw DOP20 satellite imagery files (highest quality)."""
        poly = self.text_polygon.get("1.0", "end").strip()
        if not poly:
            messagebox.showwarning("Warning", "Please extract a polygon first.")
            return

        print("[INFO] Starting DOP20 (Raw TIF) Download...")
        
        self.downloader.download_dir = "downloads_dop20"
        if not os.path.exists("downloads_dop20"):
            os.makedirs("downloads_dop20")
            
        self.add_download_row("DOP20", "Generating file list...", 0, "Calculating", "...")
        threading.Thread(target=self.run_raw_download, args=(poly, "dop20"), daemon=True).start()

    def run_raw_download(self, poly, dataset):
        """Handler for raw file downloads (DOP20, DGM1, etc.)."""
        print(f"[INFO] Generating {dataset.upper()} file list for polygon...")
        
        files = self.downloader.generate_1km_grid_files(poly, dataset=dataset)
        if files:
            print(f"[INFO] Generated {len(files)} files to download.")
            
            for fname, url in files:
                self.after(0, lambda f=fname: self.add_download_row(f, "Pending...", 0, "-", "-"))
                
            self.add_download_row(dataset.upper(), f"Queued {len(files)} files.", 100, "Ready", "")
            self.run_downloads_batch(files)
        else:
            print("[WARN] No files generated for polygon.")
            self.add_download_row(dataset.upper(), "No intersecting files found.", 0, "Error", "")

    def run_relief_gen(self, poly, type_key, format_ext="jpg", high_res=False):
        print(f"[INFO] Generating {type_key} tiles for polygon (Format: {format_ext}, High-Res: {high_res})...")
        # 'dop40' or 'relief' - logic is handled in downloader now
        layer = "by_relief_schraeglicht" if type_key == "relief" else "dop40"
        
        tiles = self.downloader.generate_relief_tiles(poly, layer=layer, format_ext=format_ext, high_res=high_res)
        if tiles:
             print(f"[INFO] Generated {len(tiles)} tiles.")
             
             # Show pending state immediately
             for fname, url in tiles:
                  # Use 'after' to ensure thread safety when manipulating UI from thread
                  self.after(0, lambda f=fname: self.add_download_row(f, "Pending...", 0, "-", "-"))
                  
             self.add_download_row(type_key.title(), f"Queued {len(tiles)} tiles.", 100, "Ready", "")
             self.run_downloads_batch(tiles)
        else:
             print("[WARN] No tiles generated.")
             self.add_download_row(type_key.title(), "No intersecting tiles found.", 0, "Error", "")

    def add_download_row(self, filename, status, percent, speed, eta):
        if filename in self.download_rows:
            widgets = self.download_rows[filename]
            try:
                widgets['status'].configure(text=status)
                widgets['progress'].set(percent / 100)
                widgets['metrics'].configure(text=f"{speed} | ETA: {eta}")
            except:
                pass
            return

        row_frame = ctk.CTkFrame(self.download_list)
        row_frame.pack(fill="x", pady=2, padx=2)
        row_frame.grid_columnconfigure(1, weight=1)
        
        lbl_name = ctk.CTkLabel(row_frame, text=filename, width=150, anchor="w", font=("Roboto", 12, "bold"))
        lbl_name.grid(row=0, column=0, padx=5, pady=5)
        
        progress = ctk.CTkProgressBar(row_frame)
        progress.grid(row=0, column=1, sticky="ew", padx=5)
        progress.set(percent / 100)
        
        lbl_status = ctk.CTkLabel(row_frame, text=status, width=120, anchor="e", font=("Roboto", 11))
        lbl_status.grid(row=0, column=2, padx=5)
        
        lbl_metrics = ctk.CTkLabel(row_frame, text=f"{speed} | ETA: {eta}", width=150, anchor="e", font=("Roboto", 11, "bold"))
        lbl_metrics.grid(row=0, column=3, padx=5)

        self.download_rows[filename] = {
            'frame': row_frame,
            'status': lbl_status,
            'progress': progress,
            'metrics': lbl_metrics
        }

    def run_downloads_batch(self, files_list):
        import concurrent.futures
        
        def update_ui(fname, percent, status, speed, eta):
             self.after(0, lambda: self.add_download_row(fname, status, percent, speed, eta))

        if self.downloader.download_dir and not os.path.exists(self.downloader.download_dir):
            try:
                os.makedirs(self.downloader.download_dir)
            except:
                pass

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(self.downloader.download_file, url, fname, update_ui)
                for fname, url in files_list
            ]
            concurrent.futures.wait(futures)
        print("[INFO] Batch download finished.")

    # =========================================================================
    # Proxy Settings
    # =========================================================================
    
    def update_proxy_status(self):
        """Update the proxy status indicator in the UI."""
        if not PROXY_AVAILABLE or not self.proxy_manager:
            self.lbl_proxy_status.configure(text="⬤ Proxy Module Not Available", text_color="gray50")
            return
        
        status = self.proxy_manager.get_status()
        if status["enabled"]:
            proxy_url = status["proxy_url"]
            # Truncate long URLs
            if len(proxy_url) > 40:
                proxy_url = proxy_url[:37] + "..."
            auth_info = f" ({status['auth_type']})" if status["auth_type"] != "none" else ""
            self.lbl_proxy_status.configure(text=f"⬤ {proxy_url}{auth_info}", text_color="#27ae60")
        else:
            self.lbl_proxy_status.configure(text="⬤ Direct Connection", text_color="gray60")
    
    def open_proxy_settings(self):
        """Open the proxy settings dialog."""
        if not PROXY_AVAILABLE:
            messagebox.showwarning("Not Available", "Proxy module is not available.\nCheck if backend/proxy_manager.py exists.")
            return
        
        dialog = ProxySettingsDialog(self, self.proxy_manager)
        self.wait_window(dialog)
        
        # Update status and reinitialize downloader with new settings
        self.update_proxy_status()
        self.downloader.proxy_manager = self.proxy_manager
        self.downloader._session = None  # Force new session


    # =========================================================================
    # OSM Data Tab
    # =========================================================================

    def setup_osm_tab(self):
        self.tab_osm.grid_columnconfigure(0, weight=1)
        self.tab_osm.grid_columnconfigure(1, weight=1)
        self.tab_osm.grid_rowconfigure(0, weight=0)
        self.tab_osm.grid_rowconfigure(1, weight=1)

        # ── Left panel: area / buffer / actions ───────────────────────────
        frame_left = ctk.CTkFrame(self.tab_osm)
        frame_left.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(frame_left, text="Area & Settings",
                     font=("Roboto", 18, "bold")).pack(pady=10)

        # Polygon preview (read-only)
        ctk.CTkLabel(frame_left, text="Active polygon (from Map Tools tab):",
                     anchor="w", font=("Roboto", 12), text_color="gray60").pack(
            fill="x", padx=10)
        self.osm_poly_preview = ctk.CTkTextbox(frame_left, height=55, state="disabled",
                                                text_color="gray50")
        self.osm_poly_preview.pack(fill="x", padx=10, pady=(0, 8))

        # Refresh polygon button
        ctk.CTkButton(frame_left, text="Refresh Polygon from Map Tools",
                      command=self._osm_refresh_polygon,
                      fg_color="transparent", border_width=1, height=28).pack(
            padx=10, pady=(0, 8))

        # Area estimate
        self.lbl_osm_area = ctk.CTkLabel(frame_left, text="Area estimate: —",
                                          font=("Roboto", 12), text_color="gray60")
        self.lbl_osm_area.pack(anchor="w", padx=10)

        # Expand / buffer
        frame_buf = ctk.CTkFrame(frame_left, fg_color="gray20")
        frame_buf.pack(fill="x", padx=10, pady=8)
        ctk.CTkLabel(frame_buf, text="Expand area beyond polygon boundary:",
                     font=("Roboto", 13, "bold")).pack(anchor="w", padx=8, pady=(8, 2))

        buf_entry_row = ctk.CTkFrame(frame_buf, fg_color="transparent")
        buf_entry_row.pack(fill="x", padx=8, pady=4)

        self.osm_buffer_var = tk.StringVar(value="0")
        self.osm_buffer_var.trace_add("write", lambda *_: self._osm_update_area())

        self.osm_buf_entry = ctk.CTkEntry(buf_entry_row, textvariable=self.osm_buffer_var,
                                           width=70)
        self.osm_buf_entry.pack(side="left")
        ctk.CTkLabel(buf_entry_row, text="meters", text_color="gray60").pack(
            side="left", padx=6)

        # Preset buttons
        preset_row = ctk.CTkFrame(frame_buf, fg_color="transparent")
        preset_row.pack(fill="x", padx=8, pady=(0, 8))
        for label, val in [("0 m", "0"), ("250 m", "250"), ("500 m", "500"),
                            ("1 km", "1000"), ("5 km", "5000")]:
            ctk.CTkButton(preset_row, text=label, width=52, height=26,
                          fg_color="gray30", hover_color="gray40",
                          command=lambda v=val: self.osm_buffer_var.set(v)).pack(
                side="left", padx=2)

        # Output directory
        frame_out = ctk.CTkFrame(frame_left, fg_color="gray20")
        frame_out.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(frame_out, text="Output directory:",
                     font=("Roboto", 13, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
        out_row = ctk.CTkFrame(frame_out, fg_color="transparent")
        out_row.pack(fill="x", padx=8, pady=(0, 4))
        self.osm_dir_var = tk.StringVar(value="downloads_osm")
        ctk.CTkEntry(out_row, textvariable=self.osm_dir_var).pack(
            side="left", fill="x", expand=True)
        ctk.CTkButton(out_row, text="...", width=30, height=28,
                      command=self._osm_browse_dir,
                      fg_color="gray30", hover_color="gray40").pack(side="left", padx=4)
        ctk.CTkButton(frame_out, text="Open Output Folder",
                      command=lambda: self._open_folder(self.osm_dir_var.get().strip() or "downloads_osm"),
                      fg_color="gray30", hover_color="gray40", height=28).pack(
            fill="x", padx=8, pady=(0, 8))

        # Output format
        frame_fmt = ctk.CTkFrame(frame_left, fg_color="gray20")
        frame_fmt.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(frame_fmt, text="Output format:",
                     font=("Roboto", 13, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
        self._osm_format_labels = {lbl: key for key, (lbl, _ext, _out) in OUTPUT_FORMATS.items()}
        default_label = OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT][0]
        self.osm_format_var = tk.StringVar(value=default_label)
        self.osm_format_menu = ctk.CTkOptionMenu(
            frame_fmt, values=list(self._osm_format_labels.keys()),
            variable=self.osm_format_var, command=self._osm_format_changed)
        self.osm_format_menu.pack(fill="x", padx=8, pady=(0, 4))
        self.osm_format_hint = ctk.CTkLabel(
            frame_fmt, text="", font=("Roboto", 11), text_color="gray60",
            anchor="w", justify="left", wraplength=320)
        self.osm_format_hint.pack(fill="x", padx=8, pady=(0, 8))
        self._osm_format_changed(default_label)

        # Action buttons
        ctk.CTkButton(frame_left, text="Download Selected Layers",
                      command=self.start_osm_download,
                      fg_color="#1e8bc3", hover_color="#3498db",
                      height=40, font=("Roboto", 14, "bold")).pack(
            fill="x", padx=10, pady=(8, 4))

        ctk.CTkButton(frame_left, text="Cancel Download",
                      command=self._osm_cancel_download,
                      fg_color="#7a2a2a", hover_color="#a33",
                      height=30).pack(fill="x", padx=10, pady=(0, 8))

        # ── Right panel: layer selection ───────────────────────────────────
        frame_right = ctk.CTkFrame(self.tab_osm)
        frame_right.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(frame_right, text="Select Layers",
                     font=("Roboto", 18, "bold")).pack(pady=10)

        layers_scroll = ctk.CTkScrollableFrame(frame_right)
        layers_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.osm_layer_vars = {}
        for layer_name in LAYER_ORDER:
            info = OSM_LAYERS[layer_name]
            is_default = layer_name in DEFAULT_LAYERS

            row = ctk.CTkFrame(layers_scroll, fg_color="gray20")
            row.pack(fill="x", padx=4, pady=3)
            row.grid_columnconfigure(1, weight=1)

            var = tk.BooleanVar(value=is_default)
            self.osm_layer_vars[layer_name] = var

            chk = ctk.CTkCheckBox(row, text="", variable=var, width=24,
                                  fg_color=info["fg_color"], hover_color=info["fg_color"])
            chk.grid(row=0, column=0, padx=(8, 4), pady=6)

            ctk.CTkLabel(row, text=layer_name,
                         font=("Roboto", 13, "bold"), anchor="w").grid(
                row=0, column=1, sticky="w")
            ctk.CTkLabel(row, text=info["description"],
                         font=("Roboto", 11), text_color="gray60", anchor="w").grid(
                row=1, column=1, sticky="w", padx=2, pady=(0, 4))

        # Select / deselect all
        btn_row = ctk.CTkFrame(frame_right, fg_color="transparent")
        btn_row.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkButton(btn_row, text="Select All", width=100,
                      fg_color="gray30", hover_color="gray40",
                      command=lambda: [v.set(True) for v in self.osm_layer_vars.values()]).pack(
            side="left", padx=4)
        ctk.CTkButton(btn_row, text="Clear All", width=100,
                      fg_color="gray30", hover_color="gray40",
                      command=lambda: [v.set(False) for v in self.osm_layer_vars.values()]).pack(
            side="left", padx=4)

        # ── Bottom: download progress ──────────────────────────────────────
        frame_bottom = ctk.CTkFrame(self.tab_osm)
        frame_bottom.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 10))

        ctk.CTkLabel(frame_bottom, text="OSM Download Progress",
                     font=("Roboto", 16, "bold")).pack(anchor="w", padx=10, pady=5)

        self.osm_download_list = ctk.CTkScrollableFrame(frame_bottom)
        self.osm_download_list.pack(fill="both", expand=True, padx=5, pady=5)
        self.osm_download_rows = {}

    def _osm_refresh_polygon(self):
        """Copy the current polygon from Map Tools into the OSM preview."""
        poly = self.text_polygon.get("1.0", "end").strip()
        self.osm_poly_preview.configure(state="normal")
        self.osm_poly_preview.delete("1.0", "end")
        self.osm_poly_preview.insert("1.0", poly if poly else "(no polygon loaded)")
        self.osm_poly_preview.configure(state="disabled")
        self._osm_update_area()

    def _osm_update_area(self):
        """Recompute and display the bounding-box area estimate."""
        poly = self.text_polygon.get("1.0", "end").strip()
        if not poly:
            self.lbl_osm_area.configure(text="Area estimate: — (no polygon)")
            return
        try:
            buffer = int(self.osm_buffer_var.get() or "0")
        except ValueError:
            buffer = 0
        try:
            bbox = self.osm_downloader.calculate_bbox(poly, buffer)
            area = self.osm_downloader.estimate_area_km2(bbox)
            self.lbl_osm_area.configure(
                text=f"Area estimate: ~{area:.1f} km²  (buffer: {buffer} m)")
        except Exception:
            self.lbl_osm_area.configure(text="Area estimate: invalid polygon")

    def _osm_browse_dir(self):
        path = filedialog.askdirectory(title="Select OSM output directory")
        if path:
            self.osm_dir_var.set(path)

    def _osm_format_changed(self, label):
        fmt_key = self._osm_format_labels.get(label, DEFAULT_OUTPUT_FORMAT)
        if fmt_key == "osm":
            hint = ("OSM XML: standards-compliant .osm file — ready for Train3D, "
                    "JOSM, osm2world.")
        else:
            hint = ("GeoJSON: one .geojson per layer — compatible with QGIS, OSG, "
                    "Terrain3D.")
        self.osm_format_hint.configure(text=hint)

    def _osm_cancel_download(self):
        if getattr(self.osm_downloader, "stop_event", False):
            return
        self.osm_downloader.stop_event = True
        print("[OSM] Cancel requested — stopping after current layer.")

    def _open_folder(self, path):
        if not path:
            return
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            print(f"[WARN] Could not create folder {path}: {e}")
        abspath = os.path.abspath(path)
        try:
            if sys.platform.startswith("win"):
                os.startfile(abspath)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", abspath])
            else:
                subprocess.Popen(["xdg-open", abspath])
        except Exception as e:
            print(f"[ERROR] Could not open folder {abspath}: {e}")
            messagebox.showerror("Open Folder", f"Could not open {abspath}:\n{e}")

    def start_osm_download(self):
        poly = self.text_polygon.get("1.0", "end").strip()
        if not poly:
            messagebox.showwarning("Warning", "Please extract a polygon first (Map Tools tab).")
            return

        selected = [name for name, var in self.osm_layer_vars.items() if var.get()]
        if not selected:
            messagebox.showwarning("Warning", "Please select at least one layer.")
            return

        try:
            buffer = int(self.osm_buffer_var.get() or "0")
        except ValueError:
            buffer = 0

        out_dir = self.osm_dir_var.get().strip() or "downloads_osm"
        self.osm_downloader.download_dir = out_dir
        fmt_key = self._osm_format_labels.get(self.osm_format_var.get(), DEFAULT_OUTPUT_FORMAT)
        self.osm_downloader.output_format = fmt_key
        self.osm_downloader.stop_event = False

        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

        # Prime progress rows
        for name in selected:
            self.add_osm_row(name, "Queued...", 0, "-", "-")

        print(f"[OSM] Starting download of {len(selected)} layers, "
              f"buffer={buffer}m, format={fmt_key}, dir={out_dir}")
        threading.Thread(
            target=self.run_osm_downloads, args=(poly, selected, buffer), daemon=True
        ).start()

    def run_osm_downloads(self, poly, layers, buffer_meters):
        def cb(name, pct, status, speed, eta):
            self.after(0, lambda n=name, p=pct, s=status, sp=speed, e=eta:
                       self.add_osm_row(n, s, p, sp, e))

        results = self.osm_downloader.download_selected(poly, layers, buffer_meters, cb)

        ok_count = sum(1 for ok, _ in results.values() if ok)
        print(f"[OSM] Finished: {ok_count}/{len(results)} layers downloaded successfully.")

    def add_osm_row(self, filename, status, percent, speed, eta):
        if filename in self.osm_download_rows:
            w = self.osm_download_rows[filename]
            try:
                w["status"].configure(text=status)
                w["progress"].set(percent / 100)
                w["metrics"].configure(text=f"{speed} | {eta}")
            except Exception:
                pass
            return

        row = ctk.CTkFrame(self.osm_download_list)
        row.pack(fill="x", pady=2, padx=2)
        row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(row, text=filename, width=160, anchor="w",
                     font=("Roboto", 12, "bold")).grid(row=0, column=0, padx=5, pady=5)

        bar = ctk.CTkProgressBar(row)
        bar.grid(row=0, column=1, sticky="ew", padx=5)
        bar.set(percent / 100)

        lbl_status = ctk.CTkLabel(row, text=status, width=200, anchor="w",
                                   font=("Roboto", 11))
        lbl_status.grid(row=0, column=2, padx=5)

        lbl_metrics = ctk.CTkLabel(row, text=f"{speed} | {eta}", width=120, anchor="e",
                                    font=("Roboto", 11, "bold"))
        lbl_metrics.grid(row=0, column=3, padx=5)

        self.osm_download_rows[filename] = {
            "frame": row, "status": lbl_status, "progress": bar, "metrics": lbl_metrics
        }


class ProxySettingsDialog(ctk.CTkToplevel):
    """Dialog for configuring proxy settings."""
    
    def __init__(self, parent, proxy_manager):
        super().__init__(parent)
        
        self.proxy_manager = proxy_manager
        self.title("Proxy Settings")
        self.geometry("500x450")
        self.resizable(False, False)
        
        # Make modal
        self.transient(parent)
        self.grab_set()
        
        self.setup_ui()
        self.load_current_settings()
    
    def setup_ui(self):
        # Main container
        container = ctk.CTkFrame(self)
        container.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Title
        ctk.CTkLabel(container, text="Proxy Configuration", font=("Roboto", 18, "bold")).pack(pady=(0, 15))
        
        # --- Mode Selection ---
        mode_frame = ctk.CTkFrame(container, fg_color="transparent")
        mode_frame.pack(fill="x", pady=5)
        
        self.var_mode = ctk.StringVar(value="auto")
        ctk.CTkRadioButton(mode_frame, text="Auto-Detect", variable=self.var_mode, value="auto", command=self.on_mode_change).pack(side="left", padx=10)
        ctk.CTkRadioButton(mode_frame, text="Manual", variable=self.var_mode, value="manual", command=self.on_mode_change).pack(side="left", padx=10)
        ctk.CTkRadioButton(mode_frame, text="No Proxy", variable=self.var_mode, value="none", command=self.on_mode_change).pack(side="left", padx=10)
        
        # --- Manual Settings Frame ---
        self.manual_frame = ctk.CTkFrame(container, fg_color="gray20")
        self.manual_frame.pack(fill="x", pady=10, padx=5)
        
        # Proxy URL
        ctk.CTkLabel(self.manual_frame, text="Proxy URL:", anchor="w").pack(fill="x", padx=10, pady=(10, 0))
        self.entry_proxy_url = ctk.CTkEntry(self.manual_frame, placeholder_text="http://proxy.company.com:8080")
        self.entry_proxy_url.pack(fill="x", padx=10, pady=5)
        
        # Authentication Type
        ctk.CTkLabel(self.manual_frame, text="Authentication:", anchor="w").pack(fill="x", padx=10, pady=(10, 0))
        self.seg_auth = ctk.CTkSegmentedButton(self.manual_frame, values=["None", "Basic", "NTLM"])
        self.seg_auth.set("None")
        self.seg_auth.pack(fill="x", padx=10, pady=5)
        self.seg_auth.configure(command=self.on_auth_change)
        
        # Credentials Frame
        self.creds_frame = ctk.CTkFrame(self.manual_frame, fg_color="transparent")
        self.creds_frame.pack(fill="x", padx=10, pady=5)
        
        # Domain (for NTLM)
        self.lbl_domain = ctk.CTkLabel(self.creds_frame, text="Domain:")
        self.entry_domain = ctk.CTkEntry(self.creds_frame, placeholder_text="COMPANY", width=150)
        
        # Username
        ctk.CTkLabel(self.creds_frame, text="Username:").grid(row=0, column=0, sticky="w", pady=2)
        self.entry_username = ctk.CTkEntry(self.creds_frame, placeholder_text="username")
        self.entry_username.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        
        # Password
        ctk.CTkLabel(self.creds_frame, text="Password:").grid(row=1, column=0, sticky="w", pady=2)
        self.entry_password = ctk.CTkEntry(self.creds_frame, placeholder_text="password", show="*")
        self.entry_password.grid(row=1, column=1, sticky="ew", padx=5, pady=2)
        
        self.creds_frame.grid_columnconfigure(1, weight=1)
        
        # --- Status / Info ---
        self.lbl_status = ctk.CTkLabel(container, text="", font=("Roboto", 11), text_color="gray60")
        self.lbl_status.pack(pady=10)
        
        # --- Buttons ---
        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.pack(fill="x", pady=10)
        
        ctk.CTkButton(btn_frame, text="Auto-Detect Now", command=self.do_auto_detect, fg_color="#555", width=130).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Test Connection", command=self.do_test_connection, fg_color="#3498db", width=130).pack(side="left", padx=5)
        
        btn_frame2 = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame2.pack(fill="x", pady=5)
        
        ctk.CTkButton(btn_frame2, text="Save & Close", command=self.do_save, fg_color="#27ae60", width=150).pack(side="right", padx=5)
        ctk.CTkButton(btn_frame2, text="Cancel", command=self.destroy, fg_color="#555", width=100).pack(side="right", padx=5)
        
        # Initial state
        self.on_mode_change()
        self.on_auth_change("None")
    
    def load_current_settings(self):
        """Load current proxy settings into the form."""
        config = self.proxy_manager.config

        if not config.enabled:
            self.var_mode.set("none")
        elif config.auto_detect:
            self.var_mode.set("auto")
        else:
            self.var_mode.set("manual")

        self.entry_proxy_url.delete(0, "end")
        self.entry_proxy_url.insert(0, config.proxy_url)

        auth_map = {"none": "None", "basic": "Basic", "ntlm": "NTLM"}
        self.seg_auth.set(auth_map.get(config.auth_type, "None"))

        self.entry_username.delete(0, "end")
        self.entry_username.insert(0, config.username)

        # Password is not persisted to disk, but if it is still in memory from
        # an earlier Save-in-this-session, re-populate the field so the user
        # doesn't accidentally save an empty password (→ guaranteed HTTP 407).
        self.entry_password.delete(0, "end")
        if config.password:
            self.entry_password.insert(0, config.password)

        self.entry_domain.delete(0, "end")
        self.entry_domain.insert(0, config.domain)
        
        self.on_mode_change()
        self.on_auth_change(self.seg_auth.get())
    
    def on_mode_change(self):
        """Handle mode radio button change."""
        mode = self.var_mode.get()
        if mode == "manual":
            for child in self.manual_frame.winfo_children():
                try:
                    child.configure(state="normal")
                except:
                    pass
        else:
            # Disable manual inputs for auto/none modes
            pass  # Keep enabled for visibility but will be ignored
    
    def on_auth_change(self, value):
        """Handle auth type change."""
        if value == "NTLM":
            self.lbl_domain.grid(row=2, column=0, sticky="w", pady=2)
            self.entry_domain.grid(row=2, column=1, sticky="ew", padx=5, pady=2)
        else:
            self.lbl_domain.grid_forget()
            self.entry_domain.grid_forget()
        
        if value == "None":
            self.entry_username.configure(state="disabled")
            self.entry_password.configure(state="disabled")
        else:
            self.entry_username.configure(state="normal")
            self.entry_password.configure(state="normal")
    
    def do_auto_detect(self):
        """Run auto-detection."""
        self.lbl_status.configure(text="Detecting proxy settings...", text_color="yellow")
        self.update()

        found = self.proxy_manager.auto_detect()
        msg = getattr(self.proxy_manager, "last_detect_message", "") or ""

        if found:
            self.entry_proxy_url.delete(0, "end")
            self.entry_proxy_url.insert(0, self.proxy_manager.config.proxy_url)
            self.lbl_status.configure(
                text=f"✓ Detected: {self.proxy_manager.config.proxy_url}",
                text_color="#27ae60",
            )
            self.var_mode.set("auto")
        else:
            # Preserve an existing manual config if one is still active
            if self.proxy_manager.config.enabled and self.proxy_manager.config.proxy_url:
                self.lbl_status.configure(
                    text=f"⚠ {msg or 'Auto-detect failed. Using saved manual proxy.'}",
                    text_color="#f39c12",
                )
                self.var_mode.set("manual")
            else:
                self.lbl_status.configure(
                    text=msg or "No proxy detected. Using direct connection.",
                    text_color="gray60",
                )
                self.var_mode.set("none")
        self.on_mode_change()
    
    def do_test_connection(self):
        """Test the current connection."""
        self.lbl_status.configure(text="Testing connection...", text_color="yellow")
        self.update()
        
        # Apply current form settings temporarily
        self.apply_settings(save=False)
        
        success, message = self.proxy_manager.test_connection()
        
        if success:
            self.lbl_status.configure(text=f"✓ {message}", text_color="#27ae60")
        else:
            self.lbl_status.configure(text=f"✗ {message}", text_color="#e74c3c")
    
    def apply_settings(self, save=True):
        """Apply form settings to proxy manager."""
        mode = self.var_mode.get()

        if mode == "none":
            self.proxy_manager.disable_proxy()
        elif mode == "auto":
            self.proxy_manager.auto_detect()
        else:  # manual
            auth_map = {"None": "none", "Basic": "basic", "NTLM": "ntlm"}
            auth_type = auth_map.get(self.seg_auth.get(), "none")
            username = self.entry_username.get()
            password = self.entry_password.get()

            # Catch a very common footgun: user saved once, reopened the
            # dialog, didn't re-enter the password (it wasn't persisted to
            # disk), and clicks Save. Without this guard we'd silently
            # overwrite the still-in-memory password with "" and the next
            # request returns 407.
            if auth_type in ("basic", "ntlm") and username and not password:
                existing = self.proxy_manager.config.password
                if existing:
                    password = existing
                    self.lbl_status.configure(
                        text="ℹ Using password from current session "
                             "(field was empty)",
                        text_color="#f39c12",
                    )
                else:
                    self.lbl_status.configure(
                        text="⚠ Password is empty — proxy will return 407",
                        text_color="#e74c3c",
                    )

            self.proxy_manager.set_manual_proxy(
                proxy_url=self.entry_proxy_url.get(),
                auth_type=auth_type,
                username=username,
                password=password,
                domain=self.entry_domain.get()
            )
        
        if save:
            self.proxy_manager.save_config()
    
    def do_save(self):
        """Save settings and close."""
        self.apply_settings(save=True)
        self.destroy()

if __name__ == "__main__":
    app = OpenMapUnifierApp()
    app.mainloop()
