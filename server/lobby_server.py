# server/lobby_server.py
import socket
import threading
import json

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
                    out, user = self.login(data)
                elif action == "logout":
                    out = self.logout(user)
                elif action == "list_games":
                    out = self.list_games()
                elif action == "list_rooms":
                    out = {"status": "ok", "data": {"rooms": self.rooms.list_rooms()}}
                elif action == "create_room":
                    out = self.create_room(user, data)
                elif action == "join_room":
                    out = self.join_room(user, data)
                elif action == "start_game":
                    out = self.start_game(user, data)
                else:
                    out = {"status": "error", "msg": "Unknown action"}

                send(conn, out)

        except Exception as e:
            print("[ERROR]", e)
        finally:
            # Auto-logout on disconnect
            if user:
                self.accounts.logout(user)
                print(f"[LOGOUT] {user} disconnected")
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
            return {"status": "ok", "user": username}, username
        else:
            return {"status": "error", "msg": reason}, None

    # ======================================================
    def logout(self, user):
        if user and user in self.users:
            self.users[user]["logged_in"] = False
        return {"status": "ok"}

    # ======================================================
    def list_games(self):
        return {"status": "ok", "games": self.games}

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

        return {"status": "ok", "data": {"room_id": room_id, "port": result}}


if __name__ == "__main__":
    server = LobbyServer()
    server.start()
