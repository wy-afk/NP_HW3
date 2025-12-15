import os
import zipfile
from pathlib import Path

def zip_folder(folder_path: str, output_zip: str):
    folder = Path(folder_path)
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(folder):
            for file in files:
                full_path = Path(root) / file
                arc = full_path.relative_to(folder)
                z.write(full_path, arc)
    return output_zip
