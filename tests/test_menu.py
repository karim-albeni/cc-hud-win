import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import hud


class MenuTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(hud, "DB_PATH", root / "hud.db"),
            mock.patch.object(hud, "TOKEN_PATH", root / "token"),
        ]
        for p in self.patches:
            p.start()
        self.db = hud.connect()
        now = int(time.time())
        rows = [
            ("waiting", "open", "waiting", None, "Svara Åsa & co"),
            ("working", "open", "working", None, "build"),
            ("red", "open", "detached", "failed", "fix CI"),
            ("merged", "open", "detached", "merged", "after merge"),
            ("plain", "open", "detached", None, "someday"),
            ("finished", "done", "detached", None, "old"),
        ]
        # Distinct times, oldest first, so the menu's ORDER BY last_activity_at gives a fixed order.
        for offset, (sid, state, live, alert, name) in enumerate(rows):
            self.db.execute(
                "INSERT INTO items (session_id, state, live, pr_alert, name, last_activity_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (sid, state, live, alert, name, now - 120 + offset),
            )
        self.db.execute("INSERT INTO steps (thread_id, pos, title) VALUES ('merged', 1, 'release it')")
        self.db.commit()

    def tearDown(self):
        self.db.close()
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def ids(self, data, heading):
        return [i["id"] for s in data["sections"] if s["heading"] == heading for i in s["items"]]

    def test_groups_like_the_swiftbar_menu(self):
        data = hud.menu(self.db)
        self.assertEqual(self.ids(data, "Needs you"), ["waiting", "red"])
        self.assertEqual(self.ids(data, "Working"), ["working"])
        self.assertEqual(self.ids(data, "Open, no tab"), ["merged", "plain"])

    def test_counts_and_board_link(self):
        data = hud.menu(self.db)
        self.assertEqual((data["needs"], data["waiting"], data["open"]), (2, 1, 5))
        self.assertTrue(data["board"].startswith("http://localhost:7777/#t="))

    def test_titles_keep_swedish_and_ampersands(self):
        item = hud.menu(self.db)["sections"][0]["items"][0]
        self.assertEqual((item["title"], item["age"]), ("Svara Åsa & co", "2m"))
