# server/game_launcher.py
import subprocess
import random
from pathlib import Path

class GameLauncher:

    def __init__(self, host="127.0.0.1", games=None):
        self.host = host
        self.games = games or {}

    def launch(self, room):
        # Look up game info from games dictionary
        game = self.games.get(room.game_id)
        if not game:
            return False, f"Game {room.game_id} not found in registry"
        
        game_name = game["name"]
        game_path = Path(game["path"])
        server_script = game_path / "server" / f"{game_name.lower()}_server.py"

        if not server_script.exists():
            return False, f"Game server not found: {server_script}"

        port = random.randint(30000, 60000)

        cmd = [
            "python3",
            str(server_script),
            "--host", self.host,
            "--port", str(port),
            "--room", str(room.room_id)
        ]

        print(f"[GameLauncher] Starting game server: {server_script} on port {port}")

        try:
            subprocess.Popen(cmd)
            return True, port
        except Exception as e:
            return False, str(e)
