import socket
import subprocess
import os
from pathlib import Path
from typing import Optional, Tuple


class GameLauncher:
    """
    Launches Battleship or Tetris game servers.
    Maps game_id -> game folder -> server executable.
    """

    def __init__(self, host="127.0.0.1"):
        self.host = host

    # ----------------------------------------------------
    # Utility: pick a free port for launching a game server
    # ----------------------------------------------------
    def _get_free_port(self) -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((self.host, 0))
        port = s.getsockname()[1]
        s.close()
        return port

    # ----------------------------------------------------
    # Map game_id → actual server executable path
    # You MUST update this based on your store metadata.
    # ----------------------------------------------------
    def _resolve_game_paths(self, game: dict) -> Tuple[str, str]:
        """
        Returns (server_script, client_script)
        based on the stored game folder.
        """

        game_path = Path(game["path"])  # Example: server/game_storage/Battleship/1.0

        server_script = game_path / "server" / f"{game['name'].lower()}_server.py"
        client_script = game_path / "client" / f"{game['name'].lower()}_client.py"

        if not server_script.exists():
            raise FileNotFoundError(f"Game server not found: {server_script}")

        return str(server_script), str(client_script)

    # ----------------------------------------------------
    # Launch game server (Battleship or Tetris)
    # ----------------------------------------------------
    def launch_game_server(self, game: dict, room_id: int) -> Tuple[int, Optional[subprocess.Popen]]:
        port = self._get_free_port()

        server_script, _ = self._resolve_game_paths(game)

        print(f"[GameLauncher] Starting game server: {server_script} on port {port}")

        # Example command: python3 battleship_server.py --port 18001
        cmd = [
            "python3",
            server_script,
            "--host", self.host,
            "--port", str(port)
        ]

        try:
            proc = subprocess.Popen(cmd)
        except Exception as e:
            print("[GameLauncher] Error launching game server:", e)
            proc = None

        return port, proc

    # ----------------------------------------------------
    # (Optional) method for starting clients
    # GUI or CLI can call this locally
    # ----------------------------------------------------
    def launch_local_client(self, game: dict, host: str, port: int):
        _, client_script = self._resolve_game_paths(game)

        cmd = ["python3", client_script, "--host", host, "--port", str(port)]
        print(f"[GameLauncher] Launching client: {cmd}")
        subprocess.Popen(cmd)

    # ----------------------------------------------------
    # Stop the game server
    # ----------------------------------------------------
    def stop_game_server(self, proc: Optional[subprocess.Popen]):
        if proc is None:
            return
        try:
            proc.terminate()
            print("[GameLauncher] Game server terminated.")
        except Exception:
            pass
