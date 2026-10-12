import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import winplatform


class AncestorsTest(unittest.TestCase):
    def test_walks_nearest_parent_first(self):
        parents = {30: 20, 20: 10, 10: 4}
        self.assertEqual(winplatform.ancestors(30, parents), [20, 10, 4])

    def test_stops_where_the_table_ends(self):
        self.assertEqual(winplatform.ancestors(30, {30: 20}), [20])

    def test_stops_at_pid_zero(self):
        self.assertEqual(winplatform.ancestors(30, {30: 20, 20: 0}), [20])

    def test_stops_on_a_cycle_from_a_reused_pid(self):
        self.assertEqual(winplatform.ancestors(30, {30: 20, 20: 10, 10: 30}), [20, 10])

    def test_caps_the_chain(self):
        parents = {n: n + 1 for n in range(1, 100)}
        self.assertEqual(len(winplatform.ancestors(1, parents)), winplatform.MAX_CHAIN)

    def test_unknown_pid_has_no_ancestors(self):
        self.assertEqual(winplatform.ancestors(99, {}), [])


class ProcessParentsTest(unittest.TestCase):
    def test_knows_this_process_and_its_parent(self):
        self.assertEqual(winplatform.process_parents()[os.getpid()], os.getppid())


class WindowlessTest(unittest.TestCase):
    def test_redirects_when_there_is_no_console(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "snapshot.log"
            with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None):
                winplatform.log_when_windowless(log)
                print("hello from pythonw", file=sys.stderr)
                sys.stderr.close()
            self.assertIn("hello from pythonw", log.read_text(encoding="utf-8"))

    def test_rotates_a_log_over_one_megabyte(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "snapshot.log"
            log.write_bytes(b"x" * (winplatform.MAX_LOG_BYTES + 1))
            Path(tmp, "snapshot.log.1").write_text("older")
            with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None):
                winplatform.log_when_windowless(log)
                sys.stdout.close()
            self.assertEqual(Path(tmp, "snapshot.log.1").stat().st_size, winplatform.MAX_LOG_BYTES + 1)
            self.assertEqual(log.stat().st_size, 0)

    def test_keeps_a_small_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "snapshot.log"
            log.write_text("small")
            with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None):
                winplatform.log_when_windowless(log)
                sys.stdout.close()
            self.assertEqual(log.read_text(), "small")
            self.assertFalse(Path(tmp, "snapshot.log.1").exists())

    def test_leaves_a_console_alone(self):
        before = sys.stdout
        winplatform.log_when_windowless(Path("unused.log"))
        self.assertIs(sys.stdout, before)
        self.assertFalse(Path("unused.log").exists())
