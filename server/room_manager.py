# server/room_manager.py
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class Room:
    room_id: int
    game_id: int
    host: str
    type: str  # "public" or "private"
    players: list = field(default_factory=list)
    status: str = "waiting"  # waiting / running
    port: Optional[int] = None


class RoomManager:

    def __init__(self):
        self.rooms: Dict[int, Room] = {}
        self.next_room_id = 1
        self.launcher = None

    def attach_launcher(self, launcher):
        self.launcher = launcher

    # -------------------------------------------------------
    # Create room
    # -------------------------------------------------------
    def create_room(self, game_id: int, username: str, room_type: str):
        room_id = self.next_room_id
        self.next_room_id += 1

        room = Room(room_id, game_id, username, room_type)
        room.players.append(username)  # host joins automatically

        self.rooms[room_id] = room
        return room

    # -------------------------------------------------------
    # Join room
    # -------------------------------------------------------
    def join_room(self, room_id: int, username: str):
        if room_id not in self.rooms:
            return False, "Room does not exist."

        room = self.rooms[room_id]

        if room.status != "waiting":
            return False, "Room already started."

        if len(room.players) >= 2:
            return False, "Room already full (2 players)."

        # PRIVATE ROOM RULE: ONLY HOST CAN JOIN
        if room.type == "private" and username != room.host:
            return False, "This is a private room. Only the host may join."

        # PUBLIC ROOM: anyone can join
        room.players.append(username)
        return True, f"{username} joined room {room_id}"

    # -------------------------------------------------------
    # Start game
    # -------------------------------------------------------
    def start_game(self, room_id: int):
        if room_id not in self.rooms:
            return False, "Room does not exist."

        room = self.rooms[room_id]
        if len(room.players) < 2:
            return False, "Need 2 players to start."

        if self.launcher is None:
            return False, "GameLauncher not attached."

        ok, port_or_err = self.launcher.launch(room)
        if not ok:
            return False, port_or_err

        room.status = "running"
        room.port = port_or_err
        return True, room.port

    # -------------------------------------------------------
    def list_rooms(self):
        data = []
        for r in self.rooms.values():
            data.append({
                "room_id": r.room_id,
                "game_id": r.game_id,
                "host": r.host,
                "players": list(r.players),
                "type": r.type,
                "status": r.status,
                "port": r.port
            })
        return data
