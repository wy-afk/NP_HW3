import unittest
import time
from server.account_manager import AccountManager
from server.room_manager import RoomManager


class TestAccountManager(unittest.TestCase):
    def setUp(self):
        self.am = AccountManager()
        # use unique prefix so repeated test runs don't hit existing usernames
        import time
        self._prefix = f"t{int(time.time()*1000)}_"

    def test_register_and_login(self):
        ok, r = self.am.register(self._prefix + "alice", "pw", "player")
        self.assertTrue(ok)
        ok, r = self.am.register(self._prefix + "dev1", "pw", "developer")
        self.assertTrue(ok)

        ok, reason = self.am.login(self._prefix + "alice", "pw", "player")
        self.assertTrue(ok)
        # duplicate login should be rejected
        ok2, reason2 = self.am.login(self._prefix + "alice", "pw", "player")
        self.assertFalse(ok2)
        self.assertEqual(reason2, "already_logged_in")

        # mark disconnected preserves role
        self.am.mark_disconnected(self._prefix + "alice")
        info = self.am.online_users.get(self._prefix + "alice")
        self.assertIsNotNone(info)
        self.assertFalse(info.get("connected"))
        self.assertEqual(info.get("role"), "player")

    def test_record_result_and_leaderboard(self):
        # record some results and ensure leaderboard updated
        self.am.register(self._prefix + "p1", "x", "player")
        self.am.register(self._prefix + "p2", "x", "player")
        self.am.record_result([self._prefix + "p1"], [self._prefix + "p1", self._prefix + "p2"])
        lb = self.am.get_leaderboard()
        self.assertTrue(any(r["username"] == self._prefix + "p1" for r in lb))


class TestRoomManager(unittest.TestCase):
    def setUp(self):
        self.rm = RoomManager()

    def test_create_join_start(self):
        room = self.rm.create_room(1, "alice", "public")
        self.assertEqual(room.host, "alice")
        ok, msg = self.rm.join_room(room.room_id, "bob")
        self.assertTrue(ok)
        # need two players to start
        ok, result = self.rm.start_game(room.room_id)
        # Because GameLauncher isn't attached, start_game should fail
        self.assertFalse(ok)

    def test_private_invites(self):
        room = self.rm.create_room(1, "host", "private")
        ok, msg = self.rm.invite_user(room.room_id, "host", "bob")
        self.assertTrue(ok)
        # bob can accept invite
        ok, msg = self.rm.accept_invite(room.room_id, "bob")
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
