import socket
import threading
import os
import json
import zipfile
from pathlib import Path

from account_manager import AccountManager
from store_manager import StoreManager
from room_manager import RoomManager
from utils.protocol import send, recv
from file_transfer import recv_file, unzip_file


HOST = "0.0.0.0"
PORT = 5555


class LobbyServer:
    def __init__(self):
        # Core modules
        self.accounts = AccountManager()
        self.store = StoreManager()
        self.rooms = RoomManager()

        # Allow RoomManager to use StoreManager (IMPORTANT)
        self.rooms.attach_store_manager(self.store)

        # Holds temporary upload metadata
        self.pending_upload = None

    # ----------------------------------------------
    # Handle an individual client connection
    # ----------------------------------------------
    def handle_client(self, conn: socket.socket, addr):
        print(f"[CONNECTED] {addr}")
        username = None

        try:
            while True:
                msg = recv(conn)
                if msg is None:
                    break

                action = msg.get("action")
                data = msg.get("data", {})
                print(f"[RECV] {addr} action={action} data={data}")

                resp = {"status": "error", "action": action, "data": {}}

                # =======================================================
                # ACCOUNT ACTIONS
                # =======================================================
                if action == "register":
                    ok, reason = self.accounts.register(
                        data.get("username", ""),
                        data.get("password", ""),
                        data.get("role", "")
                    )
                    resp["status"] = "ok" if ok else "error"
                    resp["data"] = {"reason": reason}

                elif action == "login":
                    ok, reason = self.accounts.login(
                        data.get("username", ""),
                        data.get("password", ""),
                        data.get("role", "")
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

                # =======================================================
                # GAME STORE: LIST GAMES
                # =======================================================
                elif action == "list_games":
                    resp["status"] = "ok"
                    resp["data"] = {"games": self.store.list_games()}

                # =======================================================
                # GAME STORE: DEVELOPER REGISTER GAME METADATA
                # =======================================================
                elif action == "register_game":
                    if not username:
                        resp["data"] = {"reason": "not_logged_in"}
                    else:
                        game = self.store.register_game(
                            name=data.get("name", ""),
                            version=data.get("version", "1.0"),
                            developer=username,
                            path=data.get("path", ""),
                            description=data.get("description", "")
                        )
                        resp["status"] = "ok"
                        resp["data"] = {"game": game}

                # =======================================================
                # UPLOAD (PHASE 1): META INFORMATION
                # =======================================================
                elif action == "upload_game_meta":
                    if not username:
                        resp["data"] = {"reason": "not_logged_in"}
                    else:
                        name = data["name"]
                        version = data["version"]

                        storage_dir = Path("server/game_storage") / name / version
                        zip_path = str(storage_dir) + ".zip"

                        os.makedirs(storage_dir.parent, exist_ok=True)

                        self.pending_upload = {
                            "zip_path": zip_path,
                            "extract_path": str(storage_dir),
                            "name": name,
                            "version": version,
                            "developer": username
                        }

                        resp["status"] = "ok"
                        resp["data"] = {
                            "zip_path": zip_path,
                            "extract_path": str(storage_dir)
                        }

                # =======================================================
                # UPLOAD (PHASE 2): RECEIVE FILE CONTENTS
                # =======================================================
                elif action == "upload_game_file":
                    info = self.pending_upload
                    if not info:
                        resp["data"] = {"reason": "no_pending_upload"}
                    else:
                        # receive file size
                        header = conn.recv(8)
                        filesize = int.from_bytes(header, 'big')

                        # receive raw bytes into zip file
                        recv_file(conn, info["zip_path"], filesize)

                        # unzip to permanent folder
                        unzip_file(info["zip_path"], info["extract_path"])

                        # register new game/version
                        game = self.store.register_game(
                            name=info["name"],
                            version=info["version"],
                            developer=info["developer"],
                            path=info["extract_path"],
                            description=f"{info['name']} version {info['version']}"
                        )

                        resp["status"] = "ok"
                        resp["data"] = {"game": game}

                        self.pending_upload = None

                # =======================================================
                # DOWNLOAD GAME (Player)
                # =======================================================
                elif action == "download_game_meta":
                    game_id = data["game_id"]
                    game = self.store.get_game(game_id)

                    if not game:
                        resp["data"] = {"reason": "game_not_found"}
                        send(conn, resp)
                        continue

                    folder = game["path"]
                    zip_path = f"/tmp/game_{game_id}.zip"

                    # zip game folder
                    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                        for root, dirs, files in os.walk(folder):
                            for f in files:
                                full = os.path.join(root, f)
                                arc = os.path.relpath(full, folder)
                                z.write(full, arc)

                    filesize = os.path.getsize(zip_path)

                    # send meta info
                    resp["status"] = "ok"
                    resp["data"] = {
                        "filename": f"game_{game_id}.zip",
                        "filesize": filesize,
                        "name": game["name"],
                        "version": game["version"]
                    }
                    send(conn, resp)

                    # send file binary
                    conn.sendall(filesize.to_bytes(8, 'big'))
                    with open(zip_path, "rb") as f:
                        conn.sendall(f.read())

                    continue

                # =======================================================
                # ROOMS: LIST
                # =======================================================
                elif action == "list_rooms":
                    resp["status"] = "ok"
                    resp["data"] = {"rooms": self.rooms.list_rooms()}

                # =======================================================
                # ROOMS: CREATE
                # =======================================================
                elif action == "create_room":
                    if not username:
                        resp["data"] = {"reason": "not_logged_in"}
                    else:
                        room = self.rooms.create_room(username, data["game_id"])
                        resp["status"] = "ok"
                        resp["data"] = {"room": room}

                # =======================================================
                # ROOMS: JOIN
                # =======================================================
                elif action == "join_room":
                    if not username:
                        resp["data"] = {"reason": "not_logged_in"}
                    else:
                        room = self.rooms.join_room(data["room_id"], username)
                        if room:
                            resp["status"] = "ok"
                            resp["data"] = {"room": room}
                        else:
                            resp["data"] = {"reason": "room_not_found"}

                # =======================================================
                # ROOMS: START GAME
                # =======================================================
                elif action == "start_game":
                    room = self.rooms.start_game(data["room_id"])
                    if room:
                        resp["status"] = "ok"
                        resp["data"] = {
                            "room_id": room["room_id"],
                            "game_port": room["port"]
                        }
                    else:
                        resp["data"] = {"reason": "room_not_found"}

                # =======================================================
                # UNKNOWN ACTION
                # =======================================================
                else:
                    resp["data"] = {"reason": "unknown_action"}

                send(conn, resp)

        except Exception as e:
            print(f"[ERROR] {addr}: {e}")

        finally:
            # Cleanly logout user
            if username:
                self.accounts.logout(username)

            conn.close()
            print(f"[DISCONNECTED] {addr}")

    # ----------------------------------------------
    # Main server loop
    # ----------------------------------------------
    def start(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((HOST, PORT))
        srv.listen()

        print(f"[LOBBY SERVER] Listening on {HOST}:{PORT}")

        while True:
            conn, addr = srv.accept()
            threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    LobbyServer().start()
