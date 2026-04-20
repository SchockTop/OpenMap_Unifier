
import customtkinter as ctk
from PIL import Image
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import sys
import os
import time

from backend.geometry import PolygonExtractor
from backend.downloader import MapDownloader, BAYERN_DATASETS, BAYERN_CATEGORY_LABELS
from backend.worldfile import generate_for_folder as generate_worldfiles
from backend.osm_downloader import OSMDownloader, LAYER_ORDER, DEFAULT_LAYERS, LAYERS as OSM_LAYERS

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
            # Respect saved config: only auto-detect if user hasn't saved manual
            # settings, or explicitly chose auto-detect mode. This prevents
            # auto_detect() from clobbering saved manual host/username/auth_type.
            cfg = self.proxy_manager.config
            if cfg.auto_detect or (not cfg.enabled and not cfg.proxy_url):
                self.proxy_manager.auto_detect()
        
        # Create downloader with proxy support
        self.downloader = MapDownloader(proxy_manager=self.proxy_manager)
        self.osm_downloader = OSMDownloader(proxy_manager=self.proxy_manager)
        
        # --- Tab View ---
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=20)
        
        self.tab_tools = self.tabview.add("Map Tools")
        self.tab_osm = self.tabview.add("OSM Data")
        self.tab_downloads = self.tabview.add("Downloads")
        self.tab_help = self.tabview.add("Help & Guide")
        self.tab_console = self.tabview.add("Console")

        self.setup_tools_tab()
        self.setup_osm_tab()
        self.setup_downloads_tab()
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
        
        # --- Bayern Open Data picker (catalog-driven) --------------------
        frame_bayern = ctk.CTkFrame(frame_right, fg_color="gray20")
        frame_bayern.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_bayern, text="Bayern Open Data",
                     font=("Roboto", 14, "bold")).pack(pady=(6, 2))
        ctk.CTkLabel(frame_bayern,
                     text="Pick one or more datasets. DGM1 = real height data (for Blender / displacement).",
                     font=("Roboto", 10), text_color="gray60",
                     wraplength=460, justify="left").pack(padx=8, pady=(0, 4))

        scroll_bayern = ctk.CTkScrollableFrame(frame_bayern, height=260)
        scroll_bayern.pack(fill="x", padx=6, pady=4)

        # Build checkboxes grouped by category, driven by BAYERN_DATASETS.
        self.bayern_dataset_vars = {}  # key -> BooleanVar
        for cat_key, cat_label in BAYERN_CATEGORY_LABELS.items():
            entries = [(k, v) for k, v in BAYERN_DATASETS.items() if v["category"] == cat_key]
            if not entries:
                continue
            ctk.CTkLabel(scroll_bayern, text=cat_label,
                         font=("Roboto", 12, "bold"),
                         text_color="#8cc8ff").pack(anchor="w", padx=6, pady=(6, 2))
            for key, meta in entries:
                row = ctk.CTkFrame(scroll_bayern, fg_color="gray15")
                row.pack(fill="x", padx=4, pady=2)
                var = tk.BooleanVar(value=(key == "dgm1"))  # default-on: DGM1
                self.bayern_dataset_vars[key] = var
                ctk.CTkCheckBox(row, text=meta["label"], variable=var,
                                font=("Roboto", 12)).pack(anchor="w", padx=6, pady=(4, 0))
                ctk.CTkLabel(row,
                             text=f"{meta['description']}   ({meta['resolution']}, {meta['ext']})",
                             font=("Roboto", 10), text_color="gray60",
                             anchor="w", justify="left",
                             wraplength=430).pack(anchor="w", padx=26, pady=(0, 4))

        # WMS-only option: high-res toggle for WMS renders (300 DPI).
        wms_opts = ctk.CTkFrame(frame_bayern, fg_color="transparent")
        wms_opts.pack(fill="x", padx=6, pady=(0, 4))
        self.chk_high_res_relief = ctk.CTkCheckBox(wms_opts, text="WMS high-res (300 DPI)")
        self.chk_high_res_relief.pack(side="left", padx=4)

        # Format segmented button — only applies to DOP40 WMS render.
        ctk.CTkLabel(wms_opts, text="DOP40-WMS format:",
                     font=("Roboto", 10), text_color="gray60").pack(side="left", padx=(12, 2))
        self.seg_format = ctk.CTkSegmentedButton(wms_opts, values=["JPG", "TIF"], width=120)
        self.seg_format.set("JPG")
        self.seg_format.pack(side="left", padx=2)

        ctk.CTkButton(frame_bayern, text="Download Selected Bayern Datasets",
                      command=self.start_bayern_download,
                      fg_color="#27ae60", hover_color="#2ecc71",
                      height=36, font=("Roboto", 13, "bold")).pack(fill="x", padx=8, pady=(4, 4))

        # License / attribution footer
        ctk.CTkLabel(frame_bayern,
                     text="© Bayerische Vermessungsverwaltung — CC BY 4.0\n"
                          "Attribution: 'Datenquelle: Bayerische Vermessungsverwaltung – www.geodaten.bayern.de'",
                     font=("Roboto", 9), text_color="gray50",
                     justify="left").pack(anchor="w", padx=8, pady=(0, 6))
        
        # --- Mass Data Section ---
        frame_meta = ctk.CTkFrame(frame_right, fg_color="gray20")
        frame_meta.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(frame_meta, text="Mass Data (.meta4)", font=("Roboto", 14, "bold")).pack(pady=5)
        ctk.CTkButton(frame_meta, text="Select & Download .meta4", command=self.load_metalink).pack(pady=10)

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

    # =========================================================================
    # Downloads tab — overview + clear + license attribution
    # =========================================================================

    # Folders the Downloads tab tracks. Tuples of (display_name, relative_path).
    DOWNLOAD_FOLDERS = [
        ("Bayern: DGM1 (Height)",          os.path.join("downloads_bayern", "dgm1")),
        ("Bayern: DGM5 (Height)",          os.path.join("downloads_bayern", "dgm5")),
        ("Bayern: DOP20 (Orthophoto)",     os.path.join("downloads_bayern", "dop20")),
        ("Bayern: DOP40 (Orthophoto)",     os.path.join("downloads_bayern", "dop40")),
        ("Bayern: LoD2 (3D buildings)",    os.path.join("downloads_bayern", "lod2")),
        ("Bayern: Laser (LiDAR LAZ)",      os.path.join("downloads_bayern", "laser")),
        ("Bayern: Relief WMS",             os.path.join("downloads_bayern", "relief_wms")),
        ("Bayern: DOP40 WMS",              os.path.join("downloads_bayern", "dop40_wms")),
        ("OSM Data",                       "downloads_osm"),
        # Legacy folders from earlier versions — shown if present.
        ("Legacy: downloads_relief",       "downloads_relief"),
        ("Legacy: downloads_satellite",    "downloads_satellite"),
        ("Legacy: downloads_dop20",        "downloads_dop20"),
        ("Legacy: downloads",              "downloads"),
    ]

    def setup_downloads_tab(self):
        self.tab_downloads.grid_columnconfigure(0, weight=1)
        self.tab_downloads.grid_rowconfigure(1, weight=1)

        # Header row
        header = ctk.CTkFrame(self.tab_downloads)
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        ctk.CTkLabel(header, text="Downloads Overview",
                     font=("Roboto", 18, "bold")).pack(side="left", padx=8, pady=6)
        ctk.CTkButton(header, text="Refresh", width=90,
                      command=self.refresh_downloads_overview,
                      fg_color="#3498db", hover_color="#2980b9").pack(side="right", padx=4, pady=4)
        ctk.CTkButton(header, text="Open base folder", width=140,
                      command=lambda: self._open_folder("."),
                      fg_color="gray30", hover_color="gray40").pack(side="right", padx=4, pady=4)

        # Scrollable list of folder rows
        self._downloads_scroll = ctk.CTkScrollableFrame(self.tab_downloads)
        self._downloads_scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=4)

        # License / attribution footer
        lic = ctk.CTkFrame(self.tab_downloads, fg_color="gray15")
        lic.grid(row=2, column=0, sticky="ew", padx=10, pady=(4, 10))
        ctk.CTkLabel(lic, text="Attribution & Licensing",
                     font=("Roboto", 13, "bold")).pack(anchor="w", padx=10, pady=(6, 2))
        ctk.CTkLabel(
            lic, justify="left", anchor="w", wraplength=1000,
            text=(
                "OpenStreetMap data  —  © OpenStreetMap contributors, "
                "Open Database License (ODbL) v1.0.\n"
                "    • Attribution: '© OpenStreetMap contributors'\n"
                "    • Share-alike: any adapted database must be offered under ODbL.\n"
                "    • Keep open: if you redistribute, do not apply DRM without an unrestricted copy.\n"
                "    • Full text: https://opendatacommons.org/licenses/odbl/1-0/\n"
                "\n"
                "Bayern geodata  —  © Bayerische Vermessungsverwaltung, Creative Commons BY 4.0.\n"
                "    • Attribution: 'Datenquelle: Bayerische Vermessungsverwaltung – www.geodaten.bayern.de'\n"
                "    • Full text: https://creativecommons.org/licenses/by/4.0/"
            ),
            font=("Consolas", 10), text_color="gray75",
        ).pack(anchor="w", padx=10, pady=(0, 8))

        self.refresh_downloads_overview()

    def refresh_downloads_overview(self):
        """Rebuild the folder rows with current file counts + sizes."""
        # Clear prior rows
        for child in self._downloads_scroll.winfo_children():
            child.destroy()

        total_files = 0
        total_bytes = 0
        for display, path in self.DOWNLOAD_FOLDERS:
            count, size = self._folder_stats(path)
            if count == 0 and not os.path.exists(path) and "Legacy" in display:
                # Hide legacy folders that don't exist at all.
                continue
            total_files += count
            total_bytes += size
            self._add_download_folder_row(display, path, count, size)

        # Totals footer row
        footer = ctk.CTkFrame(self._downloads_scroll, fg_color="gray25")
        footer.pack(fill="x", padx=2, pady=(8, 2))
        ctk.CTkLabel(footer, text="TOTAL",
                     font=("Roboto", 12, "bold"),
                     width=200, anchor="w").pack(side="left", padx=8, pady=6)
        ctk.CTkLabel(footer,
                     text=f"{total_files} files, {self._fmt_bytes(total_bytes)}",
                     font=("Roboto", 12, "bold")).pack(side="left", padx=8, pady=6)

    def _add_download_folder_row(self, display, path, count, size):
        row = ctk.CTkFrame(self._downloads_scroll, fg_color="gray20")
        row.pack(fill="x", padx=2, pady=2)
        row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(row, text=display, width=220, anchor="w",
                     font=("Roboto", 12, "bold")).grid(row=0, column=0, padx=8, pady=(6, 0), sticky="w")
        ctk.CTkLabel(row, text=path, anchor="w",
                     font=("Consolas", 10), text_color="gray55").grid(
            row=1, column=0, padx=8, pady=(0, 6), sticky="w")

        if count == 0:
            summary = "— empty —"
            color = "gray55"
        else:
            summary = f"{count} files  •  {self._fmt_bytes(size)}"
            color = "#8cc8ff"
        ctk.CTkLabel(row, text=summary, font=("Roboto", 12),
                     text_color=color).grid(row=0, column=1, padx=8, pady=6, sticky="e")

        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.grid(row=0, column=2, rowspan=2, padx=6, pady=4, sticky="e")
        ctk.CTkButton(btns, text="Open", width=60,
                      command=lambda p=path: self._open_folder(p),
                      fg_color="gray30", hover_color="gray40").pack(side="left", padx=2)

        # Write worldfiles — only meaningful for raw Bayern TIFF folders.
        # Look up the matching BAYERN_DATASETS key via the folder basename.
        dataset_key = os.path.basename(path)
        dataset_meta = BAYERN_DATASETS.get(dataset_key, {})
        can_worldfile = (count > 0
                         and dataset_meta.get("kind") == "raw"
                         and dataset_meta.get("pixel_size_m")
                         and dataset_meta.get("ext") in (".tif", ".tiff"))
        if can_worldfile:
            ctk.CTkButton(
                btns, text=".tfw", width=50,
                command=lambda p=path, k=dataset_key: self._write_worldfiles(p, k),
                fg_color="#2e86de", hover_color="#3498db",
            ).pack(side="left", padx=2)

        ctk.CTkButton(btns, text="Clear", width=60,
                      command=lambda p=path, d=display: self._clear_folder(p, d),
                      fg_color="#b03a2e", hover_color="#c0392b",
                      state=("normal" if count > 0 else "disabled")).pack(side="left", padx=2)

    @staticmethod
    def _folder_stats(path):
        """Return (file_count, total_bytes). Non-existent folder -> (0, 0)."""
        if not os.path.isdir(path):
            return 0, 0
        count, size = 0, 0
        for root, _, files in os.walk(path):
            for f in files:
                try:
                    size += os.path.getsize(os.path.join(root, f))
                    count += 1
                except OSError:
                    pass
        return count, size

    @staticmethod
    def _fmt_bytes(n):
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024:
                return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
            n /= 1024
        return f"{n:.1f} PB"

    def _open_folder(self, path):
        """Open a folder in the OS file manager (Windows-first, best-effort)."""
        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
            except Exception:
                messagebox.showwarning("Not found", f"Folder does not exist:\n{path}")
                return
        try:
            if sys.platform.startswith("win"):
                os.startfile(os.path.abspath(path))
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", path])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showwarning("Could not open", f"{path}\n\n{e}")

    def _write_worldfiles(self, path, dataset_key):
        """Generate .tfw + .prj for every tile in a raw Bayern folder."""
        meta = BAYERN_DATASETS.get(dataset_key, {})
        pixel = meta.get("pixel_size_m")
        if not pixel:
            messagebox.showwarning("Unknown dataset", f"No pixel size known for {dataset_key}.")
            return
        try:
            made, skipped = generate_worldfiles(path, pixel_size_m=pixel)
        except Exception as e:
            messagebox.showerror("Worldfile error", f"Failed in {path}:\n{e}")
            return
        print(f"[INFO] {dataset_key}: wrote worldfiles for {made} tiles "
              f"({skipped} non-Bayern filenames skipped).")
        messagebox.showinfo("Worldfiles written",
                            f"{made} .tfw + .prj sidecars written in:\n{path}\n\n"
                            f"({skipped} filenames didn't match the Bayern tile scheme.)")

    def _clear_folder(self, path, display):
        """Delete every file inside `path` after user confirmation. Keeps the folder."""
        if not os.path.isdir(path):
            return
        count, size = self._folder_stats(path)
        if count == 0:
            return
        ok = messagebox.askyesno(
            "Clear downloads?",
            f"Delete {count} files ({self._fmt_bytes(size)}) from:\n\n{display}\n{path}\n\n"
            "The folder itself will be kept. This cannot be undone.",
        )
        if not ok:
            return
        deleted = 0
        errors = 0
        for root, _, files in os.walk(path):
            for f in files:
                try:
                    os.remove(os.path.join(root, f))
                    deleted += 1
                except OSError:
                    errors += 1
        print(f"[INFO] Cleared {deleted} files from {path} ({errors} errors).")
        self.refresh_downloads_overview()
        if errors:
            messagebox.showwarning("Partial clear",
                                   f"Deleted {deleted} files, {errors} could not be removed "
                                   "(may be locked or in use).")

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

    def start_bayern_download(self):
        """Dispatch download for every selected dataset in the Bayern picker."""
        poly = self.text_polygon.get("1.0", "end").strip()
        if not poly:
            messagebox.showwarning("Warning", "Please extract a polygon first.")
            return

        selected = [k for k, v in self.bayern_dataset_vars.items() if v.get()]
        if not selected:
            messagebox.showwarning("Warning", "Select at least one Bayern dataset.")
            return

        high_res = self.chk_high_res_relief.get() == 1
        fmt = self.seg_format.get().lower()

        for key in selected:
            meta = BAYERN_DATASETS[key]
            out_dir = os.path.join("downloads_bayern", key)
            os.makedirs(out_dir, exist_ok=True)
            if meta["kind"] == "raw":
                self.add_download_row(meta["label"], "Generating tile list...", 0, "Calculating", "...")
                threading.Thread(
                    target=self._run_bayern_raw,
                    args=(poly, key, out_dir),
                    daemon=True,
                ).start()
            else:  # wms
                # DOP40 WMS uses the picker's format; relief WMS is always tiff.
                wms_fmt = fmt if key == "dop40_wms" else "tiff"
                self.add_download_row(meta["label"], "Generating WMS tiles...", 0, "Calculating", "...")
                threading.Thread(
                    target=self._run_bayern_wms,
                    args=(poly, key, wms_fmt, high_res, out_dir),
                    daemon=True,
                ).start()

    def _run_bayern_raw(self, poly, key, out_dir):
        """Download a raw Bayern dataset (e.g. dgm1, dop20) into its own folder."""
        # MapDownloader.download_dir is shared across threads, so we wrap the
        # call in a per-download change. Downloads are added sequentially per
        # dataset so this is safe.
        self.downloader.download_dir = out_dir
        files = self.downloader.generate_1km_grid_files(poly, dataset=key)
        if not files:
            self.after(0, lambda: self.add_download_row(
                key.upper(), "No intersecting tiles found.", 0, "Error", ""))
            return
        print(f"[INFO] {key}: generated {len(files)} tiles -> {out_dir}")
        for fname, _ in files:
            self.after(0, lambda f=fname: self.add_download_row(f, "Pending...", 0, "-", "-"))
        self.run_downloads_batch(files)

        # After downloads finish, write .tfw + .prj sidecars so Blender GIS
        # (and any other georef-aware tool) can batch-import without the
        # "Unable to read georef infos from worldfile or geotiff tags" error.
        meta = BAYERN_DATASETS.get(key, {})
        pixel = meta.get("pixel_size_m")
        if pixel and meta.get("ext") in (".tif", ".tiff"):
            try:
                made, skipped = generate_worldfiles(out_dir, pixel_size_m=pixel)
                print(f"[INFO] {key}: wrote worldfiles for {made} tiles "
                      f"({skipped} non-Bayern filenames skipped).")
            except Exception as e:
                print(f"[WARN] {key}: worldfile generation failed: {e}")

    def _run_bayern_wms(self, poly, key, fmt, high_res, out_dir):
        """Download a WMS-rendered Bayern dataset (relief, dop40_wms)."""
        self.downloader.download_dir = out_dir
        meta = BAYERN_DATASETS[key]
        # generate_relief_tiles historically uses layer="by_relief_schraeglicht"
        # for relief and "dop40" to trigger DOP40 inside the downloader.
        layer = meta["layer"] if key == "relief_wms" else "dop40"
        tiles = self.downloader.generate_relief_tiles(
            poly, layer=layer, format_ext=fmt, high_res=high_res)
        if not tiles:
            self.after(0, lambda: self.add_download_row(
                key.upper(), "No intersecting tiles found.", 0, "Error", ""))
            return
        print(f"[INFO] {key}: generated {len(tiles)} WMS tiles -> {out_dir}")
        for fname, _ in tiles:
            self.after(0, lambda f=fname: self.add_download_row(f, "Pending...", 0, "-", "-"))
        self.run_downloads_batch(tiles)

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
        self.downloader._session = None       # Force new Bayern session
        self.osm_downloader._session = None   # Force new OSM session


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
        out_row.pack(fill="x", padx=8, pady=(0, 8))
        self.osm_dir_var = tk.StringVar(value="downloads_osm")
        ctk.CTkEntry(out_row, textvariable=self.osm_dir_var).pack(
            side="left", fill="x", expand=True)
        ctk.CTkButton(out_row, text="...", width=30, height=28,
                      command=self._osm_browse_dir,
                      fg_color="gray30", hover_color="gray40").pack(side="left", padx=4)

        # SSL settings moved to unified Proxy Settings dialog (applies to Bayern + OSM).
        ctk.CTkLabel(frame_left,
                     text="SSL / proxy settings → top-right 'Proxy Settings' button",
                     font=("Roboto", 10), text_color="gray50").pack(padx=10, pady=(0, 4))

        # Download button
        ctk.CTkButton(frame_left, text="Download Selected Layers",
                      command=self.start_osm_download,
                      fg_color="#1e8bc3", hover_color="#3498db",
                      height=40, font=("Roboto", 14, "bold")).pack(
            fill="x", padx=10, pady=8)

        ctk.CTkButton(frame_left, text="Test Overpass Connection",
                      command=self._osm_test_connection,
                      fg_color="gray30", hover_color="gray40",
                      height=30).pack(fill="x", padx=10, pady=(0, 4))

        self.lbl_osm_conn = ctk.CTkLabel(frame_left, text="",
                                          font=("Roboto", 11), text_color="gray60")
        self.lbl_osm_conn.pack(padx=10, pady=(0, 4))

        ctk.CTkLabel(frame_left,
                     text="Output: GeoJSON per layer — compatible with QGIS, OSG, Terrain3D",
                     font=("Roboto", 11), text_color="gray50").pack(padx=10, pady=(0, 4))

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

    def _osm_test_connection(self):
        """Quick connectivity test to overpass-api.de — runs in thread."""
        self.lbl_osm_conn.configure(text="Testing...", text_color="yellow")

        def _run():
            import requests as _req
            url = "https://overpass-api.de/api/interpreter"
            # Tiny status query — should return in under 2 seconds
            query = "[out:json][timeout:5];node(0,0,0,0);out;"
            try:
                session = self.osm_downloader._get_session()
                # session already has verify/CA bundle from proxy_manager
                r = session.post(url, data={"data": query}, timeout=10)
                if r.status_code == 200:
                    msg, color = "Overpass reachable (HTTP 200)", "#27ae60"
                else:
                    msg, color = f"HTTP {r.status_code} from Overpass", "#e67e22"
            except _req.exceptions.SSLError:
                msg = "SSL error — try disabling SSL verify (proxy inspection)"
                color = "#e74c3c"
            except _req.exceptions.ProxyError:
                msg = "Proxy blocked — ask IT to whitelist overpass-api.de"
                color = "#e74c3c"
            except _req.exceptions.ConnectionError:
                msg = "Cannot reach overpass-api.de — check proxy/network"
                color = "#e74c3c"
            except Exception as e:
                msg, color = f"Error: {e}", "#e74c3c"

            self.after(0, lambda: self.lbl_osm_conn.configure(text=msg, text_color=color))
            print(f"[OSM] Connection test: {msg}")

        threading.Thread(target=_run, daemon=True).start()

    def _osm_browse_dir(self):
        path = filedialog.askdirectory(title="Select OSM output directory")
        if path:
            self.osm_dir_var.set(path)

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
        self.osm_downloader.stop_event = False

        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

        # Prime progress rows
        for name in selected:
            self.add_osm_row(name, "Queued...", 0, "-", "-")

        print(f"[OSM] Starting download of {len(selected)} layers, buffer={buffer}m, dir={out_dir}")
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
        self.title("Proxy & SSL Settings")
        self.geometry("560x620")
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

        # --- SSL / TLS Section (applies to Bayern + OSM, regardless of proxy mode) ---
        ssl_frame = ctk.CTkFrame(container, fg_color="gray20")
        ssl_frame.pack(fill="x", pady=10, padx=5)

        ctk.CTkLabel(ssl_frame, text="SSL / TLS", anchor="w",
                     font=("Roboto", 13, "bold")).pack(fill="x", padx=10, pady=(8, 0))
        ctk.CTkLabel(ssl_frame,
                     text="Applied to both Bayern + OSM downloads. Required when a corporate proxy inspects HTTPS.",
                     anchor="w", font=("Roboto", 10), text_color="gray60",
                     wraplength=500, justify="left").pack(fill="x", padx=10, pady=(0, 5))

        self.var_ssl_verify = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(ssl_frame, text="Verify SSL certificates",
                        variable=self.var_ssl_verify).pack(anchor="w", padx=10, pady=3)

        ca_row = ctk.CTkFrame(ssl_frame, fg_color="transparent")
        ca_row.pack(fill="x", padx=10, pady=(3, 8))
        ctk.CTkLabel(ca_row, text="CA bundle (.pem):", width=120, anchor="w").pack(side="left")
        self.entry_ca_bundle = ctk.CTkEntry(ca_row, placeholder_text="(empty = system default)")
        self.entry_ca_bundle.pack(side="left", fill="x", expand=True, padx=5)
        ctk.CTkButton(ca_row, text="Browse...", width=80,
                      command=self._browse_ca_bundle,
                      fg_color="gray30", hover_color="gray40").pack(side="left")

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
        
        self.entry_domain.delete(0, "end")
        self.entry_domain.insert(0, config.domain)

        # SSL fields
        self.var_ssl_verify.set(config.ssl_verify)
        self.entry_ca_bundle.delete(0, "end")
        self.entry_ca_bundle.insert(0, config.ca_bundle_path)

        self.on_mode_change()
        self.on_auth_change(self.seg_auth.get())

    def _browse_ca_bundle(self):
        path = filedialog.askopenfilename(
            title="Select CA bundle (.pem)",
            filetypes=[("PEM certificates", "*.pem *.crt *.cer"), ("All files", "*.*")],
        )
        if path:
            self.entry_ca_bundle.delete(0, "end")
            self.entry_ca_bundle.insert(0, path)
    
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
        
        if found:
            self.entry_proxy_url.delete(0, "end")
            self.entry_proxy_url.insert(0, self.proxy_manager.config.proxy_url)
            self.lbl_status.configure(text=f"✓ Detected: {self.proxy_manager.config.proxy_url}", text_color="#27ae60")
            self.var_mode.set("auto")
        else:
            self.lbl_status.configure(text="No proxy detected. Using direct connection.", text_color="gray60")
            self.var_mode.set("none")
    
    def do_test_connection(self):
        """Test connections to all known data sources (Bayern + OSM)."""
        self.lbl_status.configure(text="Testing Bayern + OSM...", text_color="yellow")
        self.update()

        # Apply current form settings temporarily (including SSL).
        self.apply_settings(save=False)

        results = self.proxy_manager.test_connections()

        lines = []
        overall_ok = True
        for label, (ok, msg) in results.items():
            mark = "✓" if ok else "✗"
            lines.append(f"{mark} {label}: {msg}")
            overall_ok = overall_ok and ok

        color = "#27ae60" if overall_ok else "#e74c3c"
        self.lbl_status.configure(text="\n".join(lines), text_color=color)
    
    def apply_settings(self, save=True):
        """Apply form settings to proxy manager."""
        mode = self.var_mode.get()
        
        if mode == "none":
            self.proxy_manager.disable_proxy()
        elif mode == "auto":
            self.proxy_manager.auto_detect()
        else:  # manual
            auth_map = {"None": "none", "Basic": "basic", "NTLM": "ntlm"}
            self.proxy_manager.set_manual_proxy(
                proxy_url=self.entry_proxy_url.get(),
                auth_type=auth_map.get(self.seg_auth.get(), "none"),
                username=self.entry_username.get(),
                password=self.entry_password.get(),
                domain=self.entry_domain.get()
            )

        # SSL settings apply regardless of proxy mode.
        self.proxy_manager.set_ssl(
            ssl_verify=bool(self.var_ssl_verify.get()),
            ca_bundle_path=self.entry_ca_bundle.get().strip(),
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
