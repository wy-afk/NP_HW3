# server/game_launcher.py
import socket
import subprocess
from typing import Optional, Tuple


class GameLauncher:
    """
    Responsible for starting/stopping individual game server processes.
    For now this is a stub; later you will:
      - map game_id -> executable command
      - start subprocess with the chosen port
    """

    def __init__(self, host: str = "127.0.0.1", base_port: int = 18000):
        self.host = host
        self.base_port = base_port

    # ---------- helpers ----------

    def _get_free_port(self) -> int:
        """
        Ask OS for a free port.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((self.host, 0))
            return s.getsockname()[1]

    # ---------- API ----------

    def launch_game_server(self, game_id: int, room_id: int) -> Tuple[int, Optional[subprocess.Popen]]:
        """
        For now, just picks a port and returns (port, None).
        Later you will start your Battleship/Tetris game server here.
        """
        port = self._get_free_port()

        # TODO: map game_id -> actual command, e.g.:
        # cmd = ["python", "games/Battleship/1.0/server/battleship_server.py", "--port", str(port)]
        # proc = subprocess.Popen(cmd)

        proc = None
        print(f"[GameLauncher] (STUB) Would start game_id={game_id} on port {port} for room {room_id}")
        return port, proc

    def stop_game_server(self, proc: Optional[subprocess.Popen]):
        if proc is None:
            return
        try:
            proc.terminate()
        except Exception:
            pass
