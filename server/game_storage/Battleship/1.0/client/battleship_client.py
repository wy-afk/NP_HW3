import socket
import json
import argparse
import random

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


def print_board(board, title="Board"):
    print("\n" + title)
    header = "   " + " ".join(f"{c}" for c in range(BOARD_SIZE))
    print(header)
    for i, row in enumerate(board):
        print(f"{i:2d} " + " ".join(row))
    print()


def parse_coord(s: str):
    """Parse 'r,c' or 'r c' into (r, c)."""
    s = s.strip().replace(",", " ")
    parts = s.split()
    if len(parts) != 2:
        raise ValueError("Need two numbers")
    r = int(parts[0])
    c = int(parts[1])
    return r, c


def can_place(board, r, c, size, orientation):
    """Check if a ship of 'size' fits starting at (r,c)."""
    if orientation == "H":
        if c + size > BOARD_SIZE:
            return False
        for i in range(size):
            if board[r][c + i] != "~":
                return False
    else:  # "V"
        if r + size > BOARD_SIZE:
            return False
        for i in range(size):
            if board[r + i][c] != "~":
                return False
    return True


def place_ship(board, r, c, size, orientation, symbol):
    if orientation == "H":
        for i in range(size):
            board[r][c + i] = symbol
    else:
        for i in range(size):
            board[r + i][c] = symbol


def auto_place_ships():
    """Randomly place all ships without overlapping."""
    board = empty_board()
    for name, size in SHIPS.items():
        symbol = name[0]
        placed = False
        while not placed:
            r = random.randint(0, BOARD_SIZE - 1)
            c = random.randint(0, BOARD_SIZE - 1)
            orientation = random.choice(["H", "V"])
            if can_place(board, r, c, size, orientation) and symbol in SHIP_SYMBOLS:
                place_ship(board, r, c, size, orientation, symbol)
                placed = True
    print_board(board, "Your Board (Auto-placed)")
    print("[Auto-placement complete]")
    return board


def manual_place_ships():
    """Manual placement with clear prompts."""
    board = empty_board()
    print("\n--- Ship Placement (Manual) ---")

    for name, size in SHIPS.items():
        symbol = name[0]
        while True:
            print_board(board, f"Placing {name} (size {size})")

            try:
                pos = input(f"Enter starting row,col for {name} (e.g., 3,5 or 3 5): ")
                r, c = parse_coord(pos)
                if not (0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE):
                    print("Out of bounds. Try again.")
                    continue

                orientation = input("Horizontal or Vertical (H/V): ").strip().upper()
                if orientation not in ("H", "V"):
                    print("Invalid orientation. Please enter H or V.")
                    continue

                if not can_place(board, r, c, size, orientation):
                    print("Ship doesn't fit there or overlaps. Try again.")
                    continue

                place_ship(board, r, c, size, orientation, symbol)
                print_board(board, f"{name} placed.")
                break
            except ValueError:
                print("Invalid format. Please enter two integers like '3,5' or '3 5'.")
            except Exception as e:
                print("Invalid input:", e)

    print("[Placement complete]")
    return board


def place_ships():
    """Ask user: auto or manual placement."""
    print("\n--- Ship Placement ---\n")
    while True:
        choice = input("Do you want to auto-place all ships? (Y/N): ").strip().upper()
        if choice == "Y":
            return auto_place_ships()
        elif choice == "N":
            return manual_place_ships()
        else:
            print("Please enter Y or N.")


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((args.host, args.port))

    # Receive role
    role_msg = recv_json(s)
    role = role_msg["role"]

    print(f"Connected to Battleship Server as Player {role}")

    # Ship placement
    my_board = place_ships()
    send_json(s, {"board": my_board})

    enemy_view = empty_board()
    last_attack = None

    # Main game loop
    while True:
        msg = recv_json(s)
        if msg is None:
            print("Disconnected from server.")
            break

        t = msg.get("msg")

        if t == "YOUR_TURN":
            print("\n--- Your Turn ---")
            print_board(enemy_view, "Enemy Board (Your view)")
            print_board(my_board, "Your Board")

            while True:
                try:
                    pos = input("Enter attack row,col (e.g., 4,7 or 4 7): ")
                    r, c = parse_coord(pos)
                    if not (0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE):
                        print("Out of bounds. Try again.")
                        continue
                    last_attack = (r, c)
                    send_json(s, {"row": r, "col": c})
                    break
                except ValueError:
                    print("Invalid format. Please enter two integers like '3,5' or '3 5'.")
                except Exception as e:
                    print("Invalid input:", e)

        elif t == "RESULT":
            result = msg["result"]
            print(f"Attack result: {result}")
            if last_attack is not None and result in ("HIT", "MISS", "REPEAT"):
                r, c = last_attack
                if result == "HIT":
                    enemy_view[r][c] = "X"
                elif result == "MISS":
                    enemy_view[r][c] = "o"
                # REPEAT: keep existing mark
                print_board(enemy_view, "Enemy Board (Updated)")

        elif t == "INCOMING":
            r, c, result = msg["row"], msg["col"], msg["result"]
            print(f"Enemy attacked ({r},{c}) → {result}")

            if 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE:
                if result == "HIT":
                    my_board[r][c] = "X"
                elif result == "MISS":
                    my_board[r][c] = "o"

            print_board(my_board, "Your Board (After attack)")

        elif t == "WIN":
            print("\n🎉 YOU WIN! 🎉")
            break

        elif t == "LOSE":
            print("\n❌ YOU LOSE ❌")
            break

    s.close()


if __name__ == "__main__":
    main()
