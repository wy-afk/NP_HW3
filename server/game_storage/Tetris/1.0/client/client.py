#!/usr/bin/env python3
import argparse
import socket
import select
import sys
import json
import time
import pygame
import threading
from proto import FramedSocket
from tetris_gui import GUI
from messages import *
from shapes import SHAPES

DEFAULT_TIMEOUT = 300.0


def run_gui(gs_host, gs_port, username, room_id):
    """
    Launch the Tetris GUI client connected to the given game server.
    Sends HELLO with user and roomId so the server can match/ready both sides.
    Includes a small retry to avoid connecting before the server has bound.
    """
    # small delay + retries to avoid race with freshly spawned game_server
    time.sleep(0.4)
    last_err = None
    for _ in range(12):  # ~3.6s max
        try:
            s = socket.create_connection((gs_host, gs_port))
            break
        except Exception as e:
            last_err = e
            time.sleep(0.3)
    else:
        raise ConnectionRefusedError(f"Could not connect to game server {gs_host}:{gs_port}: {last_err}")

    sock = FramedSocket(s)
    # IMPORTANT: include roomId in HELLO so game_server can pair both clients
    sock.send_json({"type": "HELLO", "user": username, "roomId": str(room_id)})
    gui = GUI(sock)
    gui.loop()
    s.close()
    return gui.last_result


def run_spectator(gs_host, gs_port, username):
    """
    Connect as a spectator to observe a game in real-time (read-only).
    """
    time.sleep(0.4)
    last_err = None
    for _ in range(12):
        try:
            s = socket.create_connection((gs_host, gs_port))
            break
        except Exception as e:
            last_err = e
            time.sleep(0.3)
    else:
        raise ConnectionRefusedError(f"Could not connect to game server {gs_host}:{gs_port}: {last_err}")

    sock = FramedSocket(s)
    sock.send_json({"type": "HELLO", "user": username, "spectator": True})
    gui = GUI(sock, spectator=True)
    gui.loop()
    s.close()
    return None


