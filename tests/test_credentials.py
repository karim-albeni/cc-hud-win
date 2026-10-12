import unittest
import uuid

import teams
import winplatform


class CredentialTest(unittest.TestCase):
    def setUp(self):
        self.target = f"cc-hud-test-{uuid.uuid4().hex}"

    def tearDown(self):
        winplatform.delete_credential(self.target)

    def test_round_trip_keeps_non_ascii(self):
        secret = "https://example.invalid/hook?sig=åäö"
        winplatform.write_credential(self.target, secret)
        self.assertEqual(winplatform.read_credential(self.target), secret)

    def test_missing_is_none(self):
        self.assertIsNone(winplatform.read_credential(self.target))

    def test_delete_of_missing_is_quiet(self):
        winplatform.delete_credential(self.target)


class ValidateWebhookTest(unittest.TestCase):
    def test_strips_and_accepts_https(self):
        self.assertEqual(teams.validate_webhook("  https://x.invalid/a \n"), "https://x.invalid/a")

    def test_rejects_http(self):
        with self.assertRaises(ValueError):
            teams.validate_webhook("http://x.invalid/a")

    def test_rejects_too_long_for_credential_manager(self):
        with self.assertRaises(ValueError):
            teams.validate_webhook("https://" + "a" * 1300)
