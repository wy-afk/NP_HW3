# server/lobby_server.py
import socket
import threading
import json
import time

from utils.protocol import send, recv
from room_manager import RoomManager
from game_launcher import GameLauncher
from account_manager import AccountManager


class LobbyServer:

    def __init__(self, host="0.0.0.0", port=5555):
        self.host = host
        self.port = port

        self.accounts = AccountManager()
        self.games = {
            1: {"name": "Battleship", "version": "1.0", "path": "server/game_storage/Battleship/1.0"},
            2: {"name": "Tetris", "version": "1.0", "path": "server/game_storage/Tetris/1.0"},
        }

        self.rooms = RoomManager()
        self.rooms.attach_launcher(GameLauncher(games=self.games))
        # active client connections identified by username (for push notifications)
        # support multiple sockets per username (main + monitor)
        self.clients: dict[str, list] = {}
        # separate registry for monitor sockets (identified by client role)
        self.monitors: dict[str, list] = {}

    def _add_client_conn(self, username: str, conn):
        lst = self.clients.setdefault(username, [])
        if conn not in lst:
            lst.append(conn)

    def _add_monitor_conn(self, username: str, conn):
        lst = self.monitors.setdefault(username, [])
        if conn not in lst:
            lst.append(conn)

    def _remove_client_conn(self, username: str, conn):
        lst = self.clients.get(username)
        if not lst:
            return
        try:
            if conn in lst:
                lst.remove(conn)
        except Exception:
            pass
        if not lst:
            self.clients.pop(username, None)
        # also try removing from monitors if present
        mlist = self.monitors.get(username)
        if mlist:
            try:
                if conn in mlist:
                    mlist.remove(conn)
            except Exception:
                pass
            if not mlist:
                self.monitors.pop(username, None)

    def _remove_monitor_conn(self, username: str, conn):
        mlist = self.monitors.get(username)
        if not mlist:
            return
        try:
            if conn in mlist:
                mlist.remove(conn)
        except Exception:
            pass
        if not mlist:
            self.monitors.pop(username, None)

    # ======================================================
    def start(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen()

        print(f"[LOBBY SERVER] Listening on {self.host}:{self.port}")

        while True:
            conn, addr = srv.accept()
            print(f"[CONNECTED] {addr}")
            threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()

    # ======================================================
    def handle_client(self, conn, addr):
        user = None

        try:
            while True:
                msg = recv(conn)
                if msg is None:
                    break

                action = msg.get("action")
                data = msg.get("data", {})

                if action == "register":
                    out = self.register(data)
                elif action == "login":
                    out, new_user = self.login(data)
                    # if login succeeded, record this main connection so the
                    # server can push notifications to the client's socket.
                    # Do NOT clear an existing connection-level `user` on a
                    # failed login attempt (otherwise a bad login would
                    # accidentally log the session out).
                    if new_user and out.get("status") == "ok":
                        user = new_user
                        try:
                            self._add_client_conn(user, conn)
                        except Exception:
                            pass
                elif action == "whoami":
                    # return the username associated with this connection
                    if user:
                        out = {"status": "ok", "user": user}
                    else:
                        out = {"status": "error", "msg": "not_logged_in"}
                elif action == "list_online":
                    # return list of currently connected players
                    names = self.accounts.get_online_users(role="player")
                    out = {"status": "ok", "data": {"online": names}}
                elif action == "logout":
                    out = self.logout(user)
                    # remove this connection mapping for explicit logout
                    try:
                        if user:
                            self._remove_client_conn(user, conn)
                    except Exception:
                        pass
                    # clear local user state for this connection
                    user = None
                elif action == "identify":
                    # lightweight identification for monitor sockets so server can
                    # push notifications to this conn for the given username.
                    uname = data.get("username")
                    role = data.get("role")
                    if uname:
                        try:
                            # monitors should register separately so pushes go to them
                            if role == "monitor":
                                self._add_monitor_conn(uname, conn)
                            else:
                                self._add_client_conn(uname, conn)
                        except Exception:
                            pass
                        out = {"status": "ok"}
                    else:
                        out = {"status": "error", "msg": "missing_username"}
                elif action == "list_games":
                    out = self.list_games()
                elif action == "record_result":
                    # External game servers can report finished match results
                    data = data or {}
                    winners = data.get("winners", [])
                    players = data.get("players", [])
                    try:
                        print(f"[RECORD] Received result report: winners={winners} players={players}")
                        self.accounts.record_result(winners, players)
                        print(f"[RECORD] Updated player stats and persisted to disk")
                        out = {"status": "ok"}
                    except Exception as e:
                        out = {"status": "error", "msg": str(e)}
                elif action == "my_stats":
                    # Return stats for the currently-identified user
                    out = self.my_stats(user)
                elif action == "resume":
                    # Re-associate this connection with a previously-known username
                    uname = data.get("username")
                    if not uname:
                        out = {"status": "error", "msg": "missing_username"}
                    else:
                        # Only allow resume if the username exists in players
                        if uname not in self.accounts.players:
                            out = {"status": "error", "msg": "user_not_found"}
                        else:
                            user = uname
                            # mark connected in account manager
                            try:
                                self.accounts.online_users[uname] = {"role": "player", "connected": True, "last_seen": time.time()}
                            except Exception:
                                pass
                            try:
                                self._add_client_conn(uname, conn)
                            except Exception:
                                pass
                            out = {"status": "ok", "user": uname}
                elif action == "leaderboard":
                    out = self.leaderboard()
                elif action == "list_rooms":
                    out = {"status": "ok", "data": {"rooms": self.rooms.list_rooms()}}
                elif action == "create_room":
                    out = self.create_room(user, data)
                elif action == "join_room":
                    out = self.join_room(user, data)
                elif action == "invite_user":
                    # host invites another user to a private room
                    if not user:
                        out = {"status": "error", "msg": "Not logged in"}
                    else:
                        room_id = data.get("room_id")
                        target = data.get("target")
                        ok, msg = self.rooms.invite_user(room_id, user, target)
                        out = {"status": "ok", "msg": msg} if ok else {"status": "error", "msg": msg}
                elif action == "list_invites":
                    if not user:
                        out = {"status": "error", "msg": "Not logged in"}
                    else:
                        invites = self.rooms.list_invites_for(user)
                        out = {"status": "ok", "data": {"invites": invites}}
                elif action == "accept_invite":
                    if not user:
                        out = {"status": "error", "msg": "Not logged in"}
                    else:
                        room_id = data.get("room_id")
                        ok, msg = self.rooms.accept_invite(room_id, user)
                        out = {"status": "ok", "msg": msg} if ok else {"status": "error", "msg": msg}
                elif action == "revoke_invite":
                    if not user:
                        out = {"status": "error", "msg": "Not logged in"}
                    else:
                        room_id = data.get("room_id")
                        target = data.get("target")
                        ok, msg = self.rooms.revoke_invite(room_id, user, target)
                        out = {"status": "ok", "msg": msg} if ok else {"status": "error", "msg": msg}
                elif action == "start_game":
                    out = self.start_game(user, data)
                else:
                    out = {"status": "error", "msg": "Unknown action"}

                send(conn, out)

        except Exception as e:
            print("[ERROR]", e)
        finally:
            # Mark disconnected on socket close; account manager will keep the
            # session for a short grace period before fully removing it. This
            # avoids immediate logout for brief client-side disconnects (e.g.
            # launching an interactive local game).
            if user:
                try:
                    self.accounts.mark_disconnected(user)
                    print(f"[DISCONNECT] {user} connection closed (marked disconnected)")
                except Exception:
                    # fallback to hard logout
                    self.accounts.logout(user)
                    print(f"[LOGOUT] {user} disconnected (forced)")
                # remove only this connection mapping for the user so other
                # sockets (monitor/main) remain attached.
                try:
                    self._remove_client_conn(user, conn)
                except Exception:
                    pass
            conn.close()

    # ======================================================
    def register(self, data):
        username = data.get("username", "")
        password = data.get("password", "")
        role = data.get("role", "player")
        
        ok, reason = self.accounts.register(username, password, role)
        if ok:
            return {"status": "ok", "msg": reason}
        else:
            return {"status": "error", "msg": reason}

    # ======================================================
    def login(self, data):
        username = data.get("username", "")
        password = data.get("password", "")
        role = data.get("role", "player")

        ok, reason = self.accounts.login(username, password, role)
        if ok:
            # include basic stats in the login response
            info = self.accounts.players.get(username, {})
            wins = int(info.get("wins", 0)) if isinstance(info.get("wins", 0), (int, str)) else 0
            played = int(info.get("played", 0)) if isinstance(info.get("played", 0), (int, str)) else 0
            return {"status": "ok", "user": username, "data": {"username": username, "wins": wins, "played": played}}, username
        else:
            return {"status": "error", "msg": reason}, None

    # ======================================================
    def logout(self, user):
        if user:
            self.accounts.logout(user)
            print(f"[LOGOUT] {user} logged out")
        return {"status": "ok"}

    # ======================================================
    def list_games(self):
        return {"status": "ok", "games": self.games}

    # ======================================================
    def leaderboard(self):
        # Prefer the cached leaderboard JSON (written on each result); fall back
        # to computing from the players store if missing or unreadable.
        try:
            lb = self.accounts.get_leaderboard()
            return {"status": "ok", "leaderboard": lb}
        except Exception:
            # Fallback to a safe compute
            players = self.accounts.players or {}
            rows = []
            for uname, info in players.items():
                wins = int(info.get("wins", 0)) if isinstance(info.get("wins", 0), (int, str)) else 0
                played = int(info.get("played", 0)) if isinstance(info.get("played", 0), (int, str)) else 0
                rows.append({"username": uname, "wins": wins, "played": played})

            rows.sort(key=lambda r: (-r["wins"], r["played"], r["username"]))
            leaderboard = []
            last_wins = None
            rank = 0
            for idx, r in enumerate(rows, start=1):
                if r["wins"] != last_wins:
                    rank = idx
                    last_wins = r["wins"]
                entry = {"rank": rank, "username": r["username"], "wins": r["wins"], "played": r["played"]}
                leaderboard.append(entry)
            return {"status": "ok", "leaderboard": leaderboard}

    # ======================================================
    def my_stats(self, username: str):
        if not username:
            return {"status": "error", "msg": "not_logged_in"}
        info = self.accounts.players.get(username) or {}
        wins = int(info.get("wins", 0)) if isinstance(info.get("wins", 0), (int, str)) else 0
        played = int(info.get("played", 0)) if isinstance(info.get("played", 0), (int, str)) else 0
        return {"status": "ok", "data": {"username": username, "wins": wins, "played": played}}

    # ======================================================
    def create_room(self, user, data):
        if not user:
            return {"status": "error", "msg": "Not logged in"}

        game_id = data["game_id"]
        room_type = data.get("type", "public")

        room = self.rooms.create_room(game_id, user, room_type)

        return {"status": "ok", "room_id": room.room_id, "type": room.type}

    # ======================================================
    def join_room(self, user, data):
        if not user:
            return {"status": "error", "msg": "Not logged in"}

        room_id = data["room_id"]
        ok, msg = self.rooms.join_room(room_id, user)

        if not ok:
            return {"status": "error", "msg": msg}

        return {"status": "ok", "msg": msg}

    # ======================================================
    def start_game(self, user, data):
        room_id = data["room_id"]

        room = self.rooms.rooms.get(room_id)
        if room is None:
            return {"status": "error", "msg": "Room not found"}

        if room.host != user:
            return {"status": "error", "msg": "Only host can start game"}

        ok, result = self.rooms.start_game(room_id)

        if not ok:
            return {"status": "error", "msg": result}

        out = {"status": "ok", "data": {"room_id": room_id, "port": result}}

        # Notify other connected clients that the game has started so their
        # monitor threads (or identified sockets) can immediately launch clients.
        notify = {"action": "game_started", "data": {"room_id": room_id, "port": result}}
        for p in room.players:
            try:
                # Prefer monitor sockets for pushing notifications
                conns = self.monitors.get(p) or self.clients.get(p) or []
                if p == user:
                    # skip notifying host
                    continue
                print(f"[NOTIFY] Preparing to notify user '{p}' on {len(conns)} conn(s)")
                for idx, c in enumerate(conns):
                    try:
                        send(c, notify)
                        print(f"[NOTIFY] Sent game_started to '{p}' conn #{idx}")
                    except Exception as e:
                        print(f"[NOTIFY] Failed to send to '{p}' conn #{idx}: {e}")
                        try:
                            # Remove the dead connection so future notifies don't hit it
                            # Try removing from monitors first, then general clients
                            try:
                                self._remove_monitor_conn(p, c)
                                print(f"[NOTIFY] Removed dead monitor conn #{idx} for user '{p}'")
                            except Exception:
                                self._remove_client_conn(p, c)
                                print(f"[NOTIFY] Removed dead client conn #{idx} for user '{p}'")
                        except Exception:
                            pass
            except Exception as e:
                print(f"[NOTIFY] Error preparing notify for '{p}': {e}")

        return out


if __name__ == "__main__":
    server = LobbyServer()
    server.start()
