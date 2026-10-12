import tempfile
import unittest
from unittest import mock

import hud
import vscode_bridge as vb


def row(**fields):
    base = {
        "session_id": "5b0bf354-09ca",
        "kind": "interactive",
        "bg_id": None,
        "cwd": None,
        "live": "detached",
        "pid": None,
    }
    return {**base, **fields}


class ResumeTextTest(unittest.TestCase):
    def test_interactive(self):
        self.assertEqual(hud.resume_text(row()), "claude --resume 5b0bf354-09ca")

    def test_background(self):
        self.assertEqual(hud.resume_text(row(kind="background", bg_id="b88d5d23")), "claude attach b88d5d23")

    def test_command_for_cmd(self):
        self.assertEqual(
            hud.resume_command(row(cwd="C:\\work\\my-project")),
            'cd /d "C:\\work\\my-project" && claude --resume 5b0bf354-09ca',
        )


class ResumeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_refuses_a_live_interactive_session(self):
        self.assertEqual(hud.resume(row(cwd=self.cwd, live="idle")), "already open in another tab")

    def test_sends_to_the_window_with_the_folder(self):
        window = vb.Window("a" * 32, (self.cwd,), frozenset(), 1)
        with (
            mock.patch.object(vb, "load_windows", return_value=[window]),
            mock.patch.object(vb, "raise_window", return_value=None) as raised,
            mock.patch.object(vb, "send_request", return_value="ok") as sent,
        ):
            self.assertEqual(hud.resume(row(cwd=self.cwd)), "opened")
        raised.assert_called_once_with(self.cwd)
        request, window_id = sent.call_args.args
        self.assertEqual(request, {"kind": "resume", "cwd": self.cwd, "text": "claude --resume 5b0bf354-09ca"})
        self.assertEqual(window_id, "a" * 32)

    def test_unclaimed_copies_the_command(self):
        with (
            mock.patch.object(vb, "load_windows", return_value=[]),
            mock.patch.object(vb, "raise_window", return_value=None),
            mock.patch.object(vb, "send_request", return_value="unclaimed"),
            mock.patch.object(hud.winplatform, "copy_to_clipboard") as copied,
        ):
            result = hud.resume(row(cwd=self.cwd))
        copied.assert_called_once_with(hud.resume_command(row(cwd=self.cwd)))
        self.assertIn("clipboard", result)

    def test_refused_raise_still_sends_to_an_open_window(self):
        window = vb.Window("a" * 32, (self.cwd,), frozenset(), 1)
        with (
            mock.patch.object(vb, "load_windows", return_value=[window]),
            mock.patch.object(vb, "raise_window", return_value="the code command is not on PATH"),
            mock.patch.object(vb, "send_request", return_value="ok") as sent,
        ):
            self.assertEqual(hud.resume(row(cwd=self.cwd)), "opened")
        sent.assert_called_once()

    def test_refused_raise_without_a_window_sends_nothing(self):
        with (
            mock.patch.object(vb, "load_windows", return_value=[]),
            mock.patch.object(vb, "raise_window", return_value="the code command is not on PATH"),
            mock.patch.object(vb, "send_request") as sent,
            mock.patch.object(hud.winplatform, "copy_to_clipboard"),
        ):
            result = hud.resume(row(cwd=self.cwd))
        sent.assert_not_called()
        self.assertIn("the code command is not on PATH", result)

    def test_missing_folder(self):
        self.assertIn("no longer exists", hud.resume(row(cwd=self.cwd + "\\gone")))


class FocusTest(unittest.TestCase):
    def test_focuses_the_terminal_whose_shell_started_claude(self):
        window = vb.Window("a" * 32, ("C:\\w",), frozenset({101}), 1)
        with (
            mock.patch.object(hud.winplatform, "process_parents", return_value={500: 101, 101: 9}),
            mock.patch.object(vb, "load_windows", return_value=[window]),
            mock.patch.object(vb, "raise_window", return_value=None),
            mock.patch.object(vb, "send_request", return_value="ok") as sent,
        ):
            self.assertEqual(hud.focus_tab(row(pid=500, live="idle", cwd="C:\\w")), "focused")
        self.assertEqual(sent.call_args.args[:2], ({"kind": "focus", "shellPid": 101}, "a" * 32))

    def test_no_pid(self):
        self.assertEqual(hud.focus_tab(row()), "no pid recorded yet")

    def test_falls_back_to_raising_the_folder_window(self):
        window = vb.Window("a" * 32, ("C:\\w",), frozenset({999}), 1)
        with (
            mock.patch.object(hud.winplatform, "process_parents", return_value={500: 101}),
            mock.patch.object(vb, "load_windows", return_value=[window]),
            mock.patch.object(vb, "raise_window", return_value=None) as raised,
        ):
            self.assertEqual(
                hud.focus_tab(row(pid=500, cwd="C:\\w\\src")),
                "terminal not found; raised the VS Code window for its folder",
            )
        raised.assert_called_once_with("C:\\w")

    def test_fallback_reports_why_the_window_could_not_be_raised(self):
        window = vb.Window("a" * 32, (r"C:\w",), frozenset({999}), 1)
        with (
            mock.patch.object(hud.winplatform, "process_parents", return_value={500: 101}),
            mock.patch.object(vb, "load_windows", return_value=[window]),
            mock.patch.object(vb, "raise_window", return_value="the code command is not on PATH"),
        ):
            self.assertEqual(hud.focus_tab(row(pid=500, cwd=r"C:\w")), "the code command is not on PATH")

    def test_no_window_has_the_terminal(self):
        with (
            mock.patch.object(hud.winplatform, "process_parents", return_value={500: 101}),
            mock.patch.object(vb, "load_windows", return_value=[]),
        ):
            self.assertEqual(hud.focus_tab(row(pid=500, cwd="C:\\w")), "no VS Code window has this session's terminal")
