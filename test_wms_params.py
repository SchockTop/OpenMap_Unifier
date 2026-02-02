
import requests

base_url = "https://geoservices.bayern.de/od/wms/dop/v1/dop40"

params_template = {
    "service": "WMS",
    "version": "1.1.1",
    "request": "GetMap",
    "layers": "by_dop40c",
    "srs": "EPSG:25832",
    "styles": "",
    "format": "image/jpeg", # Changed to jpeg
    "width": "256",
    "height": "256",
    "bbox": "668000,5424000,669000,5425000",
    "transparent": "true"
}

tests = [
    ("Default (jpeg)", {}),
    ("Format: image/jpg", {"format": "image/jpg"}),
    ("Format: image/png", {"format": "image/png"}),
    ("Version 1.3.0 (CRS)", {"version": "1.3.0", "crs": "EPSG:25832", "srs": None}),
    ("No Styles", {"styles": None}),
]

print(f"Testing {base_url}...")

for name, overrides in tests:
    p = params_template.copy()
    p.update(overrides)
    # Remove None keys
    p = {k: v for k, v in p.items() if v is not None}
    
    try:
        r = requests.get(base_url, params=p, timeout=5)
        print(f"[{name}] Status: {r.status_code}")
        if r.status_code != 200:
            print(f"  Response: {r.text[:200]}")
    except Exception as e:
        print(f"[{name}] Error: {e}")