def lobby_loop(host, port):
    """
    Interactive lobby loop: handles user registration, login, room creation, joining, and starting games.
    """
    fsock = socket.create_connection((host, port))
    fsock.setblocking(False)
    print("Connected to Lobby. Please register or login.")
    state = {"user": None, "game_running": False}

    prompt = "» "
    print(prompt, end="", flush=True)

    buffer = b""

    while True:
        r, _, _ = select.select([fsock, sys.stdin], [], [], 0.2)
        for src in r:
            # Handle server messages
            if src == fsock:
                try:
                    data = fsock.recv(4096)
                    if not data:
                        print("\n[RX] disconnected.")
                        return
                    buffer += data

                    # Lobby is line-oriented; process complete lines
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        msg = line.decode(errors="ignore").strip()
                        if not msg:
                            continue

                        print(f"\r{msg}\n{prompt}", end="", flush=True)

                        # Auto-launch GUI if a game is announced
                        # Expect something like: >> {"game": {"host":"...","port":12345,"roomId":"1"}}
                        if '"game"' in msg and not state["game_running"]:
                            # extract JSON after the ">> " prefix if present
                            try:
                                json_part = msg
                                if ">> " in msg:
                                    json_part = msg.split(">> ", 1)[1]
                                js = json.loads(json_part)
                                g = js["game"]
                                host_fix = g["host"] if g["host"] != "0.0.0.0" else "127.0.0.1"
                                room_id = g.get("roomId")
                                print(f"\nConnected to game server; waiting for opponent to join...")
                                state["game_running"] = True

                                result = run_gui(host_fix, g["port"], state["user"], room_id)

                                # Print local outcome, ask for replay (we don't auto-rematch anymore)
                                if isinstance(result, dict) and "winners" in result:
                                    won = state["user"] in result.get("winners", [])
                                    print(f">>> You {'WIN 🎉' if won else 'LOSE'}")
                                    choice = input("Play again? (y/n) ").strip().lower()
                                    if choice == "y":
                                        print("Back to lobby. Use `create_room` / `join <roomId>` to start a new match.")
                                    else:
                                        print("Back to lobby. Use `create_room` / `join <roomId>` to start a new match.")

                                state["game_running"] = False
                                print(prompt, end="", flush=True)
                            except Exception as e:
                                print(f"[Client] Game launch error: {e}")
                                state["game_running"] = False
                                print(prompt, end="", flush=True)
                        # Auto-launch spectator GUI when lobby returns spectate info
                        if '"spectate"' in msg and not state["game_running"]:
                            try:
                                json_part = msg
                                if ":: " in msg:
                                    json_part = msg.split(":: ", 1)[1]
                                if "-> " in msg:
                                    json_part = msg.split("-> ", 1)[1]
                                if ">> " in msg:
                                    json_part = msg.split(">> ", 1)[1]
                                js = json.loads(json_part)
                                s = js.get("spectate")
                                if s:
                                    host_fix = s["host"] if s["host"] != "0.0.0.0" else "127.0.0.1"
                                    port = s.get("port")
                                    print(f"Connecting as spectator to {host_fix}:{port} (room {s.get('roomId')})...")
                                    state["game_running"] = True
                                    run_spectator(host_fix, port, state.get("user", "spectator"))
                                    state["game_running"] = False
                                    print(prompt, end="", flush=True)
                            except Exception as e:
                                print(f"[Client] Spectate launch error: {e}")
                                state["game_running"] = False
                                print(prompt, end="", flush=True)

                except Exception as e:
                    print("\n[RX] disconnected or error:", e)
                    return

            # Handle user input
            elif src == sys.stdin:
                line = sys.stdin.readline()
                if not line:
                    return
                cmdline = line.strip()
                if cmdline == "":
                    print(prompt, end="", flush=True)
                    continue

                toks = cmdline.split()
                cmd = toks[0]

                # Simple local commands
                if cmd == "quit":
                    fsock.sendall((cmdline + "\n").encode())
                    print("Exiting...")
                    return

                elif cmd == "login" and len(toks) == 3:
                    # Let client update current username locally
                    state["user"] = toks[1]

                # ⬇⬇⬇ ONLY THIS WHITELIST IS MODIFIED ⬇⬇⬇
                elif cmd not in (
                    "register", "login", "logout",
                    "create_room", "list_rooms", "list_online",
                    "list_top", "join", "start_game",
                    "my_stats", "whoami", "help",

                    # --- Newly added commands for private-room logic ---
                    "invite",            # host invites another user
                    "accept_invite",     # invited player accepts
                    "revoke_invite",     # host removes an invite
                    "list_invites",      # list received invites
                    "leave",             # leave lobby or room

                    # --- Spectator mode ---
                    "spectate",          # spectate a room
                    "list_spectatable"   # list rooms available to spectate
                ):
                    # If command is not recognized locally → reject
                    print("Unknown or bad args. Type 'help'.")
                    print(prompt, end="", flush=True)
                    continue
                # ⬆⬆⬆ END OF MODIFIED PART ⬆⬆⬆

                # If command passed validation → SEND IT TO SERVER
                try:
                    fsock.sendall((cmdline + "\n").encode())
                except Exception as e:
                    print(f"[ERR] failed sending command: {e}")
                    return

def run_client(gs_host, gs_port, username, room_id):
    """
    Simple entry point for HW3 game launcher (not the HW2 lobby).
    This wraps the existing run_gui() so the HW3 platform can launch Tetris directly.
    """
    return run_gui(gs_host, gs_port, username, room_id)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["lobby", "spectate"], help="Mode: lobby or spectate")
    ap.add_argument("--lobby-host", default="127.0.0.1")
    ap.add_argument("--lobby-port", type=int, default=12000)
    ap.add_argument("--gs-host", default="127.0.0.1")
    ap.add_argument("--gs-port", type=int, default=11000)
    ap.add_argument("--user")
    args = ap.parse_args()

    if args.mode == "lobby":
        lobby_loop(args.lobby_host, args.lobby_port)
    elif args.mode == "spectate":
        if not args.gs_host or not args.gs_port or not args.user:
            print("Error: --gs-host, --gs-port, and --user required for spectate mode")
            sys.exit(1)
        run_spectator(args.gs_host, args.gs_port, args.user)
