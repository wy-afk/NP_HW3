#!/usr/bin/env python3
"""Minimal Player CLI (refactored into layered menus).

This client is a compact, robust replacement of the previous long
script. It uses the project's `player_client.utils.protocol` helpers to
talk to the lobby server. The goal is to provide a clean onboarding
experience with a simple initial menu and layered authenticated/room
menus as requested.
"""
import socket
import json
import sys
from typing import Optional
import threading
import time
import os
import subprocess
import select
import shutil

_PLAYER_CLIENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PLAYER_DOWNLOADS_DIR = os.path.join(_PLAYER_CLIENT_DIR, "downloads")

# Allow running as `python3 player_client/lobby_client.py` from repo root
# without requiring `player_client` to be an importable package.
if _PLAYER_CLIENT_DIR not in sys.path:
    sys.path.insert(0, _PLAYER_CLIENT_DIR)

try:
    from player_client.utils.protocol import send, recv
except Exception:
    from utils.protocol import send, recv


def connect_to_server(host: str = "127.0.0.1", port: int = 5555):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, port))
    return s


def request(sock, action: str, data: dict = None):
    payload = {"action": action, "data": data or {}}
    try:
        send(sock, payload)
    except Exception as e:
        print(f"[request] send failed: {e}")
        return None
    resp = recv(sock)
    return resp


def _extract_rooms(list_rooms_resp: dict):
    if not isinstance(list_rooms_resp, dict):
        return []
    data = list_rooms_resp.get("data")
    if isinstance(data, dict) and isinstance(data.get("rooms"), list):
        return data.get("rooms")
    # fallback
    if isinstance(list_rooms_resp.get("rooms"), list):
        return list_rooms_resp.get("rooms")
    return []


def _extract_games(list_games_resp: dict):
    if not isinstance(list_games_resp, dict):
        return {}
    games = list_games_resp.get("games")
    if isinstance(games, dict):
        return games
    data = list_games_resp.get("data")
    if isinstance(data, dict) and isinstance(data.get("games"), dict):
        return data.get("games")
    return {}


def _resolve_game_for_room(sock, room_id: int):
    """Return (game_id, game_name, game_version) for a room_id, or (None, None, None)."""
    rr = request(sock, "list_rooms")
    room_game_id = None
    for r in _extract_rooms(rr):
        if r.get("room_id") == room_id:
            room_game_id = r.get("game_id")
            break

    if room_game_id is None:
        return None, None, None

    gg = request(sock, "list_games")
    games = _extract_games(gg)
    gi = games.get(room_game_id) or games.get(str(room_game_id))
    if not isinstance(gi, dict):
        return room_game_id, None, None
    return room_game_id, gi.get("name"), gi.get("version", "1.0")


def _do_download_game_noninteractive(sock, game_id: int, download_user: str):
    """Non-interactive downloader used by auto-download flows.

    If download_user is falsy, installs to shared `downloads/<Game>/<Version>`.
    Returns the extract path on success.
    """
    resp = request(sock, "download_game_meta", {"game_id": game_id})
    if not resp or resp.get("status") != "ok":
        raise RuntimeError(f"Server returned download metadata error: {resp}")

    info = resp.get("data", {})
    filename = info.get("filename")
    filesize = int(info.get("filesize", 0))
    if not filename or not filesize:
        raise RuntimeError(f"Server download metadata incomplete: {info}")

    name = info.get("name")
    version = info.get("version")
    if download_user:
        extract_path = os.path.join(_PLAYER_DOWNLOADS_DIR, download_user, name, str(version))
    else:
        extract_path = os.path.join(_PLAYER_DOWNLOADS_DIR, name, str(version))
    os.makedirs(extract_path, exist_ok=True)

    save_path = f"/tmp/{filename}"
    print(f"[Auto-Download] {filename} ({filesize} bytes) -> {extract_path}")

    # Read 8-byte header then the file bytes
    header = sock.recv(8)
    size = int.from_bytes(header, "big")
    if size != filesize:
        print(f"[Warning] server filesize {size} != metadata {filesize}")

    from utils.file_downloader import recv_and_save, unzip
    recv_and_save(sock, save_path, size)
    unzip(save_path, extract_path)
    try:
        os.remove(save_path)
    except Exception:
        pass
    return extract_path


