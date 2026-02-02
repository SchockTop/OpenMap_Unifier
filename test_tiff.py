
import requests

base_url = "https://geoservices.bayern.de/od/wms/dop/v1/dop40"

params_template = {
    "service": "WMS",
    "version": "1.1.1",
    "request": "GetMap",
    "layers": "by_dop40c",
    "srs": "EPSG:25832",
    "styles": "",
    "format": "image/tiff", # Testing TIFF
    "width": "256",
    "height": "256",
    "bbox": "668000,5424000,669000,5425000",
    "transparent": "true"
}

print(f"Testing {base_url} for TIFF support...")

try:
    r = requests.get(base_url, params=params_template, timeout=5)
    print(f"Status: {r.status_code}")
    print(f"Content-Type: {r.headers.get('content-type')}")
    if r.status_code != 200:
        print(f"Response: {r.text[:200]}")
    else:
        print("Success! Tiff is supported.")
except Exception as e:
    print(f"Error: {e}")
