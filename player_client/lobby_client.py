# player_lobby_client.py (or client/lobby_client.py, depending on your path)
import socket
import json
import subprocess
import time
import threading
import sys
import select
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
game_in_progress = False  # True while playing a text-based game

# For Player 2: monitor thread sets these when game is ready
pending_game_launch = None  # Dict with game_name, game_version, port, etc.


def connect_to_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((HOST, PORT))
    print(f"[CONNECTED] Lobby server at {HOST}:{PORT}")
    return s


def request(sock, action, data=None):
    msg = {"action": action, "data": data or {}}
    send(sock, msg)
    # Receive responses until we get a normal reply (has 'status').
    # The server may send asynchronous 'action' pushes on the same socket;
    # handle those locally and continue waiting for the actual reply.
    while True:
        resp = recv(sock)
        if resp is None:
            return None
        # If this is a push notification, handle locally then continue
        if isinstance(resp, dict) and resp.get("action"):
            act = resp.get("action")
            data = resp.get("data", {})
            print(f"[Push recv] {resp}")
            # If a game has started for our current room, set pending launch
            try:
                if act == "game_started":
                    rid = data.get("room_id")
                    port = data.get("port")
                    # Set a minimal pending launch; the main thread will resolve
                    # the actual metadata before launch.
                    if rid and port and rid == current_room_id:
                        global pending_game_launch
                        pending_game_launch = {"game_name": None, "game_version": None, "port": port, "username": current_user, "room_id": rid}
                        print(f"\n\n🎮 GAME STARTING (push)! Press Enter to launch...\n")
                        # keep waiting for the real reply to the original request
                        continue
            except Exception:
                pass
            continue

        # Normal reply expected to contain 'status'
        return resp


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
    # Prevent logging in to a second account in the same terminal session
    if current_user:
        print(f"Already logged in as '{current_user}'. Logout first to switch accounts.")
        return

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


def launch_game_client(game_name, game_version, port, username, room_id, inline=True):
    """Launch the game client GUI
    
    Args:
        inline: If True, run text-based games in current terminal (blocking).
                If False, spawn subprocess (for background monitor).
    """
    global game_launched, game_in_progress
    print(f"[LAUNCH] Request to launch {game_name} v{game_version} for {username} in room {room_id} on port {port}. game_launched={game_launched}")
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
    
    # Battleship is text-based
    if game_name.lower() == "battleship":
        cmd = [
            "python3",
            client_path,
            "--host", "127.0.0.1",
            "--port", str(port),
        ]
        # pass username and room to battleship client so server can record names
        cmd.extend(["--user", username or "Player", "--room", str(room_id)])
        
        # Always run in foreground - subprocess.run() gives full control of stdin/stdout
        game_in_progress = True
        try:
            print("[Battleship] Starting game - you have full control now...")
            result = subprocess.run(cmd)
            print(f"\n[Game finished with exit code {result.returncode}]")
        except Exception as e:
            print(f"[ERROR] Battleship error: {e}")
        finally:
            game_in_progress = False
            game_launched = False  # Allow rejoining games
        return
    
    # Tetris and other GUI games - spawn subprocess
    cmd = [
        "python3",
        client_path,
        "--host", "127.0.0.1",
        "--port", str(port),
    ]
    
    # Tetris supports additional arguments
    if game_name.lower() == "tetris":
        cmd.extend(["--user", username or "Player", "--room", str(room_id)])
    
    try:
        # Run Tetris in foreground so we can capture the final result
        if game_name.lower() == "tetris":
            game_in_progress = True
            print("[TETRIS] Launching GUI (foreground) - terminal will resume after game ends...")
            result = subprocess.run(cmd, capture_output=True, text=True)
            # attempt to parse JSON from stdout
            out = result.stdout.strip()
            parsed = None
            if out:
                try:
                    parsed = json.loads(out)
                except Exception:
                    # try to find JSON object in stdout lines
                    for line in out.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            parsed = json.loads(line)
                            break
                        except Exception:
                            continue

            # Print winner info if available
            if isinstance(parsed, dict) and parsed.get("winners"):
                winners = parsed.get("winners")
                if username in winners:
                    print(">>> You WIN 🎉 (Tetris)")
                else:
                    print(">>> You LOSE 💀 (Tetris)")
                print(f">>> Winners: {winners}")
            elif isinstance(parsed, dict) and parsed.get("error"):
                print(f"[TETRIS ERROR] {parsed.get('error')}")
            else:
                # no JSON result — show raw stdout/stderr for debugging
                if out:
                    print("[TETRIS OUTPUT]", out)
                if result.stderr:
                    print("[TETRIS ERROR OUTPUT]", result.stderr)

            game_in_progress = False
            game_launched = False
            return

        # For other GUI games just spawn in background
        subprocess.Popen(cmd)
        print(f"[✓] Game window launched!\n")
    except Exception as e:
        print(f"[✗] Error launching game: {e}")
        print(f"[i] Manual command: {' '.join(cmd)}\n")


