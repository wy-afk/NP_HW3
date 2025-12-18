import socket
import threading
import json
import sys

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

        self.p1 = None
        self.p2 = None

        self.p1_board = None
        self.p2_board = None

        self.turn = 1  # 1 = Player A, 2 = Player B

    def await_players(self):
        print("[BattleshipServer] Waiting for players...")

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.port))
        s.listen(8)

        players = []  # list of (conn, addr, hello_msg)
        while len(players) < 2:
            conn, addr = s.accept()

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
            print(f"[Player {len(players)} connected] {addr} user={hello.get('user')}")

        self.p1, addr1, _ = players[0]
        self.p2, addr2, _ = players[1]

        send_json(self.p1, {"msg": "ASSIGN", "role": "A"})
        send_json(self.p2, {"msg": "ASSIGN", "role": "B"})

    def receive_board(self, player_conn, player_name):
        data = recv_json(player_conn)
        if not data or "board" not in data:
            print(f"[ERROR] Invalid board from {player_name}")
            return None
        print(f"[RECV] Board from {player_name}")
        return data["board"]

    def relay_turn(self):
        while True:

            if self.turn == 1:
                attacker = self.p1
                defender = self.p2
                defender_board = self.p2_board
                attacker_name = "A"
            else:
                attacker = self.p2
                defender = self.p1
                defender_board = self.p1_board
                attacker_name = "B"

            # Tell attacker to play
            send_json(attacker, {"msg": "YOUR_TURN"})

            attack = recv_json(attacker)
            if not attack:
                print("[ERROR] Lost connection to attacker")
                return

            r, c = attack["row"], attack["col"]
            print(f"[TURN] Player {attacker_name} attacks ({r},{c})")

            cell = defender_board[r][c]

            # -------------------------
            # Determine hit / miss
            # -------------------------
            if cell in SHIP_SYMBOLS:
                result = "HIT"
                hit_symbol = cell     # IMPORTANT: save symbol before overwriting
                defender_board[r][c] = "X"
            elif cell == "X" or cell == "o":
                result = "REPEAT"
            else:
                result = "MISS"
                defender_board[r][c] = "o"

            # Tell attacker
            send_json(attacker, {"msg": "RESULT", "result": result})

            # Tell defender
            send_json(defender, {
                "msg": "INCOMING",
                "row": r,
                "col": c,
                "result": result
            })

            # -------------------------
            # NEW WIN CONDITION:
            #    First ship fully sunk wins
            # -------------------------
            if result == "HIT":
                # check if this ship is fully destroyed
                if ship_sunk(defender_board, hit_symbol):
                    print(f"[GAME OVER] Player {attacker_name} wins by sinking {hit_symbol}!")
                    send_json(attacker, {"msg": "WIN"})
                    send_json(defender, {"msg": "LOSE"})
                    return

            # Normal continue
            self.turn = 2 if self.turn == 1 else 1

    def start(self):
        self.await_players()

        # Receive boards from both players
        self.p1_board = self.receive_board(self.p1, "Player A")
        self.p2_board = self.receive_board(self.p2, "Player B")

        print("[BattleshipServer] Starting gameplay loop...")
        self.relay_turn()

        print("[BattleshipServer] Game finished. Closing connections.")
        self.p1.close()
        self.p2.close()


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
