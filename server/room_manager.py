# server/room_manager.py
from typing import Dict, List, Optional
from game_launcher import GameLauncher


class RoomManager:
    """
    Manages lobby rooms and launches game servers.
    Room structure:
    {
        "room_id": int,
        "host": str,
        "game_id": int,
        "players": [str],
        "status": "waiting" | "in_game",
        "port": int | None,
        "proc": subprocess.Popen | None
    }
    """

    def __init__(self, store_manager=None):
        self.rooms: Dict[int, dict] = {}
        self._next_room_id = 1

        # store_manager reference will be provided by LobbyServer
        self.store = store_manager

        # game launcher handles actual subprocess starting
        self.launcher = GameLauncher()

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------
    def _new_room_id(self) -> int:
        rid = self._next_room_id
        self._next_room_id += 1
        return rid

    def attach_store_manager(self, store_manager):
        """Called by LobbyServer so RoomManager can fetch game metadata."""
        self.store = store_manager

    # ----------------------------------------------------------------------
    # Room list
    # ----------------------------------------------------------------------
    def list_rooms(self) -> List[dict]:
        return list(self.rooms.values())

    # ----------------------------------------------------------------------
    # Create a new room
    # ----------------------------------------------------------------------
    def create_room(self, host: str, game_id: int) -> dict:
        room_id = self._new_room_id()
        room = {
            "room_id": room_id,
            "host": host,
            "game_id": game_id,
            "players": [host],
            "status": "waiting",
            "port": None,
            "proc": None
        }

        self.rooms[room_id] = room
        print(f"[RoomManager] Created room {room_id} for game {game_id}.")
        return room

    # ----------------------------------------------------------------------
    # Join an existing room
    # ----------------------------------------------------------------------
    def join_room(self, room_id: int, username: str) -> Optional[dict]:
        room = self.rooms.get(room_id)
        if not room:
            print(f"[RoomManager] join_room failed: room {room_id} not found.")
            return None

        if room["status"] != "waiting":
            print(f"[RoomManager] join_room failed: room {room_id} already started.")
            return None

        if username not in room["players"]:
            room["players"].append(username)
            print(f"[RoomManager] {username} joined room {room_id}.")

        return room

    # ----------------------------------------------------------------------
    # Start game (host triggers this)
    # ----------------------------------------------------------------------
    def start_game(self, room_id: int) -> Optional[dict]:
        room = self.rooms.get(room_id)
        if not room:
            print(f"[RoomManager] start_game failed: no room {room_id}.")
            return None

        if room["status"] == "in_game":
            return room

        # get the correct game metadata
        if not self.store:
            raise RuntimeError("RoomManager has no store_manager attached.")

        game = self.store.get_game(room["game_id"])
        if not game:
            print(f"[RoomManager] start_game failed: unknown game_id {room['game_id']}.")
            return None

        # launch the game server
        port, proc = self.launcher.launch_game_server(game, room_id)

        room["status"] = "in_game"
        room["port"] = port
        room["proc"] = proc

        print(f"[RoomManager] Room {room_id} started game on port {port}.")
        return room

    # ----------------------------------------------------------------------
    # End game + cleanup room
    # ----------------------------------------------------------------------
    def end_game(self, room_id: int):
        room = self.rooms.get(room_id)
        if not room:
            print(f"[RoomManager] end_game: room {room_id} not found.")
            return

        # terminate server process
        proc = room.get("proc")
        self.launcher.stop_game_server(proc)

        print(f"[RoomManager] Closing room {room_id}.")
        self.rooms.pop(room_id, None)

    # ----------------------------------------------------------------------
    # Remove all rooms if server shuts down
    # ----------------------------------------------------------------------
    def cleanup(self):
        for room_id, room in list(self.rooms.items()):
            proc = room.get("proc")
            self.launcher.stop_game_server(proc)
        self.rooms.clear()
