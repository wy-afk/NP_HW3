# player_lobby_client.py (or client/lobby_client.py, depending on your path)
import socket
import json
import subprocess
import time
import threading
from utils.protocol import send, recv
from utils.file_downloader import recv_and_save, unzip

HOST = "127.0.0.1"
PORT = 5555

# Track current user and game info
current_user = None
current_room_id = None
current_game_id = None
monitoring_room = False
game_launched = False


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
    global current_user
    username = input("Username: ")
    password = input("Password: ")
    role = input("Role (player/developer): ").strip().lower()

    resp = request(sock, "login", {
        "username": username,
        "password": password,
        "role": role
    })
    print(resp)
    if resp.get("status") == "ok":
        current_user = username
        print(f"[Logged in as: {current_user}]")


def do_list_games(sock):
    resp = request(sock, "list_games")
    print(json.dumps(resp, indent=2))


def do_list_rooms(sock):
    resp = request(sock, "list_rooms")
    print(json.dumps(resp, indent=2))


def launch_game_client(game_name, game_version, port, username, room_id):
    """Launch the game client GUI"""
    global game_launched
    if game_launched:
        return
    
    game_launched = True
    client_path = f"downloads/{game_name}/{game_version}/client/{game_name.lower()}_client.py"
    
    print(f"\n{'='*60}")
    print(f"🎮 LAUNCHING {game_name.upper()} GAME")
    print(f"{'='*60}")
    print(f"Server: 127.0.0.1:{port}")
    print(f"Player: {username}")
    print(f"Room: {room_id}")
    print(f"{'='*60}\n")
    
    cmd = [
        "python3",
        client_path,
        "--host", "127.0.0.1",
        "--port", str(port),
        "--user", username or "Player",
        "--room", str(room_id)
    ]
    
    try:
        subprocess.Popen(cmd)
        print(f"[✓] Game window launched!\n")
    except Exception as e:
        print(f"[✗] Error launching game: {e}")
        print(f"[i] Manual command: {' '.join(cmd)}\n")


def monitor_room_status():
    """Background thread to monitor room status and auto-launch game"""
    global monitoring_room, current_room_id, current_game_id, current_user, game_launched
    
    # Create a separate socket for monitoring to avoid thread conflicts
    try:
        monitor_sock = connect_to_server()
    except Exception as e:
        print(f"[Monitor] Failed to connect: {e}")
        return
    
    print(f"[Monitor] Starting monitoring for room {current_room_id}, game {current_game_id}, user {current_user}")
    
    while monitoring_room:
        try:
            if current_room_id and not game_launched:
                rooms_resp = request(monitor_sock, "list_rooms")
                print(f"[Monitor] list_rooms response: {rooms_resp}")
                
                if rooms_resp.get("status") == "ok":
                    rooms_list = rooms_resp.get("data", {}).get("rooms", [])
                    print(f"[Monitor] Found {len(rooms_list)} rooms")
                    
                    for room in rooms_list:
                        print(f"[Monitor] Checking room: {room}")
                        if room.get("room_id") == current_room_id:
                            print(f"[Monitor] Found our room! Status: {room.get('status')}, Port: {room.get('port')}")
                            # Check if game has started (status == "running" and port exists)
                            if room.get("status") == "running" and room.get("port"):
                                port = room.get("port")
                                print(f"[Monitor] Game is running! Port: {port}")
                                
                                # Get game info
                                games_resp = request(monitor_sock, "list_games")
                                if games_resp.get("status") == "ok":
                                    games = games_resp.get("games", {})
                                    game_info = games.get(current_game_id) or games.get(str(current_game_id))
                                    print(f"[Monitor] Game info: {game_info}")
                                    
                                    if game_info:
                                        game_name = game_info.get("name")
                                        game_version = game_info.get("version", "1.0")
                                        print(f"[Monitor] Launching {game_name} v{game_version}")
                                        launch_game_client(game_name, game_version, port, current_user, current_room_id)
                                        monitoring_room = False
                                        monitor_sock.close()
                                        return
                            break
            time.sleep(2)  # Poll every 2 seconds
        except Exception as e:
            print(f"[Monitor error: {e}]")
            import traceback
            traceback.print_exc()
            time.sleep(2)
    
    monitor_sock.close()


def do_create_room(sock):
    global current_room_id, current_game_id
    game_id = int(input("Game ID: "))
    room_type = input("Room type (public/private): ").strip().lower()

    resp = request(sock, "create_room", {
        "game_id": game_id,
        "type": room_type
    })
    print(resp)
    if resp.get("status") == "ok":
        current_room_id = resp.get("room_id")
        current_game_id = game_id
        print(f"[Created room {current_room_id} for game {current_game_id}]")



