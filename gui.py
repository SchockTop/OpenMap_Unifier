
import customtkinter as ctk
from PIL import Image
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import sys
import os
import time

from backend.geometry import PolygonExtractor
from backend.downloader import MapDownloader

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
        
        self.downloader = MapDownloader()
        
        # --- Tab View ---
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=20)
        
        self.tab_tools = self.tabview.add("Map Tools")
        self.tab_help = self.tabview.add("Help & Guide")
        self.tab_console = self.tabview.add("Console")
        
        self.setup_tools_tab()
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
        
        # DOP40 (WMS Tiles)
        sat_row2 = ctk.CTkFrame(frame_sat, fg_color="transparent")
        sat_row2.pack(pady=3, fill="x", padx=5)
        
        btn_dop40 = ctk.CTkButton(sat_row2, text="Download DOP40 (WMS)", command=self.start_satellite_download, fg_color="#3498db", hover_color="#2980b9")
        btn_dop40.pack(side="left", padx=5)
        
        self.seg_format = ctk.CTkSegmentedButton(sat_row2, values=["JPG", "TIF"])
        self.seg_format.set("JPG")
        self.seg_format.pack(side="left", padx=5)
        
        # --- Mass Data Section ---
        frame_meta = ctk.CTkFrame(frame_right, fg_color="gray20")
        frame_meta.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_meta, text="Mass Data (.meta4)", font=("Roboto", 14, "bold")).pack(pady=5)
        ctk.CTkButton(frame_meta, text="Select & Download .meta4", command=self.load_metalink).pack(pady=10)

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

if __name__ == "__main__":
    app = OpenMapUnifierApp()
    app.mainloop()
