
import requests

urls = [
    ("Old Guess", "https://geoservices.bayern.de/wms/v1/ogc_dop80_oa.cgi?service=WMS&request=GetCapabilities"),
    ("OD Pattern 80", "https://geoservices.bayern.de/od/wms/dop/v1/dop80?service=WMS&request=GetCapabilities"),
    ("OD Pattern 40", "https://geoservices.bayern.de/od/wms/dop/v1/dop40?service=WMS&request=GetCapabilities"),
    ("OD Pattern 20", "https://geoservices.bayern.de/od/wms/dop/v1/dop20?service=WMS&request=GetCapabilities"),
]

for name, url in urls:
    try:
        print(f"Checking {name}...")
        r = requests.get(url, timeout=5)
        print(f"Status: {r.status_code}")
        if r.status_code == 200 and "xml" in r.headers.get("content-type", ""):
            print(f"SUCCESS: {name} is valid WMS.")
            print(f"Snippet: {r.text[:200]}")
        else:
            print("Failed or not XML.")
    except Exception as e:
        print(f"Error: {e}")
    print("-" * 20)
