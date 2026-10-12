import json
import subprocess
import unittest
from unittest import mock

import hud


class LiveSessionsTest(unittest.TestCase):
    def test_decodes_swedish_names_as_utf8(self):
        payload = json.dumps([{"sessionId": "s1", "name": "Svara Åsa"}], ensure_ascii=False)
        done = subprocess.CompletedProcess([], 0, stdout=payload, stderr="")
        with mock.patch.object(hud.subprocess, "run", return_value=done) as run:
            self.assertEqual(hud.live_sessions(), [{"sessionId": "s1", "name": "Svara Åsa"}])
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertEqual(kwargs["creationflags"], hud.winplatform.NO_WINDOW)

    def test_none_when_claude_fails(self):
        done = subprocess.CompletedProcess([], 1, stdout="", stderr="boom")
        with mock.patch.object(hud.subprocess, "run", return_value=done):
            self.assertIsNone(hud.live_sessions())
