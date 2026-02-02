import os
import xml.etree.ElementTree as ET
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import sys

def download_file(url, file_path, file_name):
    try:
        if os.path.exists(file_path):
            print(f"Skipping {file_name}, already exists.")
            return True

        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        block_size = 8192  # 8KB
        
        with open(file_path, 'wb') as f, tqdm(
            desc=file_name,
            total=total_size,
            unit='iB',
            unit_scale=True,
            unit_divisor=1024,
        ) as bar:
            for data in response.iter_content(block_size):
                size = f.write(data)
                bar.update(size)
        return True
    except Exception as e:
        print(f"Error downloading {file_name} from {url}: {e}")
        if os.path.exists(file_path):
            os.remove(file_path) # Clean up partial file
        return False

def process_metalink(metalink_file, output_dir="downloads", max_workers=5):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    try:
        tree = ET.parse(metalink_file)
        root = tree.getroot()
        
        # Namespace handling
        ns = {'ml': 'urn:ietf:params:xml:ns:metalink'}
        
        files_to_download = []
        
        for file_elem in root.findall('ml:file', ns):
            file_name = file_elem.get('name')
            
            # Get all urls for this file (mirrors)
            urls = [u.text for u in file_elem.findall('ml:url', ns)]
            
            if file_name and urls:
                files_to_download.append((file_name, urls))
                
        print(f"Found {len(files_to_download)} files to download.")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {}
            for file_name, urls in files_to_download:
                target_path = os.path.join(output_dir, file_name)
                # Try the first URL for now. 
                # Ideally we'd have retry logic for mirrors, but let's start simple.
                url = urls[0] 
                future = executor.submit(download_file, url, target_path, file_name)
                future_to_file[future] = file_name
                
            for future in as_completed(future_to_file):
                file_name = future_to_file[future]
                try:
                    success = future.result()
                    if not success:
                        print(f"Failed to download {file_name}")
                except Exception as exc:
                    print(f"{file_name} generated an exception: {exc}")
                    
        print("Download processing complete.")

    except Exception as e:
        print(f"Error parse metalink: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        meta_file = sys.argv[1]
    else:
        meta_file = "dop20rgb.meta4"
        
    process_metalink(meta_file)
