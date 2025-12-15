#!/usr/bin/env python3
import argparse, socket, threading, time, random
from typing import Dict, List
from proto import FramedSocket
from shapes import SHAPES, bag7_rng
from messages import *

WIDTH, HEIGHT = 10, 20
TICK_MS = 500
JOIN_TIMEOUT = 300.0

POWERUP_RATE = 0.10            # 10% chance a piece becomes a Power piece “P”
FREEZE_SECS = 2.0              # FREEZE effect duration on opponent


class PlayerState:
    def __init__(self, name: str):
        self.name = name
        self.board = [[None]*WIDTH for _ in range(HEIGHT)]
        self.active = None             # (piece,x,y,r)
        self.queue: List[str] = []
        self.alive = True
        self.score = 0
        self.lines = 0
        self.cleared_recent: List[int] = []   # rows just cleared (for FX)
        self.freeze_until = 0.0               # if > now, inputs ignored
        self.hold: str = None                 # held piece (or None)
        self.hold_used = False                # whether hold was used this drop
        self.flash_charges = 0                # number of flash charges available (one per 2 lines cleared)
        self._flash_granted = 0               # internal: lines//2 previously granted
        self.last_hold_at = 0.0               # timestamp of last hold (for client FX)
        self.last_flash_at = 0.0              # timestamp of last flash use (for client FX)


