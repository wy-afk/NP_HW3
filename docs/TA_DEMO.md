# TA Demo Quick Run (seeded per-player downloads)

The repository includes seeded per-player copies of the demo packages under:


These are convenient copies so a grader can run both players on the same host without clobbering a single shared `downloads/` folder.

Quick steps (manual):

1. Start the Lobby Server (in a terminal):

```bash
cd /home/wy/NP/HW3
python3 server/lobby_server.py
```
# TA Quick Demo Checklist (One Page)

Purpose: run a minimal end-to-end demo (lobby server + two players) showing
browse → install → start, plus developer upload. These steps assume you're
in the repository root `/home/wy/NP/HW3` on Linux with Python 3 installed.

Prerequisites
- Python 3 available as `python3`.
- Port availability for the lobby server (default TCP ports used by the project).
- Seeded downloads exist (`downloads/Player1`, `downloads/Player2`) — no extra setup needed.

Quick start (copy-paste)

1) Start the lobby server (Terminal A):

```bash
cd /home/wy/NP/HW3
python3 server/lobby_server.py
```

2) Start Player 1 client (Terminal B):

```bash
cd /home/wy/NP/HW3
python3 player_client/lobby_client.py
```

3) Start Player 2 client (Terminal C):

```bash
cd /home/wy/NP/HW3
python3 player_client/lobby_client.py
```

Alternative (tmux): the repo includes a helper script that opens server + two
clients in tmux panes when available:

```bash
bash scripts/ta_run_demo.sh
```

Minimal demo flow (what to click/type)
- On each client, follow the text menu.
- Top-level menu: choose `1. Browse Games` to view the catalog.
- To install a game: `2. Install Game` → pick the game number → confirm. The client will show download progress.
- To start/play a game quickly: `3. Launch Game` → pick a game number → choose to host (create room) or join. When hosting, the client will auto-download the missing per-user package and launch the game client using the manifest `game.json` start command.

Developer flow (quick test)
- On any client choose `4. Developer Mode` → `Upload Game`.
- The client will list `.zip` files in the current directory or allow you to paste a path.
- Select a `.zip` that contains a `game.json` manifest (fields: `name`, `version`, optional `start_cmd`). The client reads the manifest and asks for confirmation before streaming the zip to the server.
- Server response: successful publish prints assigned game id and becomes immediately available in `Browse Games`.

Expected console outputs (sanity checks)
- Server: lines indicating it received an upload, published to `server/game_storage/<name>/<version>`, and saved `server/data/games.json`.
- Client: download progress messages (`received X / total Y bytes`) and final extraction success.

If something fails
- Check the server terminal for error traces.
- Ensure the zip contains a valid `game.json` and that you used the repository root when launching clients so relative paths resolve.

Quick verification checklist (tick during demo)
- [ ] Server started and listening.
- [ ] Player 1 and Player 2 clients connected.
- [ ] Browse shows at least one game.
- [ ] Player installs a game and progress is displayed.
- [ ] Player starts the game; client auto-downloads missing package and launches.
- [ ] Developer upload succeeded and new game appears in browse list.

That's it — this single page gives the exact commands and the minimal menu steps a TA needs for the assignment demo.
