# server/store_manager.py
import json
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parent / "data"
GAMES_FILE = DATA_DIR / "games.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> list:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _save_json(path: Path, data: list):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class StoreManager:
    """
    Game catalog:
    [
      {
        "game_id": 1,
        "name": "Battleship",
        "version": "1.0",
        "developer": "dev_user",
        "path": "games/Battleship/1.0",
        "description": "..."
      },
      ...
    ]
    """

    def __init__(self):
        self.games: list[dict] = _load_json(GAMES_FILE)
        self._next_id = (max((g["game_id"] for g in self.games), default=0) + 1)

    # ---------- helpers ----------

    def _find_game(self, game_id: int) -> Optional[dict]:
        return next((g for g in self.games if g["game_id"] == game_id), None)

    # ---------- API used by LobbyServer / dev client ----------

    def list_games(self) -> list[dict]:
        return self.games

    def register_game(
        self,
        name: str,
        version: str,
        developer: str,
        path: str,
        description: str = "",
    ) -> dict:
        """
        For now, assume files are already in place (later you handle upload).
        """
        game = {
            "game_id": self._next_id,
            "name": name,
            "version": version,
            "developer": developer,
            "path": path,
            "description": description,
        }
        self._next_id += 1
        self.games.append(game)
        _save_json(GAMES_FILE, self.games)
        return game

    def update_version(self, game_id: int, new_version: str, new_path: str) -> bool:
        game = self._find_game(game_id)
        if not game:
            return False
        game["version"] = new_version
        game["path"] = new_path
        _save_json(GAMES_FILE, self.games)
        return True

    def remove_game(self, game_id: int, developer: str) -> bool:
        """
        Only allow owner (developer) to remove their game.
        """
        game = self._find_game(game_id)
        if not game or game["developer"] != developer:
            return False
        self.games = [g for g in self.games if g["game_id"] != game_id]
        _save_json(GAMES_FILE, self.games)
        return True
