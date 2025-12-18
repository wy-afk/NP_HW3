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
    max_players: int = 2
    status: str = "waiting"  # waiting / running
    port: Optional[int] = None
    # simple in-memory chat log: list of {user, msg, ts}
    chat: list = field(default_factory=list)


class RoomManager:

    def __init__(self):
        self.rooms: Dict[int, Room] = {}
        self.next_room_id = 1
        self.launcher = None
        # invitations: room_id -> set(usernames)
        self.invites: Dict[int, set] = {}

    def attach_launcher(self, launcher):
        self.launcher = launcher

    # -------------------------------------------------------
    # Create room
    # -------------------------------------------------------
    def create_room(self, game_id: int, username: str, room_type: str, max_players: int = 2):
        room_id = self.next_room_id
        self.next_room_id += 1

        room = Room(room_id, game_id, username, room_type, max_players=max_players)
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

        if len(room.players) >= int(room.max_players or 2):
            return False, f"Room already full ({int(room.max_players or 2)} players)."

        # PRIVATE ROOM RULE: ONLY HOST CAN JOIN
        if room.type == "private" and username != room.host:
            return False, "This is a private room. Only the host may join."

        # PUBLIC ROOM: anyone can join
        room.players.append(username)
        return True, f"{username} joined room {room_id}"

    # -------------------------------------------------------
    # Invite management for PRIVATE rooms
    # -------------------------------------------------------
    def invite_user(self, room_id: int, host: str, target: str):
        if room_id not in self.rooms:
            return False, "Room does not exist."
        room = self.rooms[room_id]
        if room.host != host:
            return False, "Only the host can invite users."
        if room.type != "private":
            return False, "Invites are only for private rooms."
        if target in room.players:
            return False, "User already in room."
        self.invites.setdefault(room_id, set()).add(target)
        return True, f"{target} invited to room {room_id}"

    def list_invites_for(self, username: str):
        # return list of room summaries where username is invited
        data = []
        for rid, targets in self.invites.items():
            if username in targets:
                r = self.rooms.get(rid)
                if r:
                    data.append({
                        "room_id": r.room_id,
                        "game_id": r.game_id,
                        "host": r.host,
                        "type": r.type,
                    })
        return data

    def accept_invite(self, room_id: int, username: str):
        if room_id not in self.rooms:
            return False, "Room does not exist."
        if room_id not in self.invites or username not in self.invites[room_id]:
            return False, "No invite for this user."
        room = self.rooms[room_id]
        if room.status != "waiting":
            return False, "Room already started."
        if len(room.players) >= int(room.max_players or 2):
            return False, f"Room already full ({int(room.max_players or 2)} players)."
        room.players.append(username)
        # remove invite
        self.invites[room_id].discard(username)
        return True, f"{username} joined room {room_id} via invite"

    def send_chat(self, room_id: int, username: str, message: str):
        """Append a chat message to the room log. Only participants may send."""
        if room_id not in self.rooms:
            return False, "Room does not exist"
        room = self.rooms[room_id]
        if username not in room.players:
            return False, "User not in room"
        import time
        entry = {"user": username, "msg": message, "ts": int(time.time())}
        room.chat.append(entry)
        # keep chat bounded (e.g., last 200 msgs)
        if len(room.chat) > 200:
            room.chat = room.chat[-200:]
        return True, entry

    def list_chat(self, room_id: int):
        if room_id not in self.rooms:
            return False, "Room does not exist"
        room = self.rooms[room_id]
        return True, list(room.chat)

    def revoke_invite(self, room_id: int, host: str, target: str):
        if room_id not in self.rooms:
            return False, "Room does not exist."
        room = self.rooms[room_id]
        if room.host != host:
            return False, "Only the host can revoke invites."
        if room_id not in self.invites or target not in self.invites[room_id]:
            return False, "Invite not found."
        self.invites[room_id].discard(target)
        return True, f"Invite for {target} revoked from room {room_id}"

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
