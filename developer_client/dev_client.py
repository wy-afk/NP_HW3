import socket
import json
import os

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
    resp = request(sock, "list_games")
    print(json.dumps(resp, indent=2))


# ==================================================================
# Corrected UPLOAD logic (full)
# ==================================================================

def do_upload_game(sock):
    folder = input("Local game folder to upload: ").strip()
    name = input("Game name: ").strip()
    version = input("Version: ").strip()

    if not os.path.isdir(folder):
        print("[ERROR] Folder does not exist:", folder)
        return

    # Safety check: prevent uploading server/game_storage by mistake
    if "server/game_storage" in folder:
        print("\n ❌ ERROR: You are trying to upload inside server storage!")
        print("Upload your REAL game source folder (e.g. HW3/Games/Battleship)")
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
5. Logout
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
            do_logout(sock)
        elif choice == "0":
            print("Goodbye!")
            sock.close()
            break
        else:
            print("Invalid option.")


if __name__ == "__main__":
    main()
