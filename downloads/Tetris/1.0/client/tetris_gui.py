#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
import threading
import os
import pygame
import sys
import time
from typing import Dict, Any, Optional, Tuple, List

from shapes import SHAPES  # for ghost path
CELL = 28
GAP  = 14
BOARD_W, BOARD_H = 10, 20

FONT_NAME = None
FPS = 60

COLOR_BG      = (16, 16, 24)
COLOR_GRID    = (38, 38, 50)
COLOR_TEXT    = (230, 230, 240)
COLOR_PANEL   = (26, 26, 36)
COLOR_FRAME   = (64, 64, 84)
COLOR_FLASH   = (255, 238, 150)

PIECE_COLORS: Dict[str, Tuple[int,int,int]] = {
    '.': (0, 0, 0),
    'I': (0, 210, 240),
    'O': (240, 240, 0),
    'T': (160, 0, 240),
    'S': (0, 240, 100),
    'Z': (240, 0, 80),
    'J': (0, 80, 240),
    'L': (240, 160, 0),
    'P': (250, 120, 255),   # Power piece
}

def draw_rect(surf, color, x, y, w, h, radius=6):
    pygame.draw.rect(surf, color, pygame.Rect(x, y, w, h), border_radius=radius)

class GUI:
    def __init__(self, sock, spectator=False):
        # Try to center the window on screen so it is visible (avoids off-screen
        # windows on multi-monitor setups). Also prefer not to use SCALED on
        # Wayland because some SDL builds produce tiny logical windows there.
        os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
        wayland = bool(os.environ.get("WAYLAND_DISPLAY"))

        pygame.init()
        pygame.display.set_caption("Tetris — Versus Mode")
        self.sock = sock
        self.running = True
        self.spectator = spectator
        self.last_result: Optional[Dict[str, Any]] = None

        # Names (arrive in WELCOME)
        self.you_name = "P1"
        self.opp_name = "P2"

        # For overlays
        self.countdown_start: Optional[float] = None
        self.finish_time: Optional[float] = None
        self.finish_text: Optional[str] = None

        # State updated by network thread
        self.state_you: Dict[str, Any] = {}
        self.state_opp: Dict[str, Any] = {}
        # Spectator list for this match (updated from server snapshots)
        self.spectators: List[str] = []
        self.spectator_count: int = 0

        # FX memory: rows flashing per board
        self.flash_rows_you: List[Tuple[int,float]] = []
        self.flash_rows_opp: List[Tuple[int,float]] = []
        self.FLASH_MS = 200
        # Hold / flash animations
        self.hold_anims: List[float] = []   # timestamps of recent hold events
        self.flash_anims: List[float] = []  # timestamps of recent flash events
        self.ANIM_MS = 700

        # Layout
        board_w_px = BOARD_W * CELL
        board_h_px = BOARD_H * CELL
        side_panel_w = 7 * CELL
        pad = 24

        total_w = (board_w_px * 2) + (side_panel_w * 2) + (pad * 4) + GAP
        total_h = board_h_px + pad * 2

        # Use SCALED where available (improves DPI scaling on many setups),
        # but avoid SCALED under Wayland which sometimes results in tiny windows
        # with certain SDL2 builds. Always allow resizing.
        flags = pygame.RESIZABLE
        if not wayland:
            try:
                flags |= pygame.SCALED
            except Exception:
                pass

        # Ensure environment positions window centered (SDL respects this)
        os.environ.setdefault("SDL_VIDEO_WINDOW_POS", "center")

        self.screen = pygame.display.set_mode((total_w, total_h), flags)

        # Final sanity: if the created surface is unexpectedly small, scale up
        # the displayed surface to a reasonable minimum so content is visible.
        try:
            w, h = self.screen.get_size()
            min_w, min_h = 800, 480
            if w < min_w or h < min_h:
                # Attempt to resize to sane defaults
                self.screen = pygame.display.set_mode((max(w, min_w), max(h, min_h)), flags)
        except Exception:
            pass
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont(FONT_NAME, 18)
        self.font_b = pygame.font.SysFont(FONT_NAME, 22, bold=True)
        self.font_big = pygame.font.SysFont(FONT_NAME, 64, bold=True)

        # Regions
        x = pad
        self.rect_you_panel = pygame.Rect(x, pad, side_panel_w, board_h_px)
        x += side_panel_w
        self.rect_you_board = pygame.Rect(x, pad, board_w_px, board_h_px)
        x += board_w_px + GAP
        self.rect_opp_board = pygame.Rect(x, pad, board_w_px, board_h_px)
        x += board_w_px
        self.rect_opp_panel = pygame.Rect(x, pad, side_panel_w, board_h_px)

        # Input rate-limit
        self.last_input_ts = 0.0
        self.input_cooldown = 0.03
        # Pause state
        self.paused = False
        # FPS display
        self.show_fps = True

        # Start network reader
        self._net_err: Optional[str] = None
        self.net_th = threading.Thread(target=self._net_loop, daemon=True)
        self.net_th.start()

    # ---------------------- Networking ----------------------
    def _net_loop(self):
        try:
            while self.running:
                msg = self.sock.recv_json()
                t = msg.get("type")
                if t == "WELCOME":
                    self.you_name = msg.get("you_name", self.you_name)
                    self.opp_name = msg.get("opp_name", self.opp_name)
                    self.countdown_start = time.time()
                elif t == "SNAPSHOT":
                    if self.spectator:
                        # Spectator receives p1 and p2
                        p1 = msg.get("p1") or {}
                        p2 = msg.get("p2") or {}
                        for y in (p1.get("cleared") or []):
                            self.flash_rows_you.append((y, time.time()))
                        for y in (p2.get("cleared") or []):
                            self.flash_rows_opp.append((y, time.time()))
                        self.state_you = p1
                        self.state_opp = p2
                    else:
                        # Player receives you and opp
                        you = msg.get("you") or {}
                        opp = msg.get("opp") or {}
                        nowt = time.time()
                        for y in (you.get("cleared") or []):
                            self.flash_rows_you.append((y, nowt))
                        for y in (opp.get("cleared") or []):
                            self.flash_rows_opp.append((y, nowt))
                        self.state_you = you
                        self.state_opp = opp
                        # spectators info included in player snapshots
                        specs = msg.get('spectators') or []
                        try:
                            self.spectators = list(specs)
                            self.spectator_count = int(msg.get('spectator_count', len(self.spectators)))
                        except Exception:
                            self.spectators = specs
                            self.spectator_count = len(self.spectators)
                        # hold animation
                        if you.get('hold_recent'):
                            self.hold_anims.append(nowt)
                        if opp.get('hold_recent'):
                            self.hold_anims.append(nowt)
                        # flash animation
                        if you.get('flash_recent'):
                            self.flash_anims.append(nowt)
                        if opp.get('flash_recent'):
                            self.flash_anims.append(nowt)
                elif t == "RESULT":
                    self.last_result = msg
                    win = False
                    if msg.get("winners"):
                        win = self.you_name in msg["winners"]
                    self.finish_text = "YOU WIN 🎉" if win else "YOU LOSE 💀"
                    self.finish_time = time.time()
                elif t == "ERROR":
                    self._net_err = msg.get("msg", "Server error")
                    self.finish_text = "ERROR"
                    self.finish_time = time.time()
        except Exception as e:
            self._net_err = f"Network closed: {e}"
            self.finish_text = "DISCONNECTED"
            self.finish_time = time.time()

    def _send_input(self, action: str):
        now = time.time()
        if (now - self.last_input_ts) < self.input_cooldown:
            return
        if self.spectator:
            return  # spectators cannot send inputs
        try:
            # disable inputs during countdown
            if self._countdown_secs_left() > 0:
                return
            # disable inputs if frozen
            if (self.state_you.get("freeze_left") or 0) > 0.01:
                return
            self.sock.send_json({"type": "INPUT", "action": action})
            self.last_input_ts = now
        except Exception as e:
            self._net_err = f"Send failed: {e}"
            self.finish_text = "DISCONNECTED"
            self.finish_time = time.time()

    # ---------------------- Rendering helpers -----------------------
    def _slot(self, rect_board: pygame.Rect, x, y):
        return rect_board.x + x * CELL, rect_board.y + y * CELL

    def _draw_grid_base(self, rect_board: pygame.Rect):
        draw_rect(self.screen, COLOR_BG, rect_board.x, rect_board.y, rect_board.w, rect_board.h, radius=12)
        for cx in range(BOARD_W + 1):
            x = rect_board.x + cx * CELL
            pygame.draw.line(self.screen, COLOR_GRID, (x, rect_board.y), (x, rect_board.y + rect_board.h), 1)
        for cy in range(BOARD_H + 1):
            y = rect_board.y + cy * CELL
            pygame.draw.line(self.screen, COLOR_GRID, (rect_board.x, y), (rect_board.x + rect_board.w, y), 1)

    def _draw_locked(self, rect_board: pygame.Rect, state: Dict[str, Any]):
        board = state.get("board") or []
        for y, row in enumerate(board):
            for x, cell in enumerate(row):
                if not cell or cell == '.': continue
                color = PIECE_COLORS.get(cell, (200, 200, 200))
                bx, by = self._slot(rect_board, x, y)
                draw_rect(self.screen, color, bx + 1, by + 1, CELL - 2, CELL - 2, radius=6)

    def _active_cells(self, state: Dict[str, Any]) -> List[Tuple[int,int]]:
        active = state.get("active")
        if not active: return []
        p, ax, ay, r = active
        shape = SHAPES['O'][0] if p == 'P' else SHAPES[p][r]
        return [(ax+dx, ay+dy) for (dx,dy) in shape]

    def _collides(self, board, cells: List[Tuple[int,int]]):
        for (cx,cy) in cells:
            if cx < 0 or cx >= BOARD_W or cy < 0 or cy >= BOARD_H:
                return True
            if board[cy][cx] not in (None, '.'):
                return True
        return False

    def _draw_ghost(self, rect_board: pygame.Rect, state: Dict[str, Any]):
        board = state.get("board") or []
        #normalize board to None/char
        nb = [[(None if c in (None,'.') else c) for c in row] for row in board]
        cells = self._active_cells(state)
        if not cells: return
        # rop cells down until collision
        dy = 0
        while True:
            test = [(x, y+dy+1) for (x,y) in cells]
            if self._collides(nb, test): break
            dy += 1
        #draw ghost one row above collision
        ghost = [(x, y+dy) for (x,y) in cells]
        for (x,y) in ghost:
            if 0 <= x < BOARD_W and 0 <= y < BOARD_H:
                gx, gy = self._slot(rect_board, x, y)
                pygame.draw.rect(self.screen, (255,255,255), pygame.Rect(gx+4, gy+4, CELL-8, CELL-8), width=1, border_radius=5)

    def _draw_active(self, rect_board: pygame.Rect, state: Dict[str, Any]):
        active = state.get("active")
        if not active: return
        p, ax, ay, r = active
        color = PIECE_COLORS.get(p, (220, 220, 220))
        shape = SHAPES['O'][0] if p == 'P' else SHAPES[p][r]
        for (dx,dy) in shape:
            x, y = ax+dx, ay+dy
            if 0 <= x < BOARD_W and 0 <= y < BOARD_H:
                bx, by = self._slot(rect_board, x, y)
                draw_rect(self.screen, color, bx + 1, by + 1, CELL - 2, CELL - 2, radius=6)

    def _draw_flash(self, rect_board: pygame.Rect, flashes: List[Tuple[int,float]]):
        now = time.time()
        alive = []
        for (row_idx, t0) in flashes:
            if (now - t0) * 1000.0 < self.FLASH_MS:
                # flash this row
                y = rect_board.y + row_idx * CELL
                draw_rect(self.screen, COLOR_FLASH, rect_board.x+1, y+1, rect_board.w-2, CELL-2, radius=6)
                alive.append((row_idx, t0))
        flashes[:] = alive  # keep live ones

    def _draw_panel(self, rect_panel: pygame.Rect, name: str, state: Dict[str, Any], title: str):
        draw_rect(self.screen, COLOR_PANEL, rect_panel.x, rect_panel.y, rect_panel.w, rect_panel.h, radius=12)
        header = self.font_b.render(title, True, COLOR_TEXT)
        self.screen.blit(header, (rect_panel.x, rect_panel.y - 26))

        # Name + stats
        name_s = self.font_b.render(name, True, COLOR_TEXT)
        self.screen.blit(name_s, (rect_panel.x + 16, rect_panel.y + 16))
        score = state.get("score", 0); lines = state.get("lines", 0)
        alive = state.get("alive", True)
        stat = self.font.render(f"Score {score}   Lines {lines}" + ("" if alive else "  (KO)"), True, COLOR_TEXT)
        self.screen.blit(stat, (rect_panel.x + 16, rect_panel.y + 46))

        # Freeze indicator (if any)
        fr = state.get("freeze_left", 0.0)
        if fr and fr > 0.01:
            t = self.font.render(f"FROZEN {fr:0.1f}s", True, (180,220,255))
            self.screen.blit(t, (rect_panel.x + 16, rect_panel.y + 74))

        # Next pieces
        self._draw_next(rect_panel, state, "NEXT")
        # Hold box
        self._draw_hold(rect_panel, state)

    def _draw_next(self, panel: pygame.Rect, state: Dict[str, Any], title: str):
        draw_rect(self.screen, COLOR_FRAME, panel.x + 10, panel.y + 110, panel.w - 20, 160, radius=10)
        t = self.font_b.render(title, True, COLOR_TEXT)
        self.screen.blit(t, (panel.x + 18, panel.y + 116))

        queue = state.get("next") or []
        mc = 18
        ox = panel.x + 18
        oy = panel.y + 146
        for i, p in enumerate(queue[:3]):
            color = PIECE_COLORS.get(p, (220, 220, 220))
            grid = _icon_shape(p)
            for (gx, gy) in grid:
                x = ox + gx * mc
                y = oy + i * (mc * 3) + gy * mc
                draw_rect(self.screen, color, x, y, mc - 2, mc - 2, radius=5)
            if p == 'P':
                tag = self.font.render("PU", True, (255,255,255))
                self.screen.blit(tag, (ox + 4*mc + 6, oy + i * (mc*3)))

    def _draw_hold(self, panel: pygame.Rect, state: Dict[str, Any]):
        # Draw hold box above NEXT
        x = panel.x + 10
        y = panel.y + 110 - 86
        w = panel.w - 20
        h = 70
        draw_rect(self.screen, COLOR_FRAME, x, y, w, h, radius=8)
        t = self.font_b.render("HOLD", True, COLOR_TEXT)
        self.screen.blit(t, (x + 8, y + 6))
        held = state.get('hold')
        if held:
            mc = 18
            ox = x + 12
            oy = y + 32
            grid = _icon_shape(held)
            color = PIECE_COLORS.get(held, (200,200,200))
            for (gx, gy) in grid:
                draw_rect(self.screen, color, ox + gx*mc, oy + gy*mc, mc-2, mc-2, radius=4)
        else:
            t2 = self.font.render("(empty)", True, (180,180,180))
            self.screen.blit(t2, (x + 12, y + 36))
        # Flash charges indicator (top-right)
        charges = state.get('flash_charges', 0)
        ch_s = self.font_b.render(str(charges), True, (255,200,120))
        self.screen.blit(ch_s, (x + w - 28, y + 8))

    def _overlay_center(self, text: str, alpha: int = 210):
        w, h = self.screen.get_size()
        shade = pygame.Surface((w, h), pygame.SRCALPHA)
        shade.fill((0, 0, 0, alpha))
        self.screen.blit(shade, (0, 0))
        surf = self.font_big.render(text, True, (255,255,255))
        rect = surf.get_rect(center=(w//2, h//2))
        self.screen.blit(surf, rect.topleft)

    def _countdown_secs_left(self) -> float:
        if self.countdown_start is None: return 0.0
        elapsed = time.time() - self.countdown_start
        remain = max(0.0, 3.0 - elapsed)
        return remain

    # ---------------------- Main loop -----------------------
    def loop(self):
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.running = False
                    elif event.key == pygame.K_p:
                        # pause/resume
                        self.paused = not self.paused
                    elif event.key == pygame.K_c:
                        # hold
                        self._send_input("HOLD")
                    elif event.key == pygame.K_LEFT:
                        if not self.paused:
                            self._send_input("LEFT")
                    elif event.key == pygame.K_RIGHT:
                        if not self.paused:
                            self._send_input("RIGHT")
                    elif event.key == pygame.K_UP:
                        if not self.paused:
                            self._send_input("CW")
                    elif event.key == pygame.K_DOWN:
                        if not self.paused:
                            self._send_input("HD")
                    elif event.key == pygame.K_f:
                        # manual flash trigger (for testing) - consumes a charge server-side
                        self._send_input("FLASH")

            self.screen.fill(COLOR_BG)

            # Panels + boards with name tags
            self._draw_panel(self.rect_you_panel, self.you_name, self.state_you, "YOU")
            self._draw_panel(self.rect_opp_panel, self.opp_name, self.state_opp, "OPPONENT")

            # Boards
            self._draw_grid_base(self.rect_you_board)
            self._draw_grid_base(self.rect_opp_board)

            # Flash FX before drawing blocks
            self._draw_flash(self.rect_you_board, self.flash_rows_you)
            self._draw_flash(self.rect_opp_board, self.flash_rows_opp)

            # Ghost then active, then locked (ghost under active)
            self._draw_locked(self.rect_you_board, self.state_you)
            self._draw_ghost(self.rect_you_board, self.state_you)
            self._draw_active(self.rect_you_board, self.state_you)

            self._draw_locked(self.rect_opp_board, self.state_opp)
            self._draw_ghost(self.rect_opp_board, self.state_opp)
            self._draw_active(self.rect_opp_board, self.state_opp)

            # Countdown overlay at start
            cd = self._countdown_secs_left()
            if cd > 0:
                text = str(int(cd)+1) if cd > 0.1 else "GO!"
                self._overlay_center(text, alpha=140)

            # Pause overlay
            if self.paused:
                self._overlay_center("Paused — press p to resume", alpha=180)

            # FPS readout
            if self.show_fps:
                fps = int(self.clock.get_fps())
                fps_s = self.font.render(f"FPS: {fps}", True, (200,200,200))
                self.screen.blit(fps_s, (10, 10))

            # Spectator panel (show count and up to 4 names)
            if not self.spectator:
                try:
                    spec_w = 220
                    spec_h = 76
                    sx = self.rect_opp_panel.x + (self.rect_opp_panel.w - spec_w) // 2
                    sy = self.rect_opp_panel.y + self.rect_opp_panel.h - spec_h - 12
                    draw_rect(self.screen, (28,28,40), sx, sy, spec_w, spec_h, radius=8)
                    title = self.font_b.render(f"Spectators ({self.spectator_count})", True, COLOR_TEXT)
                    self.screen.blit(title, (sx + 8, sy + 6))
                    # names (comma separated, wrap if needed)
                    names = ", ".join(self.spectators[:6])
                    nm_s = self.font.render(names or "(none)", True, (200,200,200))
                    self.screen.blit(nm_s, (sx + 8, sy + 34))
                except Exception:
                    pass

            # Draw hold / flash animations (simple pulsing indicator)
            nowt = time.time()
            # hold anim: draw a ring near hold box
            alive_h = []
            for t0 in self.hold_anims:
                if (nowt - t0) * 1000.0 < self.ANIM_MS:
                    # pulse size
                    pct = (nowt - t0) * 1000.0 / self.ANIM_MS
                    radius = int(6 + pct * 18)
                    hx = self.rect_you_panel.x + 10 + (self.rect_you_panel.w - 20) - 20
                    hy = self.rect_you_panel.y + 110 - 86 + 10
                    pygame.draw.circle(self.screen, (200,200,255), (hx, hy), radius, width=3)
                    alive_h.append(t0)
            self.hold_anims[:] = alive_h

            # flash anim: draw bolt over opponent panel
            alive_f = []
            for t0 in self.flash_anims:
                if (nowt - t0) * 1000.0 < self.ANIM_MS:
                    pct = 1.0 - ((nowt - t0) * 1000.0 / self.ANIM_MS)
                    alpha = int(180 * pct)
                    bx = self.rect_opp_panel.centerx
                    by = self.rect_opp_panel.y + 40
                    surf = pygame.Surface((80, 40), pygame.SRCALPHA)
                    surf.fill((0,0,0,0))
                    # lightning shape
                    pygame.draw.polygon(surf, (255, 240, 120, alpha), [(10,0),(30,0),(20,18),(40,18),(20,40),(30,20),(10,20)])
                    self.screen.blit(surf, (bx-40, by-10))
                    alive_f.append(t0)
            self.flash_anims[:] = alive_f

            # Finish overlay (show 1.5s then let client return)
            if self.finish_time:
                if (time.time() - self.finish_time) < 1.5 and self.finish_text:
                    self._overlay_center(self.finish_text, alpha=140)
                else:
                    self.running = False

            pygame.display.flip()
            self.clock.tick(FPS)

        pygame.quit()
        return

def _icon_shape(p: str):
    if p == 'I': return [(0,0),(1,0),(2,0),(3,0)]
    if p == 'O': return [(0,0),(1,0),(0,1),(1,1)]
    if p == 'T': return [(0,0),(1,0),(2,0),(1,1)]
    if p == 'S': return [(1,0),(2,0),(0,1),(1,1)]
    if p == 'Z': return [(0,0),(1,0),(1,1),(2,1)]
    if p == 'J': return [(0,0),(0,1),(1,1),(2,1)]
    if p == 'L': return [(2,0),(0,1),(1,1),(2,1)]
    if p == 'P': return [(0,0),(1,0),(0,1),(1,1)]  # power icon (2x2)
    return []
