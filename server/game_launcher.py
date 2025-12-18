# server/game_launcher.py
import subprocess
import random
import time
import json
from pathlib import Path
import socket


class GameLauncher:

    def __init__(self, host="127.0.0.1", games=None):
        self.host = host
        self.games = games or {}

    def _load_manifest(self, game_path: Path) -> dict:
        mpath = game_path / "game.json"
        if not mpath.exists():
            return {}
        try:
            with mpath.open('r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _render_cmd(self, cmd_spec, host: str, port: int, room_id: int, extra: dict = None):
        extra = extra or {}
        # cmd_spec can be list or string
        def render_token(tok):
            if isinstance(tok, str):
                return tok.format(host=host, port=port, room_id=room_id, **extra)
            return tok

        if isinstance(cmd_spec, str):
            return cmd_spec.format(host=host, port=port, room_id=room_id, **extra).split()
        elif isinstance(cmd_spec, list):
            return [render_token(t) for t in cmd_spec]
        else:
            return []

    def launch(self, room):
        # Look up game info from games dictionary
        game = self.games.get(room.game_id)
        if not game:
            return False, f"Game {room.game_id} not found in registry"

        game_name = game.get("name")
        game_path = Path(game.get("path"))

        manifest = self._load_manifest(game_path)
        server_spec = manifest.get('server', {}).get('start_cmd')

        if not server_spec:
            # Fallback to legacy behavior: look for server/<name>_server.py
            server_script = game_path / "server" / f"{game_name.lower()}_server.py"
            if not server_script.exists():
                return False, f"Game server not found: {server_script}"
            # Many legacy game servers only accept a `--port` argument.
            # Use a minimal fallback that passes `--port` only; games
            # that require `host` should provide a `game.json` manifest
            # with an explicit `server.start_cmd` entry.
            server_spec = ["python3", str(server_script), "--port", "{port}"]

        port = random.randint(30000, 60000)

        cmd = self._render_cmd(server_spec, self.host, port, room.room_id)

        # Add room id if the manifest start_cmd didn't include it explicitly
        if "{room_id}" in repr(server_spec) and str(room.room_id) not in repr(cmd):
            cmd.extend(["--room-id", str(room.room_id)])

        print(f"[GameLauncher] Starting {game_name} server with cmd: {' '.join(cmd)} on port {port}")

        try:
            # Run from the game's runtime directory so relative paths in
            # `game.json` (e.g., "server/battleship_server.py") work.
            proc = subprocess.Popen(cmd, cwd=str(game_path))
        except Exception as e:
            return False, f"failed_to_start_process: {e}"

        # Wait for the new game server to accept connections on the chosen
        # port. This reduces races where the lobby notifies players before
        # the game server is ready.
        def _wait_for_port(host, port, timeout=5.0, interval=0.25):
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    with socket.create_connection((host, port), timeout=interval):
                        return True
                except Exception:
                    time.sleep(interval)
            return False

        started = _wait_for_port(self.host, port, timeout=6.0)
        if started:
            print(f"[GameLauncher] server appears to be listening on {self.host}:{port}")
            return True, port
        else:
            # process did not open port in time; terminate it to avoid
            # leaving stray processes around and return an error.
            try:
                proc.terminate()
            except Exception:
                pass
            return False, f"server_failed_to_listen_on_port_{port}"
