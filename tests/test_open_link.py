import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import hud

REPO = Path(__file__).resolve().parent.parent


class ParseLinkTest(unittest.TestCase):
    def test_go(self):
        self.assertEqual(hud.parse_link("cc-hud:go/5b0bf354-09ca"), ("go", "5b0bf354-09ca"))

    def test_resume_with_trailing_slash_from_a_browser(self):
        self.assertEqual(hud.parse_link("cc-hud:resume/5b0bf354-09ca/"), ("resume", "5b0bf354-09ca"))

    def test_rejects_anything_else(self):
        for link in (
            "cc-hud:rm/x",
            "cc-hud:go/../../x",
            "cc-hud:go/a&calc",
            "http://x",
            "cc-hud:resume/a",
            "cc-hud:go/5b0bf354\n",
        ):
            with self.subTest(link=link), self.assertRaises(ValueError):
                hud.parse_link(link)


class Args:
    link = "cc-hud:go/5b0bf354-09ca"
    session = "5b0bf354-09ca"


LIVE_ROW = {"session_id": "5b0bf354-09ca", "kind": "interactive", "live": "detached", "bg_id": None}


class NotifyTest(unittest.TestCase):
    def run_open_link(self, result, windowless=True):
        with (
            mock.patch.object(hud, "connect"),
            mock.patch.object(hud, "resolve", return_value=LIVE_ROW),
            mock.patch.object(hud, "resume", return_value=result),
            mock.patch.object(hud.winplatform, "notify") as notify,
            mock.patch.object(sys, "__stdout__", None if windowless else sys.stdout),
            mock.patch("builtins.print"),
        ):
            hud.cmd_open_link(Args())
        return notify

    def test_windowless_failure_is_shown(self):
        self.run_open_link("unclaimed; the resume command is on your clipboard").assert_called_once_with(
            "unclaimed; the resume command is on your clipboard"
        )

    def test_windowless_success_is_silent(self):
        self.run_open_link("opened").assert_not_called()

    def test_console_failure_is_not_shown(self):
        self.run_open_link("unclaimed", windowless=False).assert_not_called()

    def test_go_notifies_too(self):
        with (
            mock.patch.object(hud, "connect"),
            mock.patch.object(hud, "resolve", return_value=LIVE_ROW),
            mock.patch.object(hud, "resume", return_value="no cwd recorded"),
            mock.patch.object(hud.winplatform, "notify") as notify,
            mock.patch.object(sys, "__stdout__", None),
            mock.patch("builtins.print"),
        ):
            hud.cmd_go(Args())
        notify.assert_called_once_with("no cwd recorded")

    def test_resolve_failure_is_shown_then_raised(self):
        with (
            mock.patch.object(hud, "connect"),
            mock.patch.object(hud, "resolve", side_effect=SystemExit("2 sessions match 'x'")),
            mock.patch.object(hud.winplatform, "notify") as notify,
            mock.patch.object(sys, "__stdout__", None),
            self.assertRaises(SystemExit),
        ):
            hud.cmd_go(Args())
        notify.assert_called_once_with("2 sessions match 'x'")


class PipedOutputTest(unittest.TestCase):
    def test_ls_survives_a_legacy_codepage(self):
        name = "fix → ✓ \U0001f680"
        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
            env.update(HUD_DB=str(Path(tmp) / "hud.db"), PYTHONUTF8="0")
            seed = (
                "import hud, sys;db = hud.connect();"
                'db.execute("INSERT INTO items (session_id, name, kind, live, state, created_at, last_activity_at)'
                " VALUES ('5b0bf354-09ca', ?, 'interactive', 'detached', 'open', 1, 1)\", (sys.argv[1],));"
                "db.commit();db.close()"
            )
            subprocess.run([sys.executable, "-c", seed, name], cwd=REPO, env=env, check=True)
            done = subprocess.run([sys.executable, "hud.py", "ls"], cwd=REPO, env=env, capture_output=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(name, done.stdout.decode("utf-8"))