def do_join_room(sock):
    global current_room_id, current_game_id, monitoring_room, game_launched
    room_id = int(input("Room ID: "))
    resp = request(sock, "join_room", {"room_id": room_id})
    print(resp)
    if resp.get("status") == "ok":
        current_room_id = room_id
        game_launched = False
        # Get room info to find game_id
        rooms_resp = request(sock, "list_rooms")
        if rooms_resp.get("status") == "ok":
            for room in rooms_resp.get("data", {}).get("rooms", []):
                if room.get("room_id") == room_id:
                    current_game_id = room.get("game_id")
                    print(f"[Joined room {current_room_id} for game {current_game_id}]")
                    
                    # Start monitoring for game start
                    monitoring_room = True
                    monitor_thread = threading.Thread(target=monitor_room_status, daemon=True)
                    monitor_thread.start()
                    print("[Waiting for game to start...]")
                    break


def do_start_game(sock):
    global current_user, current_room_id, current_game_id
    room_id = int(input("Room ID: "))
    resp = request(sock, "start_game", {"room_id": room_id})
    print(resp)
    
    if resp.get("status") == "ok":
        # Handle nested data format
        port = resp.get("data", {}).get("port") or resp.get("port")
        
        # If we don't have game_id, fetch it from room info
        game_id_to_use = current_game_id
        if not game_id_to_use:
            rooms_resp = request(sock, "list_rooms")
            if rooms_resp.get("status") == "ok":
                for room in rooms_resp.get("data", {}).get("rooms", []):
                    if room.get("room_id") == room_id:
                        game_id_to_use = room.get("game_id")
                        break
        
        # Get game info to determine which client to launch
        games_resp = request(sock, "list_games")
        game_name = None
        game_version = None
        
        if games_resp.get("status") == "ok":
            games = games_resp.get("games", {})
            # Try integer key first, then string key
            game_info = games.get(game_id_to_use) or games.get(str(game_id_to_use))
            
            if game_info:
                game_name = game_info.get("name")
                game_version = game_info.get("version", "1.0")
        
        if game_name and port:
            launch_game_client(game_name, game_version, port, current_user, room_id)
        else:
            print(f"[ERROR] Could not determine game to launch. game_name={game_name}, port={port}, game_id={game_id_to_use}")


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

    save_path = f"/tmp/{filename}"
    extract_path = f"downloads/{info['name']}/{info['version']}"

    print(f"[DOWNLOADING] {filename} ({filesize} bytes)")

    header = sock.recv(8)
    filesize = int.from_bytes(header, "big")

    recv_and_save(sock, save_path, filesize)
    unzip(save_path, extract_path)

    print(f"[DONE] Extracted to {extract_path}")


def do_logout(sock):
    global current_user, current_room_id, current_game_id
    resp = request(sock, "logout")
    print(resp)
    current_user = None
    current_room_id = None
    current_game_id = None


# ---------- NEW: PRIVATE ROOM COMMANDS ----------

def do_invite_user(sock):
    room_id = int(input("Your private Room ID: "))
    target = input("Username to invite: ").strip()
    resp = request(sock, "invite_user", {"room_id": room_id, "target": target})
    print(resp)


def do_list_invites(sock):
    resp = request(sock, "list_invites")
    print(json.dumps(resp, indent=2))


def do_accept_invite(sock):
    room_id = int(input("Room ID to accept: "))
    resp = request(sock, "accept_invite", {"room_id": room_id})
    print(resp)


def do_revoke_invite(sock):
    room_id = int(input("Room ID: "))
    target = input("Username to revoke: ").strip()
    resp = request(sock, "revoke_invite", {"room_id": room_id, "target": target})
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
10. Invite user to PRIVATE room
11. List my invites
12. Accept invite
13. Revoke invite (host)
0. Exit
"""

    while True:
        print(MENU)
        choice = input("> ").strip()

        if choice == "1":   do_register(sock)
        elif choice == "2": do_login(sock)
        elif choice == "3": do_list_games(sock)
        elif choice == "4": do_list_rooms(sock)
        elif choice == "5": do_create_room(sock)
        elif choice == "6": do_join_room(sock)
        elif choice == "7": do_start_game(sock)
        elif choice == "8": do_download_game(sock)
        elif choice == "9": do_logout(sock)
        elif choice == "10": do_invite_user(sock)
        elif choice == "11": do_list_invites(sock)
        elif choice == "12": do_accept_invite(sock)
        elif choice == "13": do_revoke_invite(sock)
        elif choice == "0":
            sock.close()
            break
        else:
            print("Invalid option.")


if __name__ == "__main__":
    main()