def monitor_room_status():
    """Background thread to monitor room status and auto-launch game"""
    global monitoring_room, current_room_id, current_game_id, current_user, game_launched, pending_game_launch
    
    # Create a separate socket for monitoring to avoid thread conflicts
    try:
        monitor_sock = connect_to_server()
    except Exception as e:
        print(f"[Monitor] Failed to connect: {e}")
        return
    # Identify this monitor connection so the server can push notifications
    try:
        if current_user:
            request(monitor_sock, "identify", {"username": current_user, "role": "monitor"})
    except Exception:
        pass

    print(f"[Monitor] Starting monitoring for room {current_room_id}, game {current_game_id}, user {current_user}")
    
    while monitoring_room:
        try:
            if current_room_id and not game_launched and pending_game_launch is None:
                rooms_resp = request(monitor_sock, "list_rooms")

                # debug: show any pushed actions received on monitor socket
                if isinstance(rooms_resp, dict) and rooms_resp.get("action"):
                    print(f"[Monitor recv] {rooms_resp}")

                # server may send push notifications instead of a list_rooms reply
                # (e.g., action == 'game_started'). Handle that case.
                if isinstance(rooms_resp, dict) and rooms_resp.get("action") == "game_started":
                    d = rooms_resp.get("data", {})
                    print(f"[Monitor debug] current_room_id={current_room_id} current_game_id={current_game_id} user={current_user}")
                    print(f"[Monitor debug] push payload: {d}")
                    if d.get("room_id") == current_room_id and d.get("port"):
                        # Determine game_id from current rooms listing (more robust)
                        room_game_id = None
                        print("[Monitor debug] fetching room list to determine game_id...")
                        rr = request(monitor_sock, "list_rooms")
                        print(f"[Monitor debug] list_rooms response: {rr}")
                        if isinstance(rr, dict) and rr.get("status") == "ok":
                            for r in rr.get("data", {}).get("rooms", []):
                                if r.get("room_id") == current_room_id:
                                    room_game_id = r.get("game_id")
                                    break

                        if room_game_id is None:
                            # fallback to previously-known game id
                            room_game_id = current_game_id

                        # get games metadata to choose client
                        print("[Monitor debug] fetching game metadata...")
                        # Sometimes a pushed notification can be received on the
                        # socket before the server's reply to an earlier request;
                        # be defensive: retry a few times if the response doesn't
                        # contain the expected 'games' key.
                        games_resp = None
                        for attempt in range(3):
                            games_resp = request(monitor_sock, "list_games")
                            print(f"[Monitor debug] list_games response (attempt {attempt+1}): {games_resp}")
                            if isinstance(games_resp, dict) and games_resp.get("status") == "ok" and "games" in games_resp:
                                break
                            time.sleep(0.2)

                        if not (isinstance(games_resp, dict) and games_resp.get("status") == "ok" and "games" in games_resp):
                            # fallback: try to use previously-known current_game_id
                            print("[Monitor debug] list_games did not return games; falling back to current_game_id")
                            games = {}
                            game_info = None
                            if current_game_id:
                                # ask again once more to be sure
                                try:
                                    games_resp = request(monitor_sock, "list_games")
                                    games = games_resp.get("games", {}) if isinstance(games_resp, dict) else {}
                                except Exception:
                                    games = {}
                                game_info = games.get(current_game_id) or games.get(str(current_game_id))
                        else:
                            games = games_resp.get("games", {})
                            game_info = games.get(room_game_id) or games.get(str(room_game_id))
                        print(f"[Monitor debug] resolved game_info: {game_info}")
                        if game_info:
                            pending_game_launch = {
                                "game_name": game_info.get("name"),
                                "game_version": game_info.get("version", "1.0"),
                                "port": d.get("port"),
                                "username": current_user,
                                "room_id": current_room_id
                            }
                            print(f"\n\n🎮 GAME STARTING! Press Enter to launch {pending_game_launch['game_name']}...\n")
                            monitoring_room = False
                            monitor_sock.close()
                            return

                if rooms_resp.get("status") == "ok":
                    rooms_list = rooms_resp.get("data", {}).get("rooms", [])
                    
                    for room in rooms_list:
                        if room.get("room_id") == current_room_id:
                            # Check if game has started (status == "running" and port exists)
                            if room.get("status") == "running" and room.get("port"):
                                port = room.get("port")
                                
                                # Get game info
                                games_resp = request(monitor_sock, "list_games")
                                if games_resp.get("status") == "ok":
                                    games = games_resp.get("games", {})
                                    game_info = games.get(current_game_id) or games.get(str(current_game_id))
                                    
                                    if game_info:
                                        game_name = game_info.get("name")
                                        game_version = game_info.get("version", "1.0")
                                        
                                        # Signal main thread to launch the game
                                        pending_game_launch = {
                                            "game_name": game_name,
                                            "game_version": game_version,
                                            "port": port,
                                            "username": current_user,
                                            "room_id": current_room_id
                                        }
                                        print(f"\n\n🎮 GAME STARTING! Press Enter to launch {game_name}...\n")
                                        monitoring_room = False
                                        monitor_sock.close()
                                        return
                            break
            time.sleep(2)  # Poll every 2 seconds
        except Exception as e:
            print(f"[Monitor error: {e}]")
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
    global current_room_id, current_game_id, monitoring_room, game_launched
    room_id = int(input("Room ID to accept: "))
    resp = request(sock, "accept_invite", {"room_id": room_id})
    print(resp)
    if resp.get("status") == "ok":
        # Mirror the behavior of do_join_room: set local state and start monitor
        current_room_id = room_id
        game_launched = False

        # fetch room info to determine game_id
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
                    print("[Waiting for game to start...")
                    break


