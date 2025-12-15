import socket
import json
import argparse

BOARD_SIZE = 5

SHIPS = {
    "Destroyer": 2,
    "Submarine": 3,
    "Battleship": 4
}

def empty_board():
    return [["~" for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]

def print_board(board, title="Board"):
    print("\n" + title)
    print("  " + " ".join(map(str, range(BOARD_SIZE))))
    for i, row in enumerate(board):
        print(i, " ".join(row))
    print()

def place_ships():
    """Simplified manual placement based on HW1 logic."""
    board = empty_board()
    print("\n--- Ship Placement ---\n")

    for ship, size in SHIPS.items():
        print_board(board, f"Placing {ship} (size {size})")

        while True:
            try:
                pos = input(f"Enter starting row,col for {ship}: ")
                r, c = map(int, pos.split(","))
                orientation = input("Horizontal or Vertical (H/V): ").upper()

                if orientation == "H":
                    if c + size > BOARD_SIZE:
                        print("Ship doesn’t fit horizontally!")
                        continue
                    # place ship
                    for i in range(size):
                        board[r][c + i] = ship[0]
                    break

                elif orientation == "V":
                    if r + size > BOARD_SIZE:
                        print("Ship doesn’t fit vertically!")
                        continue
                    # place ship
                    for i in range(size):
                        board[r + i][c] = ship[0]
                    break

                else:
                    print("Invalid orientation.")
            except:
                print("Invalid input. Try again.")

        print_board(board)

    print("[Placement complete]\n")
    return board


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

    # Enemy board tracking (unknown cells = ~)
    enemy_view = empty_board()

    # Main game loop
    while True:
        msg = recv_json(s)
        if msg is None:
            print("Disconnected from server.")
            break

        if msg["msg"] == "YOUR_TURN":
            print("\n--- Your Turn ---")
            print_board(enemy_view, "Enemy Board")

            while True:
                pos = input("Enter attack row,col: ")
                try:
                    r, c = map(int, pos.split(","))
                    break
                except:
                    print("Invalid format. Enter row,col")

            send_json(s, {"row": r, "col": c})

        elif msg["msg"] == "RESULT":
            result = msg["result"]
            print(f"Attack result: {result}")

        elif msg["msg"] == "INCOMING":
            r, c, result = msg["row"], msg["col"], msg["result"]
            print(f"Enemy attacked ({r},{c}) → {result}")

            # Update local board
            if result == "HIT":
                my_board[r][c] = "X"
            elif result == "MISS":
                my_board[r][c] = "o"

            print_board(my_board, "Your Board")

        elif msg["msg"] == "WIN":
            print("\n🎉 YOU WIN! 🎉")
            break

        elif msg["msg"] == "LOSE":
            print("\n❌ YOU LOSE ❌")
            break

    s.close()


if __name__ == "__main__":
    main()
