import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

import vscode_bridge as vb

WID = "a" * 32
OTHER = "b" * 32


class WindowFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bridge = Path(self.tmp.name)
        (self.bridge / "windows").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, wid, folders, pids, updated):
        data = {"windowId": wid, "folders": folders, "shellPids": pids, "updatedAt": updated}
        (self.bridge / "windows" / f"{wid}.json").write_text(json.dumps(data), encoding="utf-8")

    def test_loads_fresh_windows(self):
        self.write(WID, ["C:\\work\\my-project"], [101], 1000)
        [window] = vb.load_windows(self.bridge, now=1000)
        self.assertEqual(window, vb.Window(WID, ("C:\\work\\my-project",), frozenset({101}), 1000))

    def test_ignores_windows_older_than_ten_minutes(self):
        self.write(WID, ["C:\\a"], [1], 1000)
        self.assertEqual(vb.load_windows(self.bridge, now=1000 + 601), [])

    def test_ignores_broken_and_misnamed_files(self):
        (self.bridge / "windows" / f"{WID}.json").write_text("{broken", encoding="utf-8")
        data = {"windowId": WID, "folders": ["C:\\a"], "shellPids": [1], "updatedAt": 1000}
        (self.bridge / "windows" / f"{OTHER}.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(vb.load_windows(self.bridge, now=1000), [])

    def test_ignores_folders_that_are_not_a_list(self):
        self.write(WID, "C:\\a", [1], 1000)
        self.assertEqual(vb.load_windows(self.bridge, now=1000), [])

    def test_ignores_boolean_pids(self):
        self.write(WID, ["C:\\a"], [True], 1000)
        self.assertEqual(vb.load_windows(self.bridge, now=1000), [])

    def test_missing_folder_is_no_windows(self):
        self.assertEqual(vb.load_windows(self.bridge / "nope", now=1000), [])


class ChoosingTest(unittest.TestCase):
    a = vb.Window(WID, ("C:\\work\\my-project",), frozenset({101, 102}), 10)
    b = vb.Window(OTHER, ("C:\\work",), frozenset({201}), 20)

    def test_contains_is_case_and_slash_insensitive(self):
        self.assertTrue(vb.contains("C:\\work\\my-project", "c:/WORK/my-project/src"))

    def test_contains_does_not_match_a_prefix_sibling(self):
        self.assertFalse(vb.contains("C:\\work\\my-project", "C:\\work\\my-project-old"))

    def test_folder_prefers_the_most_recent_window(self):
        self.assertEqual(vb.window_for_folder([self.a, self.b], "C:\\work\\my-project"), self.b)

    def test_folder_with_no_match(self):
        self.assertIsNone(vb.window_for_folder([self.a], "D:\\elsewhere"))

    def test_pid_takes_the_nearest_ancestor(self):
        self.assertEqual(vb.window_for_pid([self.a, self.b], [555, 102, 201]), (self.a, 102))

    def test_pid_with_no_match(self):
        self.assertIsNone(vb.window_for_pid([self.a], [1, 2, 3]))


class SendRequestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bridge = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def fake_extension(self, outcome):
        folder = self.bridge / "requests" / WID

        def run():
            for _ in range(100):
                for request in folder.glob("*.json"):
                    claimed = request.with_suffix(".claimed")
                    request.rename(claimed)
                    if outcome != "ok":
                        claimed.with_suffix(".failed").write_text(outcome, encoding="utf-8")
                    claimed.unlink()
                    return
                time.sleep(0.02)

        thread = threading.Thread(target=run)
        thread.start()
        return thread

    def test_claimed_and_done(self):
        thread = self.fake_extension("ok")
        self.assertEqual(vb.send_request({"kind": "focus", "shellPid": 1}, WID, self.bridge, wait=3), "ok")
        thread.join()

    def test_claimed_and_failed(self):
        thread = self.fake_extension("no terminal with shell pid 1")
        result = vb.send_request({"kind": "focus", "shellPid": 1}, WID, self.bridge, wait=3)
        thread.join()
        self.assertEqual(result, "failed: no terminal with shell pid 1")
        self.assertEqual(list((self.bridge / "requests" / WID).iterdir()), [])

    def test_claimed_but_never_finished(self):
        folder = self.bridge / "requests" / WID

        def run():
            for _ in range(100):
                for request in folder.glob("*.json"):
                    request.rename(request.with_suffix(".claimed"))
                    return
                time.sleep(0.02)

        thread = threading.Thread(target=run)
        thread.start()
        result = vb.send_request({"kind": "focus", "shellPid": 1}, WID, self.bridge, wait=0.3)
        thread.join()
        self.assertEqual(result, "failed: timed out waiting for VS Code")
        for leftover in folder.iterdir():
            leftover.unlink()

    def test_unclaimed_request_is_removed(self):
        self.assertEqual(vb.send_request({"kind": "focus", "shellPid": 1}, None, self.bridge, wait=0.2), "unclaimed")
        self.assertEqual(list((self.bridge / "requests" / "any").iterdir()), [])


class RaiseWindowTest(unittest.TestCase):
    def test_refuses_cmd_special_characters(self):
        self.assertIn("cannot pass", vb.raise_window("C:\\work\\R&D") or "")
        self.assertIn("cannot pass", vb.raise_window("C:\\work\\100%") or "")

    def test_refuses_a_missing_folder(self):
        self.assertIn("does not exist", vb.raise_window("C:\\definitely\\not\\here") or "")