def do_revoke_invite(sock):
    room_id = int(input("Room ID: "))
    target = input("Username to revoke: ").strip()
    resp = request(sock, "revoke_invite", {"room_id": room_id, "target": target})
    print(resp)


def do_leaderboard(sock):
    """Request and display the global leaderboard (wins & games played)."""
    resp = request(sock, "leaderboard")
    if resp.get("status") != "ok":
        print(resp)
        return
    lb = resp.get("leaderboard", [])
    if not lb:
        print("No players found.")
        return

    print("\n=== Leaderboard ===")
    print(f"{'Rank':>4}  {'Player':<20} {'Wins':>4}  {'Played':>6}")
    print("-" * 40)
    for entry in lb:
        print(f"{entry.get('rank', '?'):>4}  {entry.get('username', ''):<20} {entry.get('wins', 0):>4}  {entry.get('played', 0):>6}")
    print()


def do_my_stats(sock):
    resp = request(sock, "my_stats")
    # If server says we're not logged in but the client still believes it
    # has a `current_user`, try a lightweight `resume` to re-associate this
    # connection with that username and retry the request.
    if resp.get("status") != "ok":
        if resp.get("msg") == "not_logged_in" and current_user:
            print("[Info] Server reports not_logged_in; attempting resume...")
            r2 = request(sock, "resume", {"username": current_user})
            if r2.get("status") == "ok":
                resp = request(sock, "my_stats")
            else:
                print(r2)
                return
        else:
            print(resp)
            return
    d = resp.get("data", {})
    print("\n=== My Stats ===")
    print(f"Player: {d.get('username')}\nWins: {d.get('wins', 0)}\nPlayed: {d.get('played', 0)}\n")


