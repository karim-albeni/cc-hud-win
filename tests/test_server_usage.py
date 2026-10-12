import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import hud
import server


class UsageEndpointTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(hud, "DB_PATH", Path(self.tmp.name) / "hud.db")
        self.patch.start()
        server.Handler.token = "t0k"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://localhost:{self.httpd.server_address[1]}/api/usage"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.patch.stop()
        self.tmp.cleanup()

    def get(self, token):
        request = urllib.request.Request(self.url, headers={"X-HUD-Token": token})
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read())

    def test_needs_the_token(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.get("wrong")
        self.assertEqual(raised.exception.code, 401)

    def test_no_file_means_no_windows(self):
        self.assertEqual(self.get("t0k")["windows"], [])

    def test_returns_the_saved_windows(self):
        now = int(time.time())
        data = {"seen_at": now, "rate_limits": {"five_hour": {"used_percentage": 50, "resets_at": now + 3600}}}
        (Path(self.tmp.name) / "usage.json").write_text(json.dumps(data), encoding="utf-8")
        body = self.get("t0k")
        self.assertEqual((body["stale"], body["windows"][0]["used"]), (False, 50.0))