def _build_game_client_cmd(client_script_path: str, port: int, username: str, room_id: int):
    host = "127.0.0.1"
    return [
        sys.executable,
        client_script_path,
        "--host",
        host,
        "--port",
        str(port),
        "--user",
        username or "Player",
        "--room",
        str(room_id),
    ]


def _prompt_username_for_local_installs(current_user: Optional[str]):
    if current_user:
        return current_user
    u = input("Username for local installs (blank to cancel): ").strip()
    return u or None


def do_download_install_game(sock, current_user: Optional[str]):
    """Interactive download/install flow.

    Downloads a game package zip from the server and extracts it into
    `player_client/downloads/<username>/<Game>/<Version>`.
    """
    username = _prompt_username_for_local_installs(current_user)
    if not username:
        print("Cancelled")
        return

    gg = request(sock, "list_games")
    games = _extract_games(gg)
    if not games:
        print("No games available on server")
        return

    print("\nAvailable server games:")
    items = []
    for gid, meta in games.items():
        if not isinstance(meta, dict):
            continue
        try:
            gid_int = int(gid)
        except Exception:
            gid_int = None
        items.append((gid, gid_int, meta))

    items.sort(key=lambda x: x[1] if x[1] is not None else str(x[0]))
    for gid, _, meta in items:
        print(f"ID={gid}  {meta.get('name')} v{meta.get('version', '1.0')}")

    raw = input("Game ID to download (blank to cancel): ").strip()
    if raw == "":
        print("Cancelled")
        return

    meta = games.get(raw)
    if meta is None:
        try:
            meta = games.get(int(raw))
        except Exception:
            meta = None
    if not isinstance(meta, dict):
        print("Invalid game id")
        return

    try:
        gid_to_use = int(raw)
    except Exception:
        try:
            gid_to_use = int(meta.get('id'))
        except Exception:
            print("Invalid game id")
            return

    try:
        extract_path = _do_download_game_noninteractive(sock, gid_to_use, username)
        print(f"[Installed] {meta.get('name')} v{meta.get('version', '1.0')} -> {extract_path}")
    except Exception as e:
        print(f"Download failed: {e}")


def _list_installed_games(username: str):
    """Return list of dicts: {game, version, path} for a user."""
    base = os.path.join(_PLAYER_DOWNLOADS_DIR, username)
    if not os.path.isdir(base):
        return []
    rows = []
    for game in sorted(os.listdir(base)):
        gdir = os.path.join(base, game)
        if not os.path.isdir(gdir):
            continue
        for version in sorted(os.listdir(gdir)):
            vdir = os.path.join(gdir, version)
            if os.path.isdir(vdir):
                rows.append({"game": game, "version": version, "path": vdir})
    return rows


def do_delete_installed_game(current_user: Optional[str]):
    """Delete a locally installed game for a user (local filesystem only)."""
    username = _prompt_username_for_local_installs(current_user)
    if not username:
        print("Cancelled")
        return

    rows = _list_installed_games(username)
    if not rows:
        print(f"No installed games found under {_PLAYER_DOWNLOADS_DIR}/{username}")
        return

    print(f"\nInstalled games for {username}:")
    for i, r in enumerate(rows, start=1):
        print(f"{i}. {r['game']} v{r['version']}")
    print("0. Cancel")

    raw = input(f"Select game to delete (0-{len(rows)}): ").strip()
    if raw in ("", "0"):
        print("Cancelled")
        return
    try:
        idx = int(raw)
        if idx < 1 or idx > len(rows):
            raise ValueError()
    except Exception:
        print("Invalid selection")
        return

    target = rows[idx - 1]
    confirm = input(f"Confirm delete {target['game']} v{target['version']} for {username}? (y/N): ").strip().lower()
    if confirm != "y":
        print("Cancelled")
        return

    abs_target = os.path.abspath(target["path"])
    abs_allowed = os.path.abspath(os.path.join(_PLAYER_DOWNLOADS_DIR, username))
    if not abs_target.startswith(abs_allowed + os.sep):
        print("[ERROR] Refusing to delete path outside downloads folder")
        return

    try:
        shutil.rmtree(abs_target)
        print("Deleted")
    except Exception as e:
        print(f"Delete failed: {e}")


