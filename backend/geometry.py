
import xml.etree.ElementTree as ET
from pyproj import Transformer

class PolygonExtractor:
    @staticmethod
    def extract_from_kml(content_bytes=None, file_path=None):
        """
        Extracts the first polygon from KML content and returns it as an EWKT string (WGS84).
        Accepts either raw bytes or a file path.
        """
        try:
            if content_bytes:
                root = ET.fromstring(content_bytes)
            elif file_path:
                tree = ET.parse(file_path)
                root = tree.getroot()
            else:
                raise ValueError("No content or file provided")

            # Simple search for 'coordinates'
            coords_text = None
            for elem in root.iter():
                if elem.tag.endswith('coordinates'):
                    coords_text = elem.text.strip()
                    break
            
            if not coords_text:
                return None, "No coordinates found in KML/XML."

            # Parse coordinates (lon,lat,alt ...)
            raw_coords = coords_text.split()
            ewkt_points = []
            
            for raw_coord in raw_coords:
                parts = raw_coord.split(',')
                if len(parts) >= 2:
                    lon = float(parts[0])
                    lat = float(parts[1])
                    ewkt_points.append(f"{lon} {lat}")
            
            if not ewkt_points:
                return None, "No valid coordinates parsed."

            coord_string = ", ".join(ewkt_points)
            ewkt = f"SRID=4326;POLYGON(({coord_string}))"
            return ewkt, None

        except Exception as e:
            return None, str(e)
