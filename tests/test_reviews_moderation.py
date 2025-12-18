import unittest
import os
import shutil
from server.account_manager import AccountManager
from server.room_manager import RoomManager
from server.lobby_server import LobbyServer

class ReviewsModerationTest(unittest.TestCase):
    def setUp(self):
        # ensure clean data dir for reviews/chat
        data_dir = os.path.join('server', 'data')
        if os.path.isdir(data_dir):
            # remove reviews and chat only
            try:
                rf = os.path.join(data_dir, 'reviews.json')
                if os.path.exists(rf):
                    os.remove(rf)
            except Exception:
                pass
            chatd = os.path.join(data_dir, 'chat')
            if os.path.isdir(chatd):
                try:
                    shutil.rmtree(chatd)
                except Exception:
                    pass
        self.accounts = AccountManager()
        self.rooms = RoomManager()
        self.server = LobbyServer()

    def test_review_permission_and_admin_deletion(self):
        # register normal player and developer
        ok, _ = self.accounts.register('rv_player', 'pw', 'player')
        self.assertTrue(ok)
        ok, _ = self.accounts.register('rv_admin', 'pw', 'player')
        self.assertTrue(ok)
        # make rv_admin an admin flag in players
        self.accounts.players['rv_admin']['role'] = 'admin'
        _save = None
        try:
            from server.account_manager import _save_json, PLAYERS_FILE
            _save_json(PLAYERS_FILE, self.accounts.players)
        except Exception:
            pass

        # try to submit review before playing -> should be rejected by LobbyServer logic
        ls = LobbyServer()
        resp = ls.handle_submit_review_for_test('rv_player', 1, 5, 'Nice')
        self.assertEqual(resp.get('status'), 'error')
        self.assertEqual(resp.get('msg'), 'not_played')

        # simulate a recorded play for game_id=1
        self.accounts._last_game_id = 1
        self.accounts.record_result([], ['rv_player'])
        # now submitting should succeed
        ls.accounts = self.accounts
        resp = ls.handle_submit_review_for_test('rv_player', 1, 4, 'Good')
        self.assertEqual(resp.get('status'), 'ok')
        # admin can delete review
        ls.accounts = self.accounts
        resp = ls.handle_delete_review_for_test('rv_admin', 1, 0)
        self.assertEqual(resp.get('status'), 'ok')

if __name__ == '__main__':
    unittest.main()