# Monitor worker: maintain a separate monitor connection so server pushes
# (e.g. game_started) can be received without interfering with the main
# request/response socket used by the interactive client.
monitor_thread = None
monitor_sock = None

# Globals used by legacy and newer flows. Keep predictable defaults so
# static analyzers and runtime code won't report NameError for these
# cross-cutting variables.
current_user = None
current_room_id = None
current_game_id = None
pending_game_launch = None
game_in_progress = False
monitoring_room = False
game_launched = False

_pending_launch_event = threading.Event()
_pending_launch_lock = threading.Lock()
_pending_launch = None


def _queue_pending_launch(game_name: str, game_version: str, port: int, username: str, room_id: int):
    global _pending_launch
    with _pending_launch_lock:
        _pending_launch = {
            "game_name": game_name,
            "game_version": game_version,
            "port": int(port),
            "username": username,
            "room_id": int(room_id),
        }
        _pending_launch_event.set()


def _take_pending_launch():
    """Take and clear the pending launch, returning dict or None."""
    global _pending_launch
    with _pending_launch_lock:
        info = _pending_launch
        _pending_launch = None
        _pending_launch_event.clear()
        return info


def _prompt_interruptible(prompt_text: str):
    """Like input(), but returns None if a pending game launch arrives.

    On Linux terminals, this allows the UI to switch to the game without
    fighting over stdin.
    """
    # If a launch is pending, don't read more input.
    if _pending_launch_event.is_set():
        return None

    # Non-interactive stdin: fall back to plain input
    if not sys.stdin or not sys.stdin.isatty():
        return input(prompt_text)

    sys.stdout.write(prompt_text)
    sys.stdout.flush()
    while True:
        if _pending_launch_event.is_set():
            sys.stdout.write("\n")
            sys.stdout.flush()
            return None
        r, _, _ = select.select([sys.stdin], [], [], 0.2)
        if r:
            line = sys.stdin.readline()
            if line == "":
                return ""
            return line.rstrip("\n")

