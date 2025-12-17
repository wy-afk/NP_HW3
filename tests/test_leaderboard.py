import unittest
import tempfile
import json
from pathlib import Path

import server.account_manager as am

class LeaderboardTest(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory to hold players.json
        self.tmpdir = tempfile.TemporaryDirectory()
        self.players_file = Path(self.tmpdir.name) / "players.json"
        # point module constants to temp paths
        am.PLAYERS_FILE = self.players_file
        am.DATA_DIR = Path(self.tmpdir.name)
        # write initial players
        initial = {
            "u1": {"password": "x", "wins": 0, "played": 0},
            "u2": {"password": "y", "wins": 0, "played": 0}
        }
        with self.players_file.open("w", encoding="utf-8") as f:
            json.dump(initial, f)
        # instantiate AccountManager which will load the temp file
        self.acc = am.AccountManager()

    def tearDown(self):
        try:
            self.acc.stop()
        except Exception:
            pass
        self.tmpdir.cleanup()

    def test_record_single_winner(self):
        self.acc.record_result(["u1"], ["u1", "u2"])
        # reload the file
        data = json.loads(self.players_file.read_text(encoding="utf-8"))
        self.assertEqual(int(data["u1"]["played"]), 1)
        self.assertEqual(int(data["u1"]["wins"]), 1)
        self.assertEqual(int(data["u2"]["played"]), 1)
        self.assertEqual(int(data["u2"].get("wins", 0)), 0)

    def test_record_multiple_winners(self):
        self.acc.record_result(["u1", "u2"], ["u1", "u2", "u3"])
        data = json.loads(self.players_file.read_text(encoding="utf-8"))
        # u3 should be created with played=1
        self.assertIn("u3", data)
        self.assertEqual(int(data["u3"]["played"]), 1)
        self.assertEqual(int(data["u1"]["wins"]), 1)
        self.assertEqual(int(data["u2"]["wins"]), 1)

if __name__ == '__main__':
    unittest.main()
