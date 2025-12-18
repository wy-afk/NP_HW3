import os
import json
import shutil
import zipfile
import tempfile
from pathlib import Path


def safe_extract_zip(zip_path: str, dest_dir: str) -> None:
    """Extract zip to dest_dir safely (prevents path traversal)."""
    dest = Path(dest_dir).resolve()
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for member in zf.namelist():
            # Skip directory entries handled by extract
            member_path = dest.joinpath(member)
            try:
                member_path.resolve()
            except Exception:
                raise RuntimeError(f"Invalid zip member path: {member}")
            if not str(member_path.resolve()).startswith(str(dest) + os.sep) and str(member_path.resolve()) != str(dest):
                raise RuntimeError(f"Zip contains path traversal entry: {member}")
        zf.extractall(dest)


def validate_game_manifest(extracted_dir: str) -> dict:
    """Validate the presence and basic fields of a `game.json` manifest inside the extracted dir.

    Returns the parsed manifest dict on success or raises RuntimeError.
    """
    mpath = Path(extracted_dir) / "game.json"
    if not mpath.exists():
        raise RuntimeError("Missing game.json manifest in package")

    try:
        with mpath.open('r', encoding='utf-8') as f:
            manifest = json.load(f)
    except Exception as e:
        raise RuntimeError(f"Invalid game.json: {e}")

    # Basic required fields
    name = manifest.get('name')
    version = manifest.get('version')
    server = manifest.get('server')
    if not name or not version or not server:
        raise RuntimeError('Manifest missing required fields: name/version/server')

    start_cmd = server.get('start_cmd')
    if not start_cmd:
        raise RuntimeError('Manifest.server.start_cmd missing')

    # start_cmd should be a list (preferred) or a string
    if not isinstance(start_cmd, (list, str)):
        raise RuntimeError('server.start_cmd must be a list or string')

    return manifest


def atomic_publish(staging_dir: str, runtime_dir: str) -> None:
    """Move staging_dir to runtime_dir atomically (replace existing)."""
    src = Path(staging_dir).resolve()
    dst = Path(runtime_dir).resolve()
    tmp_parent = dst.parent
    tmp_parent.mkdir(parents=True, exist_ok=True)

    # If destination exists, remove it (we replace on publish)
    if dst.exists():
        shutil.rmtree(dst)

    # Move staging to final location
    shutil.move(str(src), str(dst))