def start_monitor_for_user(username):
    """Start a background monitor connection identified as `monitor`.
    Server pushes (action without status) will be received here and
    handled (for now we only handle 'game_started')."""
    global monitor_thread, monitor_sock
    if monitor_thread is not None and monitor_thread.is_alive():
        return
    try:
        monitor_sock = connect_to_server()
        # identify monitor connection
        try:
            request(monitor_sock, "identify", {"username": username, "role": "monitor"})
        except Exception:
            pass
    except Exception as e:
        print(f"[Monitor] failed to connect: {e}")
        return

    def _loop():
        while True:
            try:
                msg = recv(monitor_sock)
            except Exception:
                break
            if not isinstance(msg, dict):
                continue
            act = msg.get("action")
            if act == "game_started":
                data = msg.get("data", {})
                room_id = data.get("room_id")
                port = data.get("port")
                game_name = data.get("game_name")
                game_version = data.get("game_version") or data.get("version") or "1.0"
                room_game_id = data.get("game_id")
                print(f"\n[Monitor] game_started push: {data}")

                # If we still don't know the game_id, attempt to fetch it
                try:
                    if room_game_id is None:
                        rr = request(monitor_sock, "list_rooms")
                        if isinstance(rr, dict) and rr.get("status") == "ok":
                            for r in rr.get("data", {}).get("rooms", []):
                                if r.get("room_id") == room_id:
                                    room_game_id = r.get("game_id")
                                    break
                except Exception:
                    pass

                # If the push didn't include game metadata, resolve it now.
                if (not game_name) and room_game_id is not None:
                    try:
                        gg = request(monitor_sock, "list_games")
                        games = _extract_games(gg)
                        gi = games.get(room_game_id) or games.get(str(room_game_id))
                        if isinstance(gi, dict):
                            game_name = gi.get("name")
                            game_version = gi.get("version", game_version)
                    except Exception:
                        pass

                if port and game_name:
                    # Try non-interactive auto-download if local copy missing
                    try:
                        local_path = os.path.join(_PLAYER_DOWNLOADS_DIR, username, game_name, str(game_version))
                        if not os.path.isdir(local_path) and room_game_id is not None:
                            print(f"[Monitor] Auto-download missing client to {local_path}...")
                            try:
                                _do_download_game_noninteractive(monitor_sock, int(room_game_id), username)
                                print("[Monitor] Auto-download complete")
                            except Exception as e:
                                print(f"[Monitor] Auto-download failed: {e}")
                    except Exception:
                        pass

                    # Queue a pending launch. The main thread will run the
                    # game in the foreground, then return to the menus.
                    _queue_pending_launch(game_name, game_version, int(port), username, int(room_id))
                    print("[Monitor] game ready; switching to game...")
        try:
            monitor_sock.close()
        except Exception:
            pass

    monitor_thread = threading.Thread(target=_loop, daemon=True)
    monitor_thread.start()


def monitor_room_status():
    """Legacy stub used by older join/accept flows.

    The newer push-based monitor uses `start_monitor_for_user`. Keep a
    simple no-op loop here so older code that starts a thread won't
    crash. This function intentionally does not attempt server
    communications; it simply waits until `monitoring_room` becomes
    False.
    """
    global monitoring_room
    try:
        while monitoring_room:
            time.sleep(0.5)
    except Exception:
        pass


def launch_game_client(
    game_name,
    game_version,
    port,
    username,
    room_id,
    foreground: bool = False,
    replace_process: bool = False,
):
    """Attempt to launch a local game client for the given user.

    This is a best-effort launcher: it looks under the per-user
    `downloads/<username>/<game_name>/<version>` folder and tries to run
    the first Python script it finds. If none is found it prints a
    helpful message and returns False.
    """
    # New default: per-player downloads live under player_client/downloads/
    per_user_base = os.path.join(_PLAYER_DOWNLOADS_DIR, username, game_name, str(game_version)) if username else None
    shared_base = os.path.join(_PLAYER_DOWNLOADS_DIR, game_name, str(game_version))
    # Backward-compatible fallbacks (older shared root downloads)
    legacy_shared_base = f"downloads/{game_name}/{game_version}"
    legacy_per_user_base = f"downloads/{username}/{game_name}/{game_version}" if username else None
    print(f"[Launcher] launching {game_name} v{game_version} for {username} (room {room_id}) on port {port}")

    # Prefer shared installation path, fall back to per-user install.
    if per_user_base and os.path.isdir(per_user_base):
        base = per_user_base
    elif os.path.isdir(shared_base):
        base = shared_base
    elif legacy_per_user_base and os.path.isdir(legacy_per_user_base):
        base = legacy_per_user_base
    elif os.path.isdir(legacy_shared_base):
        base = legacy_shared_base
    else:
        print(f"[Launcher] no local client found at {per_user_base} or {shared_base}")
        return False

    # Prefer a script that looks like a client entrypoint.
    candidates = []
    for root, _, files in os.walk(base):
        for fn in files:
            if fn.lower().endswith('.py'):
                candidates.append(os.path.join(root, fn))

    if not candidates:
        print("[Launcher] no runnable client script found in package")
        return False

    # Prefer <game>_client.py or tetris_client.py etc.
    g = (game_name or "").lower()
    preferred = None
    for pth in candidates:
        bn = os.path.basename(pth).lower()
        if bn == f"{g}_client.py" or bn.endswith("_client.py"):
            preferred = pth
            break
    path = preferred or candidates[0]

    host = "127.0.0.1"
    cmd = _build_game_client_cmd(path, int(port), username, int(room_id))

    try:
        if foreground:
            # Run in the foreground so this terminal becomes the game.
            return subprocess.call(cmd) == 0

        subprocess.Popen(cmd)
        return True
    except Exception as e:
        print(f"[Launcher] failed to start {path}: {e}")
        return False


