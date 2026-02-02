
import xml.etree.ElementTree as ET
import sys
from pyproj import Transformer

def extract_and_convert(xml_file):
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        
        # Define namespaces
        namespaces = {
            'kml': 'http://www.opengis.net/kml/2.2',
            'gx': 'http://www.google.com/kml/ext/2.2'
        }
        
        # Find the Polygon coordinates
        # The structure is somewhat nested, so we'll search for the Polygon tag directly if possible
        # or traverse down.
        # Based on file content: kml > Document > Placemark > Polygon > outerBoundaryIs > LinearRing > coordinates
        
        # Just searching for 'coordinates' element might be easiest if there's only one relevant polygon
        # But to be safe, let's find the Placemark with the Polygon
        
        # Look for any coordinates tag inside a Polygon/outerBoundaryIs/LinearRing
        # We handle default namespace by using the URI
        ns_url = 'http://www.opengis.net/kml/2.2'
        # ElementTree simplistic namespace handling for find/findall:
        # We can just iterate or use specific paths.
        
        coords_text = None
        for elem in root.iter():
            if elem.tag.endswith('coordinates'):
                # Check if parent path looks like a polygon boundary
                # For simplicity in this specific file, taking the first coordinates block 
                # inside a LinearRing is likely correct.
                coords_text = elem.text.strip()
                break
        
        if not coords_text:
            print("Error: No coordinates found in XML.")
            return

        # Parse coordinates
        # Format in KML: lon,lat,alt lon,lat,alt ...
        # Separated by whitespace (space or newline)
        raw_coords = coords_text.split()
        
        points = []
        for raw_coord in raw_coords:
            parts = raw_coord.split(',')
            if len(parts) >= 2:
                lon = float(parts[0])
                lat = float(parts[1])
                points.append((lon, lat))
            
        if not points:
            print("Error: No valid coordinates parsed.")
            return

        # The user prefers SRID=4326 (WGS84) which matches the KML input system.
        # This avoids reprojection and keeps coordinates "familiar".
        
        ewkt_points = []
        for lon, lat in points:
            # EWKT format for POLYGON: Longitude Latitude
            ewkt_points.append(f"{lon} {lat}")
            
        # Join for EWKT
        # The format required: SRID=4326;POLYGON ((x1 y1, x2 y2, ...))
        coord_string = ", ".join(ewkt_points)
        
        ewkt = f"SRID=4326;POLYGON(({coord_string}))"
        
        print(ewkt)

    except Exception as e:
        print(f"Error processing file: {e}")

if __name__ == "__main__":
    extract_and_convert("googleearth.xml")