class Game:
    def __init__(self, seed: int):
        self.seed = seed
        self.rng = bag7_rng(seed)
        self.players: Dict[str, PlayerState] = {}
        self.lock = threading.Lock()

    def _next_piece(self) -> str:
        """7-bag base + POWERUP_RATE chance to convert to 'P' (power piece)."""
        p = next(self.rng)
        if random.random() < POWERUP_RATE:
            return 'P'  # special: behaves like 2x2 “O” but triggers power effect on lock
        return p

    def spawn_piece(self, ps: PlayerState):
        while len(ps.queue) < 3:
            ps.queue.append(self._next_piece())
        p = ps.queue.pop(0)
        ps.active = (p, 3, 0, 0)
        ps.hold_used = False
        if self.collides(ps, *ps.active):
            ps.alive = False

    def cells(self, p, x, y, r):
        if p == 'P':
            # Power piece: use O shape offsets (2x2)
            return [(x+dx, y+dy) for (dx, dy) in SHAPES['O'][0]]
        return [(x+dx, y+dy) for (dx, dy) in SHAPES[p][r]]

    def collides(self, ps, p, x, y, r):
        for cx, cy in self.cells(p, x, y, r):
            if cx < 0 or cx >= WIDTH or cy < 0 or cy >= HEIGHT:
                return True
            if ps.board[cy][cx] is not None:
                return True
        return False

    def _apply_power_on_lock(self, me: PlayerState, opp: PlayerState, p: str):
        """Simple power-up effects:
           - 'P' on lock: 50% chance freeze opponent, always +50 score boost.
        """
        if p != 'P':
            return
        me.score += 50
        if opp and random.random() < 0.5:
            opp.freeze_until = time.time() + FREEZE_SECS

    def _grant_flash_charges(self, ps: PlayerState):
        # one flash charge per 2 lines cleared (cumulative)
        granted = ps.lines // 2
        if granted > ps._flash_granted:
            ps.flash_charges += (granted - ps._flash_granted)
            ps._flash_granted = granted

    def lock_piece(self, ps: PlayerState, opp: PlayerState):
        p, x, y, r = ps.active
        for cx, cy in self.cells(p, x, y, r):
            if 0 <= cy < HEIGHT:
                ps.board[cy][cx] = p
        new_rows = []
        cleared = 0
        cleared_rows = []
        for row_idx, row in enumerate(ps.board):
            if all(c is not None for c in row):
                cleared += 1
                cleared_rows.append(row_idx)
            else:
                new_rows.append(row)
        for _ in range(cleared):
            new_rows.insert(0, [None]*WIDTH)
        ps.board = new_rows
        ps.lines += cleared
        ps.score += [0, 100, 300, 500, 800][cleared]
        ps.cleared_recent = cleared_rows  # remember for GUI FX (row indices before compaction)

        # Grant flash charges for every 2 lines cleared cumulatively
        if cleared > 0:
            self._grant_flash_charges(ps)

        # Power-up: may freeze opponent etc.
        self._apply_power_on_lock(ps, opp, p)

        self.spawn_piece(ps)

    def do_hold(self, ps: PlayerState):
        """Perform a hold action."""
        if not ps.active or ps.hold_used:
            return
        cur_p, _, _, _ = ps.active
        if ps.hold is None:
            # no held piece → store current and spawn next
            ps.hold = cur_p
            ps.active = None
            self.spawn_piece(ps)
        else:
            # swap held piece and current
            old = ps.hold
            ps.hold = cur_p
            ps.active = (old, 3, 0, 0)
            if self.collides(ps, *ps.active):
                ps.alive = False
        ps.hold_used = True
        ps.last_hold_at = time.time()

    def move(self, ps, dx):
        if not ps.active:
            return
        p, x, y, r = ps.active
        nx = x + dx
        if not self.collides(ps, p, nx, y, r):
            ps.active = (p, nx, y, r)

    def rotate(self, ps):
        if not ps.active:
            return
        p, x, y, r = ps.active
        nr = (r + 1) % 4 if p != 'P' else 0  # power piece doesn't rotate (like O)
        if not self.collides(ps, p, x, y, nr):
            ps.active = (p, x, y, nr)

    def tick(self, ps, opp):
        if not ps.active:
            return
        p, x, y, r = ps.active
        ny = y + 1
        if self.collides(ps, p, x, ny, r):
            self.lock_piece(ps, opp)
        else:
            ps.active = (p, x, ny, r)

    def hard_drop(self, ps, opp):
        if not ps.active:
            return
        p, x, y, r = ps.active
        while not self.collides(ps, p, x, y + 1, r):
            y += 1
        ps.active = (p, x, y, r)
        self.lock_piece(ps, opp)

    def snapshot(self, ps: PlayerState):
        board = [[(c or '.') for c in row] for row in ps.board]
        nowt = time.time()
        return {
            'board': board,
            'active': ps.active,
            'next': ps.queue[:3],
            'score': ps.score,
            'lines': ps.lines,
            'alive': ps.alive,
            'cleared': ps.cleared_recent,
            'freeze_left': max(0.0, ps.freeze_until - nowt),
            'hold': ps.hold,
            'hold_used': ps.hold_used,
            'hold_recent': (nowt - ps.last_hold_at) < 0.8,
            'flash_charges': ps.flash_charges,
            'flash_recent': (nowt - ps.last_flash_at) < 0.8,
        }


class ClientConn:
    def __init__(self, sock: FramedSocket, name: str, role: str):
        self.sock = sock
        self.name = name
        self.role = role


def accept_with_timeout(srv, timeout):
    srv.settimeout(timeout)
    try:
        return srv.accept()
    except Exception:
        return None, None