def _maybe_run_pending_launch():
    if not _pending_launch_event.is_set():
        return False
    info = _take_pending_launch()
    if not info:
        return False
    try:
        launch_game_client(
            info["game_name"],
            info["game_version"],
            info["port"],
            info["username"],
            info["room_id"],
            foreground=True,
        )
    except Exception as e:
        print(f"[Launcher] failed: {e}")
    return True


# --- Basic actions ---
def do_register(sock):
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    role = "player"
    resp = request(sock, "register", {"username": username, "password": password, "role": role})
    print(resp)


def do_login(sock) -> Optional[str]:
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    resp = request(sock, "login", {"username": username, "password": password, "role": "player"})
    print(resp)
    # Some server implementations keep session state per-connection and
    # will reply already_logged_in if the client tries to login twice.
    # Treat that case as success for UX.
    if resp and resp.get("status") == "error" and resp.get("msg") == "already_logged_in":
        return username

    if resp and resp.get("status") == "ok":
        try:
            request(sock, "identify", {"username": username, "role": "client"})
        except Exception:
            pass
        # start monitor connection so server pushes (game_started) are
        # received on a separate socket and can auto-launch the client
        try:
            start_monitor_for_user(username)
        except Exception:
            pass
        return username
    return None


def do_list_games(sock):
    resp = request(sock, "list_games")
    print(json.dumps(resp, indent=2))


def do_list_rooms(sock):
    resp = request(sock, "list_rooms")
    print(json.dumps(resp, indent=2))


def do_create_room(sock):
    try:
        game_id = int(input("Game ID: ").strip())
    except Exception:
        print("Invalid game id")
        return None
    # Ask whether the room should be public or private (default: public)
    rt = input("Room type (public/private) [public]: ").strip().lower() or "public"
    if rt not in ("public", "private"):
        print("Invalid room type; using 'public'")
        rt = "public"
    r = request(sock, "create_room", {"game_id": game_id, "type": rt})
    print(r)
    return r


def do_join_room(sock):
    while True:
        raw = input("Room ID (blank to cancel): ").strip()
        if raw == "":
            print("Cancelled")
            return None
        try:
            room_id = int(raw)
            break
        except Exception:
            print("Invalid room id")
    r = request(sock, "join_room", {"room_id": room_id})
    print(r)
    return r


def do_start_game(sock, username: str, room_id: int):
    r = request(sock, "start_game", {"room_id": room_id})
    print(r)
    if not isinstance(r, dict) or r.get("status") != "ok":
        return False

    port = None
    if isinstance(r.get("data"), dict):
        port = r.get("data", {}).get("port")
    port = port or r.get("port")
    if not port:
        print("[StartGame] missing port in response")
        return False

    game_id, game_name, game_version = _resolve_game_for_room(sock, room_id)
    if not game_name:
        print("[StartGame] could not resolve game metadata")
        return False

    local_path = os.path.join(_PLAYER_DOWNLOADS_DIR, username, game_name, str(game_version))
    if not os.path.isdir(local_path) and game_id is not None:
        try:
            _do_download_game_noninteractive(sock, int(game_id), username)
        except Exception as e:
            print(f"[StartGame] auto-download failed: {e}")
            return False

    # Run the game in the foreground so it immediately takes over this terminal.
    ok = launch_game_client(game_name, game_version, int(port), username, room_id, foreground=True)
    return bool(ok)