# ============================================================
# Main Menu
# ============================================================

def main():
    global pending_game_launch, game_in_progress
    
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
14. Show Leaderboard
15. My Stats
0. Exit
"""

    while True:
        # Check if monitor thread detected a game starting
        if pending_game_launch is not None:
            info = pending_game_launch
            pending_game_launch = None
            # If the push didn't include resolved metadata, query the server
            # for room -> game mapping and games metadata before launching.
            if not info.get("game_name"):
                try:
                    # get room list to find game_id
                    rooms_resp = request(sock, "list_rooms")
                    room_game_id = None
                    if rooms_resp.get("status") == "ok":
                        for r in rooms_resp.get("data", {}).get("rooms", []):
                            if r.get("room_id") == info.get("room_id"):
                                room_game_id = r.get("game_id")
                                break

                    # get games metadata
                    games_resp = request(sock, "list_games")
                    game_name = None
                    game_version = None
                    if games_resp.get("status") == "ok":
                        games = games_resp.get("games", {})
                        game_info = games.get(room_game_id) or games.get(str(room_game_id))
                        if game_info:
                            game_name = game_info.get("name")
                            game_version = game_info.get("version", "1.0")
                    # fill in resolved metadata
                    info["game_name"] = game_name or "Unknown"
                    info["game_version"] = game_version or "1.0"
                except Exception as e:
                    print(f"[Error resolving game metadata before launch: {e}]")

            launch_game_client(
                info["game_name"], 
                info["game_version"], 
                info["port"], 
                info["username"], 
                info["room_id"]
            )
            continue

        # Don't show menu while a text-based game is in progress
        if game_in_progress:
            time.sleep(0.5)
            continue

        # Print menu once and then poll stdin so we can wake up to pending launches
        print(MENU)
        choice = None
        print("> ", end="", flush=True)

        # Poll for input while periodically checking pending_game_launch
        while choice is None:
            # If monitor thread set a launch, handle it immediately
            if pending_game_launch is not None:
                info = pending_game_launch
                pending_game_launch = None
                # resolve metadata if missing
                if not info.get("game_name"):
                    try:
                        rooms_resp = request(sock, "list_rooms")
                        room_game_id = None
                        if rooms_resp.get("status") == "ok":
                            for r in rooms_resp.get("data", {}).get("rooms", []):
                                if r.get("room_id") == info.get("room_id"):
                                    room_game_id = r.get("game_id")
                                    break
                        games_resp = request(sock, "list_games")
                        game_name = None
                        game_version = None
                        if games_resp.get("status") == "ok":
                            games = games_resp.get("games", {})
                            game_info = games.get(room_game_id) or games.get(str(room_game_id))
                            if game_info:
                                game_name = game_info.get("name")
                                game_version = game_info.get("version", "1.0")
                        info["game_name"] = game_name or "Unknown"
                        info["game_version"] = game_version or "1.0"
                    except Exception as e:
                        print(f"[Error resolving game metadata before launch: {e}]")

                launch_game_client(
                    info["game_name"], 
                    info["game_version"], 
                    info["port"], 
                    info["username"], 
                    info["room_id"]
                )
                choice = ""
                break

            # Wait up to 0.5s for user input
            try:
                r, _, _ = select.select([sys.stdin], [], [], 0.5)
            except Exception:
                r = []

            if r:
                line = sys.stdin.readline()
                if not line:
                    # EOF / ctrl-d
                    sock.close()
                    return
                choice = line.strip()
                break

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
        elif choice == "14": do_leaderboard(sock)
        elif choice == "15": do_my_stats(sock)
        elif choice == "0":
            sock.close()
            break
        elif choice == "":
            # empty string because we launched due to pending_game_launch
            continue
        else:
            print("Invalid option.")


if __name__ == "__main__":
    main()
