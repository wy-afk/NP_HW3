import os
import zipfile
from pathlib import Path

def recv_file(sock, save_path: str, filesize: int):
    """Receive raw binary file of known size."""
    remaining = filesize
    with open(save_path, "wb") as f:
        while remaining > 0:
            chunk = sock.recv(min(4096, remaining))
            if not chunk:
                break
            f.write(chunk)
            remaining -= len(chunk)
    return save_path


def unzip_file(zip_path: str, extract_dir: str):
    os.makedirs(extract_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_dir)
    return extract_dir
