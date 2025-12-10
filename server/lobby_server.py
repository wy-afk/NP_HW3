# server/lobby_server.py
import socket
import threading

from account_manager import AccountManager
from store_manager import StoreManager
from room_manager import RoomManager
from utils.protocol import send, recv

HOST = "0.0.0.0"
PORT = 5555


class LobbyServer:
    def __init__(self):
        self.accounts = AccountManager()
        self.store = StoreManager()
        self.rooms = RoomManager()

    # ---------- per-client handler ----------

    def handle_client(self, conn: socket.socket, addr):
        print(f"[CONNECTED] {addr}")
        username = None  # track logged-in user for logout

        try:
            while True:
                msg = recv(conn)
                if msg is None:
                    break  # client closed connection

                action = msg.get("action")
                data = msg.get("data", {})
                print(f"[RECV] {addr} action={action} data={data}")

                resp = {"status": "error", "action": action, "data": {}}

                # ---------- account actions ----------
                if action == "register":
                    ok, reason = self.accounts.register(
                        data.get("username", ""),
                        data.get("password", ""),
                        data.get("role", ""),
                    )
                    resp["status"] = "ok" if ok else "error"
                    resp["data"] = {"reason": reason}

                elif action == "login":
                    ok, reason = self.accounts.login(
                        data.get("username", ""),
                        data.get("password", ""),
                        data.get("role", ""),
                    )
                    if ok:
                        username = data.get("username")
                    resp["status"] = "ok" if ok else "error"
                    resp["data"] = {"reason": reason}

                elif action == "logout":
                    if username:
                        self.accounts.logout(username)
                        username = None
                    resp["status"] = "ok"

                elif action == "list_online":
                    role = data.get("role")  # optional
                    users = self.accounts.get_online_users(role)
                    resp["status"] = "ok"
                    resp["data"] = {"users": users}

                # ---------- store actions ----------
                elif action == "list_games":
                    games = self.store.list_games()
                    resp["status"] = "ok"
                    resp["data"] = {"games": games}

                elif action == "register_game":
                    # For now: simple registration; later tie to upload flow
                    if not username:
                        resp["data"] = {"reason": "not_logged_in"}
                    else:
                        game = self.store.register_game(
                            name=data.get("name", ""),
                            version=data.get("version", "1.0"),
                            developer=username,
                            path=data.get("path", ""),
                            description=data.get("description", ""),
                        )
                        resp["status"] = "ok"
                        resp["data"] = {"game": game}

                # ---------- room actions ----------
                elif action == "list_rooms":
                    rooms = self.rooms.list_rooms()
                    resp["status"] = "ok"
                    resp["data"] = {"rooms": rooms}

                elif action == "create_room":
                    if not username:
                        resp["data"] = {"reason": "not_logged_in"}
                    else:
                        game_id = data.get("game_id")
                        room = self.rooms.create_room(username, game_id)
                        resp["status"] = "ok"
                        resp["data"] = {"room": room}

                elif action == "join_room":
                    if not username:
                        resp["data"] = {"reason": "not_logged_in"}
                    else:
                        room_id = data.get("room_id")
                        room = self.rooms.join_room(room_id, username)
                        if room:
                            resp["status"] = "ok"
                            resp["data"] = {"room": room}
                        else:
                            resp["data"] = {"reason": "room_not_found"}

                elif action == "start_game":
                    # Only host should call this (you can enforce later)
                    room_id = data.get("room_id")
                    room = self.rooms.start_game(room_id)
                    if room:
                        resp["status"] = "ok"
                        resp["data"] = {
                            "room_id": room["room_id"],
                            "game_port": room["port"],
                        }
                    else:
                        resp["data"] = {"reason": "room_not_found"}

                else:
                    resp["data"] = {"reason": "unknown_action"}

                send(conn, resp)

        except Exception as e:
            print(f"[ERROR] {addr}: {e}")

        finally:
            if username:
                self.accounts.logout(username)
            conn.close()
            print(f"[DISCONNECTED] {addr}")

    # ---------- server loop ----------

    def start(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((HOST, PORT))
        srv.listen()
        print(f"[LOBBY SERVER] Listening on {HOST}:{PORT}")

        while True:
            conn, addr = srv.accept()
            t = threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True)
            t.start()


if __name__ == "__main__":
    LobbyServer().start()
