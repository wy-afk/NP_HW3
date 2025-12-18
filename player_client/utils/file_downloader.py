import os
import zipfile

def recv_and_save(sock, save_path, filesize):
    import tempfile
    remaining = filesize
    # Write to a temporary file and rename atomically on success.
    dirn = os.path.dirname(save_path) or "."
    os.makedirs(dirn, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="dl_", dir=dirn)
    os.close(fd)
    received = 0
    last_report = 0
    try:
        with open(tmp, "wb") as f:
            while remaining > 0:
                chunk = sock.recv(min(65536, remaining))
                if not chunk:
                    break
                f.write(chunk)
                received += len(chunk)
                remaining -= len(chunk)
                # progress: report every ~5% or every 1MB
                if filesize > 0:
                    pct = int(received * 100 / filesize)
                    if pct - last_report >= 5 or received - last_report >= 1024*1024:
                        print(f"[Download] {received}/{filesize} bytes ({pct}%)")
                        last_report = pct

        # Verify size
        if filesize and received != filesize:
            # incomplete download
            try:
                os.remove(tmp)
            except Exception:
                pass
            raise RuntimeError(f"Incomplete download: expected {filesize}, got {received}")

        # Atomic move into place
        try:
            os.replace(tmp, save_path)
        except Exception:
            # best-effort copy then remove
            with open(tmp, "rb") as src, open(save_path, "wb") as dst:
                dst.write(src.read())
            try:
                os.remove(tmp)
            except Exception:
                pass
        return save_path
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise


def unzip(zip_path, extract_to):
    os.makedirs(extract_to, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_to)
