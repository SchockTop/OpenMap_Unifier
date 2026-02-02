
import requests
import xml.etree.ElementTree as ET

url = "https://geoservices.bayern.de/od/wms/dop/v1/dop40?service=WMS&request=GetCapabilities"
print(f"Fetching {url}...")
try:
    r = requests.get(url, timeout=10)
    root = ET.fromstring(r.content)
    # Find all Layer names
    for layer in root.iter("Layer"):
        title = layer.find("Title")
        name = layer.find("Name")
        if name is not None:
             print(f"Layer: {name.text} - {title.text if title is not None else 'No Title'}")
except Exception as e:
    print(e)
