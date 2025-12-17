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

# Map symbol -> ship name for reporting
SYMBOL_TO_NAME = {name[0]: name for name in SHIPS.keys()}


def all_ships_sunk(board):
    """Check if all ships are gone from this board."""
    for row in board:
        for cell in row:
            if cell in SHIP_SYMBOLS:
                return False
    return True


# -------------------------
# Reporting helper
# -------------------------
def report_result_to_lobby(winners, players, attempts=3, base_delay=0.2):
    import socket as _socket, json as _json, struct as _struct, time as _time
    payload = {"action": "record_result", "data": {"winners": winners, "players": players}}
    b = _json.dumps(payload).encode("utf-8")
    hdr = _struct.pack("!I", len(b))
    for attempt in range(attempts):
        try:
            s2 = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            s2.settimeout(1.0)
            s2.connect(("127.0.0.1", 5555))
            s2.sendall(hdr + b)
            # read response if any
            try:
                rh = s2.recv(4)
                if rh:
                    (ln,) = _struct.unpack("!I", rh)
                    resp = s2.recv(ln).decode()
                    # ignore parsed response
            except Exception:
                pass
            try:
                s2.close()
            except Exception:
                pass
            return True
        except Exception:
            _time.sleep(base_delay * (2 ** attempt))
            continue
    return False


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

        # Expect each client to send a HELLO JSON before assignment (so we can
        # know their username). Each side should send a newline-terminated JSON.
        conn1, addr1 = s.accept()
        hello1 = recv_json(conn1)
        name1 = hello1.get('user') if isinstance(hello1, dict) else 'P1'
        print(f"[Player 1 connected] {addr1} user={name1}")
        send_json(conn1, {"msg": "ASSIGN", "role": "A"})

        conn2, addr2 = s.accept()
        hello2 = recv_json(conn2)
        name2 = hello2.get('user') if isinstance(hello2, dict) else 'P2'
        print(f"[Player 2 connected] {addr2} user={name2}")
        send_json(conn2, {"msg": "ASSIGN", "role": "B"})

        self.p1 = conn1
        self.p2 = conn2
        # store names for result reporting
        self.p1_name = name1
        self.p2_name = name2

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
                    boat_sym = cell
                    # mark hit
                    defender_board[r][c] = "X"
                    # check if this sank the entire ship (no remaining symbol on board)
                    remaining = any(boat_sym in row for row in defender_board)
                    sunk_boat = None
                    if not remaining:
                        sunk_boat = SYMBOL_TO_NAME.get(boat_sym)
                elif cell == "X" or cell == "o":
                    result = "REPEAT"
                    sunk_boat = None
                else:
                    result = "MISS"
                    defender_board[r][c] = "o"
                    sunk_boat = None

            # Notify attacker of result
            send_json(attacker, {"msg": "RESULT", "result": result})

            # Notify defender of attack
            send_json(defender, {
                "msg": "INCOMING",
                "row": r,
                "col": c,
                "result": result
            })

            # Check immediate-sink win condition: if this attack sank any ship, attacker wins
            if result == "HIT" and sunk_boat:
                winner = attacker_name
                print(f"[GAME OVER] Player {winner} wins! (sank {sunk_boat})")
                # inform attacker and defender which boat was sunk
                send_json(attacker, {"msg": "WIN", "boat": sunk_boat})
                send_json(defender, {"msg": "LOSE", "boat": sunk_boat})
                # report immediately to lobby
                try:
                    winner_name = self.p1_name if attacker_name == 'A' else self.p2_name
                    report_result_to_lobby([winner_name], [self.p1_name, self.p2_name])
                    print(f"[REPORT] Reported result to lobby: winner={winner_name}")
                except Exception:
                    print("[REPORT] Failed to report result to lobby")
                return

            # Fallback: previous behaviour (win when all ships gone)
            if result != "INVALID" and all_ships_sunk(defender_board):
                winner = attacker_name
                print(f"[GAME OVER] Player {winner} wins! (all ships sunk)")
                send_json(attacker, {"msg": "WIN"})
                send_json(defender, {"msg": "LOSE"})
                try:
                    winner_name = self.p1_name if attacker_name == 'A' else self.p2_name
                    report_result_to_lobby([winner_name], [self.p1_name, self.p2_name])
                    print(f"[REPORT] Reported result to lobby: winner={winner_name}")
                except Exception:
                    print("[REPORT] Failed to report result to lobby")
                return

            # Next turn
            self.turn = 2 if self.turn == 1 else 1

    def start(self):
        try:
            self.await_players()

            # Receive boards from both players
            self.p1_board = self.receive_board(self.p1, "Player A")
            self.p2_board = self.receive_board(self.p2, "Player B")

            print("[BattleshipServer] Starting turn loop...")
            self.relay_turn()

            print("[BattleshipServer] Game finished. Shutting down.")
        except Exception as e:
            print(f"[BattleshipServer] Error during game: {e}")
        finally:
            try:
                if self.p1:
                    self.p1.close()
            except Exception:
                pass
            try:
                if self.p2:
                    self.p2.close()
            except Exception:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--room-id", required=False, default=None)
    # keep compatibility with optional launcher args
    parser.add_argument("--seed", required=False, default=None)
    parser.add_argument("--lobby-host", required=False, default=None)
    parser.add_argument("--lobby-notify-port", type=int, required=False, default=None)
    args = parser.parse_args()

    try:
        server = BattleshipServer(args.host, args.port)
        server.start()
    except Exception as e:
        # Print stack for debugging and exit
        import traceback
        print("[BattleshipServer] Fatal error during startup:")
        traceback.print_exc()
        raise