def do_my_stats(sock):
    r = request(sock, "my_stats")
    print(json.dumps(r, indent=2))


def do_leaderboard(sock):
    r = request(sock, "leaderboard")
    if not isinstance(r, dict) or r.get("status") != "ok":
        print(r)
        return

    entries = r.get("leaderboard")
    if not isinstance(entries, list):
        print(r)
        return

    # Normalize + sort by wins desc, then played desc, then username asc
    normalized = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        username = str(e.get("username", ""))
        try:
            wins = int(e.get("wins", 0))
        except Exception:
            wins = 0
        try:
            played = int(e.get("played", 0))
        except Exception:
            played = 0
        normalized.append({"username": username, "wins": wins, "played": played})

    normalized.sort(key=lambda x: (-x["wins"], -x["played"], x["username"]))

    # Assign sequential ranks after sorting
    rows = []
    for idx, e in enumerate(normalized, start=1):
        rows.append({"rank": idx, **e})

    headers = ["Rank", "Username", "Wins", "Played"]
    col_rank = max(len(headers[0]), max((len(str(x["rank"])) for x in rows), default=1))
    col_user = max(len(headers[1]), max((len(x["username"]) for x in rows), default=1))
    col_wins = max(len(headers[2]), max((len(str(x["wins"])) for x in rows), default=1))
    col_played = max(len(headers[3]), max((len(str(x["played"])) for x in rows), default=1))

    fmt = f"{{:>{col_rank}}}  {{:<{col_user}}}  {{:>{col_wins}}}  {{:>{col_played}}}"
    print(fmt.format(*headers))
    print(
        f"{'-'*col_rank}  {'-'*col_user}  {'-'*col_wins}  {'-'*col_played}"
    )
    for x in rows:
        print(fmt.format(x["rank"], x["username"], x["wins"], x["played"]))


def do_logout(sock):
    r = request(sock, "logout")
    print(r)


def do_invite_user(sock, room_id: Optional[int] = None):
    if room_id is None:
        try:
            room_id = int(input("Your private Room ID: ").strip())
        except Exception:
            print("Invalid room id")
            return
    target = input("Username to invite: ").strip()
    r = request(sock, "invite_user", {"room_id": int(room_id), "target": target})
    print(r)


def do_list_invites(sock):
    r = request(sock, "list_invites")
    print(json.dumps(r, indent=2))


def do_accept_invite(sock, room_id: Optional[int] = None):
    if room_id is None:
        try:
            room_id = int(input("Room ID to accept: ").strip())
        except Exception:
            print("Invalid room id")
            return
    r = request(sock, "accept_invite", {"room_id": room_id})
    print(r)
    return r


# Simple placeholders for chat and reviews to avoid hiding features
def room_chat_menu(sock):
    while True:
        print("\n--- Room Chat ---")
        print("1. Show chat")
        print("2. Send message")
        print("0. Back")
        c = input("Choice: ").strip()
        if c == "1":
            r = request(sock, "list_room_chat")
            print(json.dumps(r, indent=2))
        elif c == "2":
            rid = input("Room ID: ").strip()
            msg = input("Message: ")
            r = request(sock, "send_room_chat", {"room_id": int(rid), "message": msg})
            print(r)
        elif c == "0":
            return
        else:
            print("Invalid")


def review_menu(sock):
    while True:
        print("\n--- Reviews ---")
        print("1. View reviews for a game")
        print("2. Submit review")
        print("0. Back")
        c = input("Choice: ").strip()
        if c == "1":
            gid = input("Game ID: ").strip()
            r = request(sock, "get_reviews", {"game_id": int(gid)})
            print(json.dumps(r, indent=2))
        elif c == "2":
            gid = input("Game ID: ").strip()
            score = int(input("Score (1-5): ").strip())
            text = input("Review text: ")
            r = request(sock, "submit_review", {"game_id": int(gid), "score": score, "text": text})
            print(r)
        elif c == "0":
            return
        else:
            print("Invalid")


