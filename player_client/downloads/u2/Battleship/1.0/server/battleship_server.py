import socket
import threading
import json
import sys
import time

# -------------------------
# Network Helpers
# -------------------------
def send_json(conn, data):
    msg = (json.dumps(data) + "\n").encode()
    conn.sendall(msg)

def recv_json(conn):
    buffer = b""
    while b"\n" not in buffer:
        chunk = conn.recv(4096)
        if not chunk:
            return None
        buffer += chunk
    return json.loads(buffer.decode().strip())


# -------------------------
# Game Settings
# -------------------------

BOARD_SIZE = 10

SHIPS = {
    "Carrier": 5,
    "Battleship": 4,
    "Cruiser": 3,
    "Submarine": 3,
    "Destroyer": 2,
}

SHIP_SYMBOLS = {name[0] for name in SHIPS.keys()}


def empty_board():
    return [["~" for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]


# NEW: detect if one ship is fully destroyed
def ship_sunk(board, symbol):
    for row in board:
        for cell in row:
            if cell == symbol:
                return False
    return True


# -------------------------
# Battleship Game Server
# -------------------------

class BattleshipServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port

        # Supports 2+ players (ring turn order). First ship fully sunk wins.
        # Keep conservative defaults to avoid hanging on missing clients.
        self.min_players = 2
        self.max_players = 8
        self.join_grace_seconds = 5.0

        # Each entry: {conn, addr, user, role, board}
        self.players = []
        self.turn_index = 0

    def await_players(self):
        print("[BattleshipServer] Waiting for players...")

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.port))
        s.listen(8)

        players = []  # list of (conn, addr, hello_msg)
        last_join = None
        s.settimeout(0.5)

        while True:
            # Start once we've got enough players and no one new joins for a bit.
            if len(players) >= self.min_players and last_join is not None:
                if time.time() - last_join >= self.join_grace_seconds:
                    break
            if len(players) >= self.max_players:
                break

            try:
                conn, addr = s.accept()
            except socket.timeout:
                continue

            # The lobby process probes the port to check readiness.
            # That probe connects but does not speak the game protocol.
            # Require a first message of type HELLO to qualify as a real player.
            try:
                conn.settimeout(1.0)
                hello = recv_json(conn)
            except Exception:
                hello = None
            finally:
                try:
                    conn.settimeout(None)
                except Exception:
                    pass

            if not isinstance(hello, dict) or hello.get("type") != "HELLO":
                try:
                    conn.close()
                except Exception:
                    pass
                continue

            players.append((conn, addr, hello))
            last_join = time.time()
            print(f"[Player {len(players)} connected] {addr} user={hello.get('user')}")

        try:
            s.settimeout(None)
        except Exception:
            pass

        # Assign roles 1..N (string) so the existing client can display it.
        self.players = []
        for i, (conn, addr, hello) in enumerate(players, start=1):
            role = str(i)
            user = None
            if isinstance(hello, dict):
                user = hello.get("user")
            self.players.append({"conn": conn, "addr": addr, "user": user, "role": role, "board": None})
            send_json(conn, {"msg": "ASSIGN", "role": role})

        print(f"[BattleshipServer] Starting with {len(self.players)} players")

    def receive_board(self, player_conn, player_name):
        data = recv_json(player_conn)
        if not data or "board" not in data:
            print(f"[ERROR] Invalid board from {player_name}")
            return None
        print(f"[RECV] Board from {player_name}")
        return data["board"]

    def _alive_players(self):
        return [p for p in self.players if p.get("conn") is not None and p.get("board") is not None]

    def _safe_send(self, conn, payload):
        try:
            send_json(conn, payload)
            return True
        except Exception:
            return False

    def relay_turn(self):
        # Ring turn order over active players. Defender is next player in ring.
        alive = [i for i, p in enumerate(self.players) if p.get("board") is not None]
        if len(alive) < 2:
            print("[ERROR] Not enough players with boards to start")
            return

        turn_pos = 0

        while True:
            # Keep alive list current (drop disconnected conns)
            alive = [i for i in alive if self.players[i].get("conn") is not None]
            if len(alive) == 0:
                return
            if len(alive) == 1:
                winner = self.players[alive[0]]
                print(f"[GAME OVER] Player {winner.get('role')} wins (others disconnected)")
                try:
                    self._safe_send(winner["conn"], {"msg": "WIN"})
                except Exception:
                    pass
                return

            if turn_pos >= len(alive):
                turn_pos = 0

            attacker_idx = alive[turn_pos]
            defender_idx = alive[(turn_pos + 1) % len(alive)]
            attacker = self.players[attacker_idx]
            defender = self.players[defender_idx]
            attacker_conn = attacker.get("conn")
            defender_conn = defender.get("conn")
            defender_board = defender.get("board")

            if attacker_conn is None or defender_conn is None or defender_board is None:
                turn_pos += 1
                continue

            attacker_role = attacker.get("role")
            defender_role = defender.get("role")

            # Tell attacker to play
            if not self._safe_send(attacker_conn, {"msg": "YOUR_TURN"}):
                attacker["conn"] = None
                continue

            attack = recv_json(attacker_conn)
            if not attack:
                print("[ERROR] Lost connection to attacker")
                attacker["conn"] = None
                continue

            try:
                r, c = int(attack["row"]), int(attack["col"])
            except Exception:
                self._safe_send(attacker_conn, {"msg": "RESULT", "result": "REPEAT"})
                continue

            if not (0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE):
                self._safe_send(attacker_conn, {"msg": "RESULT", "result": "REPEAT"})
                continue

            print(f"[TURN] Player {attacker_role} attacks Player {defender_role} at ({r},{c})")

            cell = defender_board[r][c]

            if cell in SHIP_SYMBOLS:
                result = "HIT"
                hit_symbol = cell
                defender_board[r][c] = "X"
            elif cell == "X" or cell == "o":
                result = "REPEAT"
                hit_symbol = None
            else:
                result = "MISS"
                hit_symbol = None
                defender_board[r][c] = "o"

            self._safe_send(attacker_conn, {"msg": "RESULT", "result": result})
            self._safe_send(defender_conn, {"msg": "INCOMING", "row": r, "col": c, "result": result})

            # Win condition stays: first ship fully sunk wins.
            if result == "HIT" and hit_symbol is not None:
                if ship_sunk(defender_board, hit_symbol):
                    print(f"[GAME OVER] Player {attacker_role} wins by sinking {hit_symbol}!")
                    for i, p in enumerate(self.players):
                        conn = p.get("conn")
                        if conn is None:
                            continue
                        if i == attacker_idx:
                            self._safe_send(conn, {"msg": "WIN"})
                        else:
                            self._safe_send(conn, {"msg": "LOSE"})
                    return

            # Advance to next attacker
            turn_pos += 1

    def start(self):
        self.await_players()

        # Receive boards from all players
        for p in self.players:
            role = p.get("role")
            conn = p.get("conn")
            if conn is None:
                continue
            p["board"] = self.receive_board(conn, f"Player {role}")

        print("[BattleshipServer] Starting gameplay loop...")
        self.relay_turn()

        print("[BattleshipServer] Game finished. Closing connections.")
        for p in self.players:
            try:
                if p.get("conn"):
                    p["conn"].close()
            except Exception:
                pass


# -------------------------
# Command-line entry
# -------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    server = BattleshipServer("0.0.0.0", args.port)
    server.start()
