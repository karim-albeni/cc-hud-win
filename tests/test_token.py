import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock

import hud
import server


class TokenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "token"
        self.patch = mock.patch.object(hud, "TOKEN_PATH", self.path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_creates_a_token_once_and_keeps_it(self):
        first = hud.token()
        self.assertGreaterEqual(len(first), 40)
        self.assertEqual(hud.token(), first)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["token"])

    def test_an_empty_token_file_is_replaced(self):
        self.path.write_text("  \n", encoding="utf-8")
        self.assertGreaterEqual(len(hud.token()), 40)


class EmptyTokenServerTest(unittest.TestCase):
    def test_serve_refuses_to_start_without_a_token(self):
        with mock.patch.object(hud, "token", return_value=""), self.assertRaises(RuntimeError):
            server.serve(0)

    def test_an_empty_server_token_signs_nobody_in(self):
        handler = server.Handler.__new__(server.Handler)
        handler.headers = Message()
        handler.headers["X-HUD-Token"] = ""
        with mock.patch.object(server.Handler, "token", ""):
            self.assertFalse(handler._signed_in())
