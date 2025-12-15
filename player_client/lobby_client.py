import socket
import json
from utils.protocol import send, recv
from utils.file_downloader import recv_and_save, unzip

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


# ============================================================
# Player Commands
# ============================================================

def do_register(sock):
    username = input("Username: ")
    password = input("Password: ")
    role = input("Role (player/developer): ").strip().lower()

    resp = request(sock, "register", {
        "username": username,
        "password": password,
        "role": role
    })
    print(resp)


def do_login(sock):
    username = input("Username: ")
    password = input("Password: ")
    role = input("Role (player/developer): ").strip().lower()

    resp = request(sock, "login", {
        "username": username,
        "password": password,
        "role": role
    })
    print(resp)


def do_list_games(sock):
    resp = request(sock, "list_games")
    print(json.dumps(resp, indent=2))


def do_list_rooms(sock):
    resp = request(sock, "list_rooms")
    print(json.dumps(resp, indent=2))


def do_create_room(sock):
    game_id = int(input("Game ID: "))
    resp = request(sock, "create_room", {"game_id": game_id})
    print(resp)


def do_join_room(sock):
    room_id = int(input("Room ID: "))
    resp = request(sock, "join_room", {"room_id": room_id})
    print(resp)


def do_start_game(sock):
    room_id = int(input("Room ID: "))
    resp = request(sock, "start_game", {"room_id": room_id})
    print(resp)


# ----------------------------
# DOWNLOAD GAME
# ----------------------------
def do_download_game(sock):
    game_id = int(input("Game ID to download: "))

    # Step 1: get metadata
    resp = request(sock, "download_game_meta", {"game_id": game_id})
    print(resp)

    if resp["status"] != "ok":
        return

    info = resp["data"]
    filename = info["filename"]
    filesize = info["filesize"]

    # Step 2: receive zip file
    save_path = f"/tmp/{filename}"
    extract_path = f"downloads/{info['name']}/{info['version']}"

    print(f"[DOWNLOADING] {filename} ({filesize} bytes)")

    header = sock.recv(8)
    filesize = int.from_bytes(header, 'big')

    recv_and_save(sock, save_path, filesize)
    unzip(save_path, extract_path)

    print(f"[DONE] Extracted to {extract_path}")


def do_logout(sock):
    resp = request(sock, "logout")
    print(resp)


# ============================================================
# Main Menu
# ============================================================

def main():
    sock = connect_to_server()

    MENU = """
=============================
 Player Lobby CLI Menu
=============================
1. Register
2. Login
3. List Games
4. List Rooms
5. Create Room
6. Join Room
7. Start Game
8. Download Game
9. Logout
0. Exit
"""

    while True:
        print(MENU)
        choice = input("> ")

        if choice == "1": do_register(sock)
        elif choice == "2": do_login(sock)
        elif choice == "3": do_list_games(sock)
        elif choice == "4": do_list_rooms(sock)
        elif choice == "5": do_create_room(sock)
        elif choice == "6": do_join_room(sock)
        elif choice == "7": do_start_game(sock)
        elif choice == "8": do_download_game(sock)
        elif choice == "9": do_logout(sock)
        elif choice == "0":
            sock.close()
            break
        else:
            print("Invalid option.")


if __name__ == "__main__":
    main()
