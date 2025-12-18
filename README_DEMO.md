TA Demo — One-line quick start

Purpose: quick, copy-paste commands for TAs to run a local demo (lobby server + two player CLIs).

Assumptions
- You are in the repository root: `/home/wy/NP/HW3`
- Python 3 is installed and available as `python3`

Quick start (copy/paste)

# Start lobby server in one terminal
cd /home/wy/NP/HW3
python3 server/lobby_server.py

# Start player 1 in another terminal
cd /home/wy/NP/HW3
python3 player_client/lobby_client.py

# Start player 2 in another terminal
cd /home/wy/NP/HW3
python3 player_client/lobby_client.py

Helper script (tmux)
If you have `tmux` installed you can use the helper to open the server and two clients in panes:

bash scripts/ta_run_demo.sh

Makefile target
You can also run:

make demo

which will attempt to run the same helper.

- Notes
- Use the top-level menu options (1: Browse Games, 2: Install Game, 3: Launch Game, 4: Developer Mode).
- Developer upload expects a zip containing `game.json` with `name` and `version` fields.
- Server persists catalog and leaderboard in `server/data/`.
