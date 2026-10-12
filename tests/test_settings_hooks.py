import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import settings_hooks as sh

OURS = '"C:/limecrm/cc-hud-win/.venv/Scripts/python.exe" "C:/limecrm/cc-hud-win/hooks/hud_event.py"'
SCRIPT = Path(__file__).resolve().parent.parent / "settings_hooks.py"


PY = "C:/limecrm/cc-hud-win/.venv/Scripts/python.exe"
HOOK = "C:/limecrm/cc-hud-win/hooks/hud_event.py"


def run_cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True, check=False)


class EditTest(unittest.TestCase):
    def test_hook_command_quotes_paths_and_optional_db(self):
        self.assertEqual(sh.hook_command(PY, HOOK, None), OURS)
        self.assertEqual(sh.hook_command(PY, HOOK, "D:/a b/hud.db"), OURS + ' --db "D:/a b/hud.db"')

    def test_adds_one_group_per_event(self):
        result = sh.add_ours({}, OURS)
        self.assertEqual(sorted(result["hooks"]), sorted(sh.EVENTS))
        self.assertEqual(result["hooks"]["Stop"], [{"hooks": [{"type": "command", "command": OURS, "timeout": 3}]}])

    def test_adding_twice_does_not_duplicate(self):
        once = sh.add_ours({}, OURS)
        self.assertEqual(sh.add_ours(once, OURS), once)

    def test_keeps_other_hooks_in_the_same_group(self):
        other = {"type": "command", "command": "notify.exe"}
        settings = {"hooks": {"Stop": [{"hooks": [other, {"type": "command", "command": OURS}]}]}}
        self.assertEqual(sh.remove_ours(settings)["hooks"]["Stop"], [{"hooks": [other]}])

    def test_drops_a_group_left_empty(self):
        settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": OURS}]}]}}
        self.assertEqual(sh.remove_ours(settings)["hooks"]["Stop"], [])

    def test_recognizes_an_old_clone_location(self):
        self.assertTrue(sh.is_ours({"command": '"D:/old/.venv/Scripts/python.exe" "D:/old/hooks/hud_event.py"'}))
        self.assertTrue(sh.is_ours({"command": "D:\\old\\hooks\\hud_event.py --db x"}))
        self.assertFalse(sh.is_ours({"command": "my-hud_event.py.bak"}))

    def test_keeps_unrelated_settings(self):
        result = sh.add_ours({"env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "x"}, "theme": "dark"}, OURS)
        self.assertEqual((result["env"], result["theme"]), ({"GITHUB_PERSONAL_ACCESS_TOKEN": "x"}, "dark"))


class CliTest(unittest.TestCase):
    def test_malformed_file_is_left_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            broken = '{"theme": "dark",}'
            path.write_text(broken, encoding="utf-8")
            out = run_cli("add", path, PY, HOOK)
            self.assertEqual(out.returncode, 1)
            self.assertIn("not valid JSON", out.stderr)
            self.assertEqual(path.read_text(encoding="utf-8"), broken)

    def test_non_utf8_file_is_left_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_bytes(b'{"a": "\xff\xfe"}')
            out = run_cli("add", path, PY, HOOK)
            self.assertEqual(out.returncode, 1)
            self.assertIn("not valid JSON", out.stderr)
            self.assertEqual(path.read_bytes(), b'{"a": "\xff\xfe"}')

    def test_non_object_hooks_is_left_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text('{"hooks": []}', encoding="utf-8")
            for action in (("add", path, PY, HOOK), ("remove", path)):
                out = run_cli(*action)
                self.assertEqual(out.returncode, 1)
                self.assertEqual(path.read_text(encoding="utf-8"), '{"hooks": []}')

    def test_add_builds_the_quoted_command_with_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            run_cli("add", path, PY, HOOK, "--db", "C:/my data/hud.db")
            command = json.loads(path.read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]["command"]
            self.assertEqual(command, OURS + ' --db "C:/my data/hud.db"')

    def test_writes_utf8_without_bom_and_keeps_non_ascii(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text('{"statusLine": "Åsa"}', encoding="utf-8")
            self.assertEqual(run_cli("add", path, PY, HOOK).returncode, 0)
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertEqual(json.loads(raw)["statusLine"], "Åsa")
