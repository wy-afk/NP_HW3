# server/room_manager.py
from typing import Dict, List, Optional
from game_launcher import GameLauncher


class RoomManager:
    """
    In-memory room management.
    For HW3 scale, keeping everything in RAM is fine.
    """

    def __init__(self):
        # room_id -> room dict
        self.rooms: Dict[int, dict] = {}
        self._next_room_id = 1
        self.launcher = GameLauncher()

    # ---------- helpers ----------

    def _new_room_id(self) -> int:
        rid = self._next_room_id
        self._next_room_id += 1
        return rid

    # ---------- API ----------

    def list_rooms(self) -> List[dict]:
        return list(self.rooms.values())

    def create_room(self, host: str, game_id: int) -> dict:
        room_id = self._new_room_id()
        room = {
            "room_id": room_id,
            "host": host,
            "game_id": game_id,
            "players": [host],
            "status": "waiting",  # waiting | in_game
            "port": None,
        }
        self.rooms[room_id] = room
        return room

    def join_room(self, room_id: int, username: str) -> Optional[dict]:
        room = self.rooms.get(room_id)
        if not room:
            return None
        if username in room["players"]:
            return room
        room["players"].append(username)
        return room

    def start_game(self, room_id: int) -> Optional[dict]:
        """
        Called when host presses "Start".
        Launches game server and returns connection info.
        """
        room = self.rooms.get(room_id)
        if not room:
            return None
        if room["status"] == "in_game":
            return room

        port, proc = self.launcher.launch_game_server(room["game_id"], room["room_id"])
        room["status"] = "in_game"
        room["port"] = port
        room["proc"] = proc  # may be used later for cleanup
        return room

    def end_game(self, room_id: int):
        room = self.rooms.get(room_id)
        if not room:
            return
        # optional: kill process here via launcher
        self.launcher.stop_game_server(room.get("proc"))
        # remove room entirely after game
        self.rooms.pop(room_id, None)
