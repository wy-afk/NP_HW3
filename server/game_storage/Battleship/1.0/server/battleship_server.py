import socket
import json
import argparse

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
# Game Logic
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


def all_ships_sunk(board):
    """Check if all ships are gone from this board."""
    for row in board:
        for cell in row:
            if cell in SHIP_SYMBOLS:
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

        # boards AFTER placement from clients
        self.p1_board = None
        self.p2_board = None

        # Current turn: 1 or 2
        self.turn = 1

    def await_players(self):
        """Wait for 2 players to connect."""
        print("[BattleshipServer] Waiting for players...")

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((self.host, self.port))
        s.listen(2)

        self.p1, addr1 = s.accept()
        print(f"[Player 1 connected] {addr1}")
        send_json(self.p1, {"msg": "ASSIGN", "role": "A"})

        self.p2, addr2 = s.accept()
        print(f"[Player 2 connected] {addr2}")
        send_json(self.p2, {"msg": "ASSIGN", "role": "B"})

        # we can close the listening socket now
        s.close()

    def receive_board(self, player_conn, player_name):
        """Receive placed board layout from client."""
        data = recv_json(player_conn)
        if not data or "board" not in data:
            print(f"[ERROR] Invalid board from {player_name}")
            return None
        print(f"[RECV] Board from {player_name}")
        return data["board"]

    def relay_turn(self):
        """Relay turns between p1 and p2 until game ends."""
        while True:
            if self.turn == 1:
                attacker = self.p1
                defender_board = self.p2_board
                defender = self.p2
                attacker_name = "A"
            else:
                attacker = self.p2
                defender_board = self.p1_board
                defender = self.p1
                attacker_name = "B"

            # Notify attacker it's their turn
            send_json(attacker, {"msg": "YOUR_TURN"})

            # Get attack coordinates
            attack = recv_json(attacker)
            if not attack:
                print("[ERROR] Lost connection to attacker")
                return

            r, c = attack["row"], attack["col"]
            print(f"[Turn] Player {attacker_name} attacks ({r},{c})")

            # Basic bounds guard (in case client misbehaves)
            if not (0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE):
                result = "INVALID"
            else:
                cell = defender_board[r][c]
                # Determine result
                if cell in SHIP_SYMBOLS:
                    result = "HIT"
                    defender_board[r][c] = "X"
                elif cell == "X" or cell == "o":
                    result = "REPEAT"
                else:
                    result = "MISS"
                    defender_board[r][c] = "o"

            # Notify attacker of result
            send_json(attacker, {"msg": "RESULT", "result": result})

            # Notify defender of attack
            send_json(defender, {
                "msg": "INCOMING",
                "row": r,
                "col": c,
                "result": result
            })

            # Check win condition
            if result != "INVALID" and all_ships_sunk(defender_board):
                winner = attacker_name
                print(f"[GAME OVER] Player {winner} wins!")
                send_json(attacker, {"msg": "WIN"})
                send_json(defender, {"msg": "LOSE"})
                return

            # Next turn
            self.turn = 2 if self.turn == 1 else 1

    def start(self):
        self.await_players()

        # Receive boards from both players
        self.p1_board = self.receive_board(self.p1, "Player A")
        self.p2_board = self.receive_board(self.p2, "Player B")

        print("[BattleshipServer] Starting turn loop...")
        self.relay_turn()

        print("[BattleshipServer] Game finished. Shutting down.")
        self.p1.close()
        self.p2.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    server = BattleshipServer(args.host, args.port)
    server.start()