def main():
    sock = connect_to_server()
    current_user = None
    current_room = None

    def initial_menu():
        nonlocal current_user
        while True:
            print("\n=== Welcome ===")
            print("1. Register")
            print("2. Login")
            print("3. Leaderboard")
            print("4. Download / Install game")
            print("5. Delete installed game")
            if current_user:
                print("6. Back to Home")
            print("0. Exit")
            c = input("Choice: ").strip()
            if c == "1":
                do_register(sock)
            elif c == "2":
                if current_user:
                    print(f"Already logged in as {current_user}")
                    continue
                u = do_login(sock)
                if u:
                    current_user = u
                    authenticated_menu()
            elif c == "3":
                do_leaderboard(sock)
            elif c == "4":
                do_download_install_game(sock, current_user)
            elif c == "5":
                do_delete_installed_game(current_user)
            elif c == "6" and current_user:
                authenticated_menu()
            elif c == "0":
                sock.close()
                return
            else:
                print("Invalid")

    def authenticated_menu():
        nonlocal current_user, current_room
        while True:
            # If a game was launched while we were elsewhere, run it here.
            # After it exits, keep user at the authenticated home menu.
            _maybe_run_pending_launch()
            print(f"\n=== Hello, {current_user} ===")
            print("1. Create room")
            print("2. Join room")
            print("3. Invite user to your private room")
            print("4. Accept invite")
            print("5. List invites")
            print("6. Logout")
            print("0. Back")
            raw = _prompt_interruptible("Choice: ")
            if raw is None:
                _maybe_run_pending_launch()
                continue
            c = raw.strip()
            if c == "1":
                res = do_create_room(sock)
                if res and res.get("status") == "ok":
                    current_room = res.get("room_id")
                    room_actions_menu()
            elif c == "2":
                res = do_join_room(sock)
                if res and res.get("status") == "ok":
                    current_room = int(res.get("room_id") or current_room or 0) or None
                    room_actions_menu()
            elif c == "3":
                do_invite_user(sock)
            elif c == "4":
                do_accept_invite(sock)
            elif c == "5":
                do_list_invites(sock)
            elif c == "6":
                do_logout(sock)
                current_user = None
                return
            elif c == "0":
                # Return to Welcome without logging out.
                return
            else:
                print("Invalid")

    def room_actions_menu():
        nonlocal current_user, current_room
        while True:
            # If a game starts (push) while we are in a room, run it, then
            # return the user to the authenticated home menu.
            if _maybe_run_pending_launch():
                current_room = None
                return
            print("\n--- Room Actions ---")
            print("1. Start room game (as host)")
            print("2. Room Chat")
            print("3. Reviews")
            print("4. Invite user to this private room")
            print("5. List invites")
            print("6. Accept invite")
            print("0. Leave room")
            raw = _prompt_interruptible("Choice: ")
            if raw is None:
                if _maybe_run_pending_launch():
                    current_room = None
                    return
                continue
            c = raw.strip()
            if c == "1":
                if not current_room:
                    # fallback prompt
                    try:
                        rid_raw = _prompt_interruptible("Room ID: ")
                        if rid_raw is None:
                            if _maybe_run_pending_launch():
                                current_room = None
                                return
                            continue
                        current_room = int(rid_raw.strip())
                    except Exception:
                        print("Invalid room id")
                        continue
                started = do_start_game(sock, current_user, int(current_room))
                # Once we start the game, we leave the room-actions menu.
                if started:
                    return
            elif c == "2":
                room_chat_menu(sock)
            elif c == "3":
                review_menu(sock)
            elif c == "4":
                # Host inviting others to this (private) room.
                do_invite_user(sock, room_id=int(current_room) if current_room else None)
            elif c == "5":
                do_list_invites(sock)
            elif c == "6":
                do_accept_invite(sock)
            elif c == "0":
                return
            else:
                print("Invalid")

    initial_menu()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting")
        sys.exit(0)
