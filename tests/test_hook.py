import contextlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import hud

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "hud_event.py"


class HookTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.dir.name) / "hud.db"
        with mock.patch.object(hud, "DB_PATH", self.db_path):
            hud.connect().close()

    def tearDown(self):
        self.dir.cleanup()

    def fire(self, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(HOOK), "--db", str(self.db_path)],
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            capture_output=True,
            check=False,
            timeout=15,
        )

    def value(self, sql: str):
        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            return db.execute(sql).fetchone()[0]

    def test_swedish_characters_survive(self):
        prompt = "Svara Åsa om fönstret i Göteborg"
        self.fire({"session_id": "s1", "hook_event_name": "UserPromptSubmit", "prompt": prompt})
        self.assertEqual(self.value("SELECT first_prompt FROM items WHERE session_id = 's1'"), prompt)

    def test_prints_nothing_and_exits_zero_on_garbage(self):
        out = subprocess.run(
            [sys.executable, str(HOOK), "--db", str(self.db_path)],
            input=b"not json",
            capture_output=True,
            timeout=15,
            check=False,
        )
        self.assertEqual((out.returncode, out.stdout, out.stderr), (0, b"", b""))

    def test_missing_database_is_a_no_op(self):
        missing = Path(self.dir.name) / "nope.db"
        out = subprocess.run(
            [sys.executable, str(HOOK), "--db", str(missing)],
            input=b'{"session_id":"s1","hook_event_name":"Stop"}',
            capture_output=True,
            check=False,
            timeout=15,
        )
        self.assertEqual(out.returncode, 0)
        self.assertFalse(missing.exists())

    def test_gives_up_on_a_locked_database_and_logs_it(self):
        holder = sqlite3.connect(self.db_path, isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")
        try:
            started = time.monotonic()
            out = self.fire({"session_id": "s1", "hook_event_name": "Stop"})
            elapsed = time.monotonic() - started
        finally:
            holder.execute("ROLLBACK")
            holder.close()
        self.assertEqual((out.returncode, out.stdout, out.stderr), (0, b"", b""))
        self.assertLess(elapsed, 6)
        log = (Path(self.dir.name) / "hook-errors.log").read_text(encoding="utf-8")
        self.assertIn("database is locked", log)

    def test_hud_db_environment_variable_is_the_default(self):
        env = {**os.environ, "HUD_DB": str(self.db_path)}
        subprocess.run(
            [sys.executable, str(HOOK)],
            input=b'{"session_id":"e1","hook_event_name":"Stop"}',
            env=env,
            capture_output=True,
            check=False,
            timeout=15,
        )
        self.assertEqual(self.value("SELECT live FROM items WHERE session_id = 'e1'"), "idle")
