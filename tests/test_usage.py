import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import usage

NOW = 1_791_804_000


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "usage.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, seen_at, rate_limits):
        self.path.write_text(json.dumps({"seen_at": seen_at, "rate_limits": rate_limits}), encoding="utf-8")

    def test_missing_file_has_no_windows(self):
        self.assertEqual(usage.load(self.path, NOW), {"seen_at": None, "stale": True, "windows": []})

    def test_reads_both_windows_with_time_elapsed(self):
        self.write(
            NOW - 60,
            {
                "five_hour": {"used_percentage": 68.4, "resets_at": NOW + 3600},
                "seven_day": {"used_percentage": 41, "resets_at": NOW + 3 * 86400},
            },
        )
        result = usage.load(self.path, NOW)
        self.assertEqual((result["seen_at"], result["stale"]), (NOW - 60, False))
        five, week = result["windows"]
        self.assertEqual(
            five,
            {
                "key": "five_hour",
                "label": "5-hour limit",
                "used": 68.4,
                "resets_at": NOW + 3600,
                "elapsed": 0.8,
                "reset": False,
            },
        )
        self.assertEqual((week["key"], week["label"], week["used"]), ("seven_day", "Weekly limit", 41.0))
        self.assertAlmostEqual(week["elapsed"], 4 / 7)

    def test_a_window_past_its_reset_shows_as_reset(self):
        self.write(NOW - 60, {"five_hour": {"used_percentage": 99, "resets_at": NOW - 1}})
        [five] = usage.load(self.path, NOW)["windows"]
        self.assertEqual((five["used"], five["elapsed"], five["reset"]), (0.0, 0.0, True))

    def test_old_data_is_stale(self):
        self.write(NOW - usage.STALE_AFTER - 1, {"five_hour": {"used_percentage": 10, "resets_at": NOW + 60}})
        self.assertTrue(usage.load(self.path, NOW)["stale"])

    def test_values_are_clamped(self):
        self.write(NOW, {"five_hour": {"used_percentage": 140, "resets_at": NOW + 99 * 3600}})
        [five] = usage.load(self.path, NOW)["windows"]
        self.assertEqual((five["used"], five["elapsed"]), (100.0, 0.0))

    def test_malformed_windows_and_files_are_skipped(self):
        self.write(
            NOW,
            {
                "five_hour": {"used_percentage": "lots", "resets_at": NOW + 60},
                "seven_day": {"used_percentage": True, "resets_at": NOW + 60},
                "spend_limit": {"used_percentage": 5, "resets_at": NOW + 60},
            },
        )
        self.assertEqual(usage.load(self.path, NOW)["windows"], [])

    def test_unreadable_file_is_logged_and_has_no_windows(self):
        self.path.write_text("{broken", encoding="utf-8")
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(usage.load(self.path, NOW)["windows"], [])
        self.assertIn("could not read", err.getvalue())
