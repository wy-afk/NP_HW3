# server/account_manager.py
import json
from pathlib import Path
from typing import Literal, Optional

DATA_DIR = Path(__file__).resolve().parent / "data"
PLAYERS_FILE = DATA_DIR / "players.json"
DEVS_FILE = DATA_DIR / "developers.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def _save_json(path: Path, data: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class AccountManager:
    """
    Very simple username/password store.
    For HW3 this is enough; you can add extra fields later.
    """

    def __init__(self):
        self.players = _load_json(PLAYERS_FILE)      # {username: {"password": "...", ...}}
        self.developers = _load_json(DEVS_FILE)      # {username: {"password": "...", ...}}

        # online sessions: username -> connection info (optional)
        self.online_users: dict[str, dict] = {}

    # ---------- helpers ----------

    def _get_store(self, role: Literal["player", "developer"]) -> tuple[dict, Path]:
        if role == "player":
            return self.players, PLAYERS_FILE
        else:
            return self.developers, DEVS_FILE

    # ---------- API used by LobbyServer ----------

    def register(self, username: str, password: str, role: str) -> tuple[bool, str]:
        if role not in ("player", "developer"):
            return False, "invalid_role"

        store, path = self._get_store(role)
        if username in store:
            return False, "username_taken"

        if not username or not password:
            return False, "empty_username_or_password"

        store[username] = {
            "password": password,
            # add more fields later (email, created_at, stats, etc.)
        }
        _save_json(path, store)
        return True, "ok"

    def login(self, username: str, password: str, role: str) -> tuple[bool, str]:
        if role not in ("player", "developer"):
            return False, "invalid_role"

        store, _ = self._get_store(role)
        user = store.get(username)
        if user is None:
            return False, "user_not_found"

        if user["password"] != password:
            return False, "wrong_password"

        # Simple duplicate-login handling: reject if already logged in
        if username in self.online_users:
            return False, "already_logged_in"

        self.online_users[username] = {"role": role}
        return True, "ok"

    def logout(self, username: str):
        self.online_users.pop(username, None)

    def is_online(self, username: str) -> bool:
        return username in self.online_users

    def get_online_users(self, role: Optional[str] = None) -> list[str]:
        if role is None:
            return list(self.online_users.keys())
        return [u for u, info in self.online_users.items() if info["role"] == role]