def handle_game(room_id, host, port, seed,
                db_host=None, db_port=None,  # kept for compatibility, ignored
                lobby_host=None, lobby_notify_port=None):  # ignored
    game = Game(seed)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen()
    print(f"[Game] room={room_id} listening on {host}:{port} seed={seed}")

    def recv_hello(conn: FramedSocket):
        msg = conn.recv_json()
        if msg.get('type') != HELLO:
            raise ValueError('expected HELLO')
        return msg

    clients: List[ClientConn] = []
    spectators: List[dict] = []  # {'sock': FramedSocket, 'name': str}
    clients_lock = threading.Lock()

    deadline = time.time() + JOIN_TIMEOUT

    # ---- Accept players (up to 2) and spectators before start ----
    while len(clients) < 2:
        if time.time() > deadline:
            break
        timeout = 1.0
        c, a = accept_with_timeout(srv, timeout)
        if not c:
            continue

        try:
            fs = FramedSocket(c)
            hello = recv_hello(fs)
            name = hello.get('user')
            is_spectator = hello.get('spectator', False)

            if is_spectator:
                with clients_lock:
                    spectators.append({'sock': fs, 'name': name})
                print(f"[Game] spectator connected: {name} from {a}")
            else:
                role = 'P1' if not clients else 'P2'
                with clients_lock:
                    clients.append(ClientConn(fs, name, role))
                print(f"[Game] client connected {name} role={role} from {a}")
        except Exception as e:
            print("[Game] HELLO error:", e)

    if len(clients) < 2:
        # Not enough players → notify whoever is here and exit
        for cc in clients:
            try:
                cc.sock.send_json({'type': ERROR, 'msg': 'Matchmaking timeout'})
            except Exception:
                pass
            try:
                cc.sock.close()
            except Exception:
                pass
        for sp in spectators:
            try:
                sp['sock'].send_json({'type': ERROR, 'msg': 'Not enough players'})
            except Exception:
                pass
            try:
                sp['sock'].close()
            except Exception:
                pass
        srv.close()
        return

    # ---- We have 2 players → run the game ----
    p1, p2 = clients[0], clients[1]
    ps1 = PlayerState(p1.name)
    ps2 = PlayerState(p2.name)
    game.players[p1.name] = ps1
    game.players[p2.name] = ps2
    game.spawn_piece(ps1)
    game.spawn_piece(ps2)

    # Send WELCOME (players + spectators)
    p1.sock.send_json({
        'type': WELCOME,
        'role': p1.role,
        'seed': seed,
        'you_name': p1.name,
        'opp_name': p2.name
    })
    p2.sock.send_json({
        'type': WELCOME,
        'role': p2.role,
        'seed': seed,
        'you_name': p2.name,
        'opp_name': p1.name
    })

    with clients_lock:
        for sp in spectators:
            try:
                sp['sock'].send_json({
                    'type': WELCOME,
                    'seed': seed,
                    'you_name': p1.name,
                    'opp_name': p2.name
                })
            except Exception:
                pass

    # ---- Input threads for both players ----
    def input_loop(cc: ClientConn, opp_name: str):
        ps = game.players[cc.name]
        try:
            while True:
                msg = cc.sock.recv_json()
                t = msg.get('type')
                if t == INPUT:
                    if time.time() < ps.freeze_until:
                        continue  # frozen, ignore inputs
                    act = msg.get('action')
                    with game.lock:
                        opp = game.players.get(opp_name)
                        if act == LEFT:
                            game.move(ps, -1)
                        elif act == RIGHT:
                            game.move(ps, +1)
                        elif act == ROTATE_CW:
                            game.rotate(ps)
                        elif act == HARD_DROP:
                            game.hard_drop(ps, opp)
                        elif act == 'HOLD':
                            game.do_hold(ps)
                        elif act == 'FLASH':
                            # flash opponent if charge available and opponent not already frozen
                            if ps.flash_charges > 0 and opp:
                                nowt = time.time()
                                if opp.freeze_until <= nowt:
                                    ps.flash_charges -= 1
                                    opp.freeze_until = nowt + FREEZE_SECS
                                    ps.last_flash_at = nowt
        except Exception:
            ps.alive = False
            print(f"[Game] {cc.name} disconnected")

    threading.Thread(target=input_loop, args=(p1, p2.name), daemon=True).start()
    threading.Thread(target=input_loop, args=(p2, p1.name), daemon=True).start()

    # ---- Main tick loop + spectator accept ----
    last = time.monotonic()
    over = False

    try:
        while not over:
            # allow spectators to join during game
            c, a = accept_with_timeout(srv, 0.01)
            if c:
                try:
                    fs = FramedSocket(c)
                    hello = recv_hello(fs)
                    name = hello.get('user')
                    if hello.get('spectator', False):
                        with clients_lock:
                            spectators.append({'sock': fs, 'name': name})
                        print(f"[Game] spectator joined during game: {name} from {a}")
                        try:
                            fs.send_json({
                                'type': WELCOME,
                                'seed': seed,
                                'you_name': p1.name,
                                'opp_name': p2.name
                            })
                        except Exception:
                            pass
                    else:
                        # reject late players
                        try:
                            fs.send_json({'type': ERROR, 'msg': 'Game already in progress'})
                        finally:
                            try:
                                fs.close()
                            except Exception:
                                pass
                except Exception as e:
                    print(f"[Game] error accepting spectator: {e}")

            now = time.monotonic()
            if now - last >= TICK_MS / 1000.0:
                with game.lock:
                    a_ps = game.players[p1.name]
                    b_ps = game.players[p2.name]
                    if a_ps.alive:
                        game.tick(a_ps, b_ps)
                    if b_ps.alive:
                        game.tick(b_ps, a_ps)
                    alive = [ps for ps in game.players.values() if ps.alive]
                    if len(alive) <= 1:
                        over = True

                # send snapshot to players
                for cc in (p1, p2):
                    try:
                        you = game.players.get(cc.name)
                        opp = game.players.get(p1.name if cc.name == p2.name else p2.name)
                        if you:
                            with clients_lock:
                                spec_names = [s.get('name') for s in spectators]
                            cc.sock.send_json({
                                'type': SNAPSHOT,
                                'you': game.snapshot(you),
                                'opp': game.snapshot(opp),
                                'spectators': spec_names,
                                'spectator_count': len(spec_names)
                            })
                            you.cleared_recent = []
                    except Exception:
                        pass

                # send snapshot to spectators
                with clients_lock:
                    dead_idxs = []
                    for i, sp in enumerate(spectators):
                        try:
                            sp['sock'].send_json({
                                'type': SNAPSHOT,
                                'p1': game.snapshot(game.players[p1.name]),
                                'p2': game.snapshot(game.players[p2.name])
                            })
                        except Exception:
                            dead_idxs.append(i)
                    for idx in reversed(dead_idxs):
                        try:
                            dead = spectators.pop(idx)
                            try:
                                dead['sock'].close()
                            except Exception:
                                pass
                        except Exception:
                            pass

                last = now
            else:
                time.sleep(0.01)

        winners = [ps.name for ps in game.players.values() if ps.alive]
        losers = [ps.name for ps in game.players.values() if not ps.alive]

        # Send RESULT to both players
        for cc in (p1, p2):
            try:
                cc.sock.send_json({'type': RESULT, 'winners': winners, 'losers': losers})
            except Exception:
                pass

    finally:
        # Clean-up: close all sockets and server
        for cc in (p1, p2):
            try:
                cc.sock.close()
            except Exception:
                pass
        with clients_lock:
            for sp in spectators:
                try:
                    sp['sock'].close()
                except Exception:
                    pass
        try:
            srv.close()
        except Exception:
            pass


def main(host="0.0.0.0", port=11000, room_id="1", seed=42):
    """Main entry point for tetris_server.py"""
    handle_game(
        room_id=room_id,
        host=host,
        port=port,
        seed=seed,
        db_host=None,
        db_port=None,
        lobby_host=None,
        lobby_notify_port=None,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--room-id", required=True)
    ap.add_argument("--seed", type=int, required=True)
    # keep compatibility but ignore:
    ap.add_argument("--db-host", required=False, default=None)
    ap.add_argument("--db-port", type=int, required=False, default=None)
    ap.add_argument("--lobby-host", required=False, default=None)
    ap.add_argument("--lobby-notify-port", type=int, required=False, default=None)
    args = ap.parse_args()

    handle_game(
        room_id=args.room_id,
        host=args.host,
        port=args.port,
        seed=args.seed,
        db_host=args.db_host,
        db_port=args.db_port,
        lobby_host=args.lobby_host,
        lobby_notify_port=args.lobby_notify_port,
    )
