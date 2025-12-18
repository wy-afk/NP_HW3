PYTHON=python3

.PHONY: demo start-server start-client1 start-client2

demo:
	@echo "Starting demo helper (uses tmux if available)"
	@bash run_demo.sh

start-server:
	$(PYTHON) server/lobby_server.py

start-client1:
	$(PYTHON) player_client/lobby_client.py

start-client2:
	$(PYTHON) player_client/lobby_client.py
