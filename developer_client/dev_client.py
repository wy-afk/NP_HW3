import socket
import json
import os
from pathlib import Path

from utils.protocol import send, recv
from utils.file_packer import zip_folder


HOST = "127.0.0.1"
PORT = 5555


def connect_to_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((HOST, PORT))
    print(f"[CONNECTED] Lobby server at {HOST}:{PORT}")
    return s


def request(sock, action, data=None):
    msg = {"action": action, "data": data or {}}
    send(sock, msg)
    return recv(sock)


_DEV_CLIENT_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCAL_GAMES_DIR = os.path.join(_DEV_CLIENT_DIR, "games")


def _iter_local_packages():
    """Yield dicts: {folder, name, version} for developer_client/games/<Name>/<Version>."""
    base = Path(_LOCAL_GAMES_DIR)
    if not base.is_dir():
        return

    for game_dir in sorted([p for p in base.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
        for version_dir in sorted([p for p in game_dir.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
            manifest_path = version_dir / "game.json"
            name = game_dir.name
            version = version_dir.name
            if manifest_path.is_file():
                try:
                    m = json.loads(manifest_path.read_text(encoding="utf-8"))
                    name = str(m.get("name") or name)
                    version = str(m.get("version") or version)
                except Exception:
                    pass

            yield {
                "folder": str(version_dir),
                "name": name,
                "version": version,
            }


def _choose_local_package():
    pkgs = list(_iter_local_packages())
    if not pkgs:
        print(f"[ERROR] No local games found under: {_LOCAL_GAMES_DIR}")
        return None

    print(f"\nLocal games in: {_LOCAL_GAMES_DIR}")
    for i, p in enumerate(pkgs, start=1):
        print(f"{i}. {p['name']} v{p['version']}")
    print("0. Cancel")
    while True:
        raw = input(f"Select a game to upload (0-{len(pkgs)}): ").strip()
        if raw == "0" or raw == "":
            return None
        try:
            idx = int(raw)
            if 1 <= idx <= len(pkgs):
                return pkgs[idx - 1]
        except Exception:
            pass
        print("Invalid selection")


# ==================================================================
# Developer actions
# ==================================================================

def do_register(sock):
    username = input("Developer Username: ").strip()
    password = input("Password: ").strip()

    resp = request(sock, "register", {
        "username": username,
        "password": password,
        "role": "developer"
    })

    print(resp)


def do_login(sock):
    username = input("Developer Username: ").strip()
    password = input("Password: ").strip()

    resp = request(sock, "login", {
        "username": username,
        "password": password,
        "role": "developer"
    })

    print(resp)
    if resp["status"] == "ok":
        print("[LOGIN SUCCESS]")


def do_list_games(sock):
    pkgs = list(_iter_local_packages())
    if not pkgs:
        print(f"No local games found under: {_LOCAL_GAMES_DIR}")
        return

    print(f"\nLocal games under: {_LOCAL_GAMES_DIR}")
    for i, p in enumerate(pkgs, start=1):
        print(f"{i}. {p['name']} v{p['version']}  ({p['folder']})")


# ==================================================================
# Corrected UPLOAD logic (full)
# ==================================================================

def do_upload_game(sock):
    selected = _choose_local_package()
    if not selected:
        print("Upload cancelled")
        return

    folder = selected["folder"]
    name = selected["name"]
    version = selected["version"]

    if not os.path.isdir(folder):
        print("[ERROR] Folder does not exist:", folder)
        return

    # ========================
    # 1) ZIP THE FOLDER
    # ========================
    zip_path = f"/tmp/{name}_{version}.zip"
    print(f"[ZIPPING] {folder} → {zip_path}")
    zip_folder(folder, zip_path)

    # ========================
    # 2) SEND METADATA FIRST
    # ========================
    resp = request(sock, "upload_game_meta", {
        "name": name,
        "version": version
    })

    if resp is None:
        print("❌ Server did not respond.")
        return
    if resp["status"] != "ok":
        print("❌ Upload meta failed:", resp)
        return

    print("[SERVER READY] Uploading file...")

    # ========================
    # 3) SEND upload_game_file COMMAND
    # ========================
    send(sock, {"action": "upload_game_file", "data": {}})

    # ========================
    # 4) SEND FILE SIZE (8 bytes)
    # ========================
    filesize = os.path.getsize(zip_path)
    sock.sendall(filesize.to_bytes(8, 'big'))

    # ========================
    # 5) SEND FILE BYTES
    # ========================
    with open(zip_path, "rb") as f:
        sock.sendall(f.read())

    # ========================
    # 6) RECEIVE FINAL CONFIRMATION
    # ========================
    final = recv(sock)
    print("[UPLOAD COMPLETE]")
    print(json.dumps(final, indent=2))


def do_update_game(sock):
    selected = _choose_local_package()
    if not selected:
        print("Update cancelled")
        return

    folder = selected["folder"]
    name = selected["name"]
    version = selected["version"]

    if not os.path.isdir(folder):
        print("[ERROR] Folder does not exist:", folder)
        return

    zip_path = f"/tmp/{name}_{version}.zip"
    print(f"[ZIPPING] {folder} → {zip_path}")
    zip_folder(folder, zip_path)

    resp = request(sock, "update_game_meta", {"name": name, "version": version})
    if resp is None or resp.get("status") != "ok":
        print("❌ Update meta failed:", resp)
        return

    print("[SERVER READY] Uploading update file...")
    send(sock, {"action": "update_game_file", "data": {}})
    filesize = os.path.getsize(zip_path)
    sock.sendall(filesize.to_bytes(8, 'big'))
    with open(zip_path, "rb") as f:
        sock.sendall(f.read())

    final = recv(sock)
    print("[UPDATE COMPLETE]")
    print(json.dumps(final, indent=2))


def do_remove_game(sock):
    # Show server-side games (with IDs) so the developer can remove by game_id.
    resp = request(sock, "list_games")
    if not resp or resp.get("status") != "ok":
        print("[ERROR] Unable to fetch server games:")
        print(resp)
        return

    games = resp.get("games")
    if not isinstance(games, dict) or not games:
        print("No games on server.")
        return

    print("\nServer games:")
    # keys may be ints or strings
    def _sort_key(item):
        k, _ = item
        try:
            return int(k)
        except Exception:
            return str(k)

    for gid, meta in sorted(games.items(), key=_sort_key):
        if not isinstance(meta, dict):
            continue
        owner = meta.get("owner")
        owner_txt = owner if owner else "-"
        print(f"ID={gid}  {meta.get('name')} v{meta.get('version')}  owner={owner_txt}")

    raw = input("Game ID to remove (blank to cancel): ").strip()
    if raw == "":
        print("Remove cancelled")
        return

    meta = games.get(raw)
    if meta is None:
        try:
            meta = games.get(int(raw))
        except Exception:
            meta = None

    if not isinstance(meta, dict):
        print("[ERROR] Invalid game id")
        return

    name = meta.get("name")
    version = str(meta.get("version"))
    if not name or not version:
        print("[ERROR] Server metadata missing name/version for that id")
        return

    confirm = input(f"Confirm remove {name} v{version}? (y/N): ").strip().lower()
    if confirm != "y":
        print("Remove cancelled")
        return

    out = request(sock, "remove_game", {"name": name, "version": version})
    print(json.dumps(out, indent=2))


def do_logout(sock):
    resp = request(sock, "logout")
    print(resp)


# ==================================================================
# MAIN MENU
# ==================================================================

def main():
    sock = connect_to_server()

    MENU = """
=============================
 Developer CLI Menu
=============================
1. Register (Developer)
2. Login (Developer)
3. List Games
4. Upload Game Folder
5. Update Game (overwrite)
6. Remove Game
7. Logout
0. Exit
"""

    while True:
        print(MENU)
        choice = input("> ").strip()

        if choice == "1":
            do_register(sock)
        elif choice == "2":
            do_login(sock)
        elif choice == "3":
            do_list_games(sock)
        elif choice == "4":
            do_upload_game(sock)
        elif choice == "5":
            do_update_game(sock)
        elif choice == "6":
            do_remove_game(sock)
        elif choice == "7":
            do_logout(sock)
        elif choice == "0":
            print("Goodbye!")
            sock.close()
            break
        else:
            print("Invalid option.")


if __name__ == "__main__":
    main()
