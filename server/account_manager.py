# server/account_manager.py
import json
import time
import threading
from pathlib import Path
from typing import Literal, Optional

DATA_DIR = Path(__file__).resolve().parent / "data"
PLAYERS_FILE = DATA_DIR / "players.json"
DEVS_FILE = DATA_DIR / "developers.json"
LEADERBOARD_FILE = DATA_DIR / "leaderboard.json"

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
    Very simple username/password store with a short disconnect grace period.
    If a client disconnects briefly (for example while launching a local interactive
    game) the server will mark the session as disconnected and keep it for a
    short grace window before fully removing it. This avoids accidental immediate
    logouts for transient disconnects.
    """

    # grace period (seconds) before a disconnected session is removed
    GRACE_PERIOD = 30

    def __init__(self):
        self.players = _load_json(PLAYERS_FILE)      # {username: {"password": "...", ...}}
        self.developers = _load_json(DEVS_FILE)      # {username: {"password": "...", ...}}

        # Ensure player records have stats fields (wins, played)
        modified = False
        for u, info in list(self.players.items()):
            if not isinstance(info, dict):
                continue
            if "wins" not in info or "played" not in info:
                info.setdefault("wins", 0)
                info.setdefault("played", 0)
                modified = True
        if modified:
            _save_json(PLAYERS_FILE, self.players)

        # online sessions: username -> {role, connected: bool, last_seen: float}
        self.online_users: dict[str, dict] = {}

        # start a background cleaner to expire stale disconnected sessions
        self._stop_cleaner = False
        self._cleaner_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleaner_thread.start()

    # ---------- helpers ----------

    def _get_store(self, role: Literal["player", "developer"]) -> tuple[dict, Path]:
        if role == "player":
            return self.players, PLAYERS_FILE
        else:
            return self.developers, DEVS_FILE

    # ---------- background cleaner ----------

    def _cleanup_loop(self):
        while not self._stop_cleaner:
            now = time.time()
            to_remove = []
            for u, info in list(self.online_users.items()):
                if not info.get("connected"):
                    last = info.get("last_seen", 0)
                    if now - last > self.GRACE_PERIOD:
                        to_remove.append(u)

            for u in to_remove:
                self.online_users.pop(u, None)

            time.sleep(5)

    def stop(self):
        self._stop_cleaner = True
        try:
            self._cleaner_thread.join(timeout=1)
        except Exception:
            pass

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

    def record_result(self, winners: list, players: list):
        """Record a finished game's result: increment 'played' for all players,
        increment 'wins' for the winners, and persist the players file."""
        modified = False
        for p in players:
            if p not in self.players:
                # create a minimal record if missing
                self.players[p] = {"password": "", "wins": 0, "played": 0}
                modified = True
            # ensure fields
            self.players[p].setdefault("wins", 0)
            self.players[p].setdefault("played", 0)
            try:
                self.players[p]["played"] = int(self.players[p].get("played", 0)) + 1
            except Exception:
                self.players[p]["played"] = 1
            modified = True

        for w in winners:
            if w not in self.players:
                self.players[w] = {"password": "", "wins": 0, "played": 0}
            self.players[w].setdefault("wins", 0)
            try:
                self.players[w]["wins"] = int(self.players[w].get("wins", 0)) + 1
            except Exception:
                self.players[w]["wins"] = 1
            modified = True

        if modified:
            _save_json(PLAYERS_FILE, self.players)
            # Also update the aggregated leaderboard file so external tools
            # (clients, dashboards) can read a simple JSON snapshot.
            try:
                # Build leaderboard rows sorted by wins desc, then played asc
                rows = []
                for uname, info in self.players.items():
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

                _save_json(LEADERBOARD_FILE, {"leaderboard": leaderboard})
            except Exception:
                # Best-effort: don't let leaderboard write failures break result recording
                pass

    def get_leaderboard(self):
        """Return the cached leaderboard if available, otherwise compute from players."""
        if LEADERBOARD_FILE.exists():
            try:
                return _load_json(LEADERBOARD_FILE).get("leaderboard", [])
            except Exception:
                pass

        # Fallback: compute on the fly
        rows = []
        for uname, info in self.players.items():
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

        return leaderboard

    def login(self, username: str, password: str, role: str) -> tuple[bool, str]:
        if role not in ("player", "developer"):
            return False, "invalid_role"

        store, _ = self._get_store(role)
        user = store.get(username)
        if user is None:
            return False, "user_not_found"

        if user["password"] != password:
            return False, "wrong_password"

        # If user currently has a connected session, reject duplicate login
        existing = self.online_users.get(username)
        if existing and existing.get("connected"):
            return False, "already_logged_in"

        # Accept login and mark session connected
        self.online_users[username] = {"role": role, "connected": True, "last_seen": time.time()}
        return True, "ok"

    def logout(self, username: str):
        # immediate full logout (explicit user-initiated)
        self.online_users.pop(username, None)

    def mark_disconnected(self, username: str):
        # mark a session as disconnected and set last_seen timestamp; the background
        # cleaner will remove it after GRACE_PERIOD seconds.
        if username in self.online_users:
            self.online_users[username]["connected"] = False
            self.online_users[username]["last_seen"] = time.time()
        else:
            # create a disconnected entry to reserve the username briefly
            self.online_users[username] = {"role": "player", "connected": False, "last_seen": time.time()}

    def is_online(self, username: str) -> bool:
        info = self.online_users.get(username)
        return bool(info and info.get("connected"))

    def get_online_users(self, role: Optional[str] = None) -> list[str]:
        if role is None:
            return [u for u, info in self.online_users.items() if info.get("connected")]
        return [u for u, info in self.online_users.items() if info.get("role") == role and info.get("connected")]
