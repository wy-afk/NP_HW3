import os
import zipfile

def recv_and_save(sock, save_path, filesize):
    remaining = filesize
    with open(save_path, "wb") as f:
        while remaining > 0:
            chunk = sock.recv(min(4096, remaining))
            if not chunk:
                break
            f.write(chunk)
            remaining -= len(chunk)
    return save_path


def unzip(zip_path, extract_to):
    os.makedirs(extract_to, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_to)
