import os
import unittest
from unittest import mock

import teams


class EscapeTest(unittest.TestCase):
    def test_escapes_markdown(self):
        self.assertEqual(
            teams.escape("fix *all* [links] (now) #1 _x_ `y` > ~z"),
            r"fix \*all\* \[links\] \(now\) \#1 \_x\_ \`y\` \> \~z",
        )

    def test_escapes_backslashes(self):
        self.assertEqual(teams.escape("a\\*b"), "a\\\\\\*b")

    def test_leaves_swedish_alone(self):
        self.assertEqual(teams.escape("Svara Åsa om fönstret"), "Svara Åsa om fönstret")


def first(options):
    return options[0]


class HeadlineTest(unittest.TestCase):
    def test_waiting_sessions_get_a_waiting_headline(self):
        self.assertEqual(teams.headline(waiting=2, untouched=5, pick=first), teams.WAITING_HEADLINES[0])

    def test_only_untouched_sessions_get_a_dusty_headline(self):
        self.assertEqual(teams.headline(waiting=0, untouched=1, pick=first), teams.UNTOUCHED_HEADLINES[0])


class BuildCardTest(unittest.TestCase):
    def setUp(self):
        self.card = teams.build_card(
            [("Waiting on you", ["fix *it* (my-project, 2h)"]), ("Open but untouched", [])],
            "http://localhost:7777",
            "Knock knock",
        )
        self.content = self.card["attachments"][0]["content"]

    def test_is_an_adaptive_card_message(self):
        self.assertEqual(self.card["type"], "message")
        self.assertEqual(self.card["attachments"][0]["contentType"], "application/vnd.microsoft.card.adaptive")
        self.assertEqual(self.content["type"], "AdaptiveCard")

    def test_opens_with_the_headline_and_a_plain_summary(self):
        title, summary = self.content["body"][:2]
        self.assertEqual((title["text"], title["size"], title["weight"]), ("Knock knock", "Large", "Bolder"))
        self.assertEqual((summary["text"], summary["isSubtle"]), ("1 waiting on you", True))

    def test_skips_empty_sections_and_counts_lines(self):
        texts = [block["text"] for block in self.content["body"][2:]]
        self.assertEqual(texts, ["**Waiting on you (1)**", r"- fix \*it\* \(my-project, 2h\)"])

    def test_links_the_board(self):
        self.assertEqual(self.content["actions"][0]["url"], "http://localhost:7777")


class WebhookTest(unittest.TestCase):
    def test_environment_wins(self):
        with (
            mock.patch.dict(os.environ, {"HUD_TEAMS_WEBHOOK": "https://env.invalid/x"}),
            mock.patch.object(teams.winplatform, "read_credential", return_value="https://cred.invalid/x"),
        ):
            self.assertEqual(teams.webhook(), "https://env.invalid/x")

    def test_credential_manager_is_the_fallback(self):
        with (
            mock.patch.dict(os.environ, {}, clear=False),
            mock.patch.object(teams.winplatform, "read_credential", return_value="https://cred.invalid/x"),
        ):
            os.environ.pop("HUD_TEAMS_WEBHOOK", None)
            self.assertEqual(teams.webhook(), "https://cred.invalid/x")

    def test_missing_exits_with_the_fix(self):
        with (
            mock.patch.dict(os.environ, {}, clear=False),
            mock.patch.object(teams.winplatform, "read_credential", return_value=None),
        ):
            os.environ.pop("HUD_TEAMS_WEBHOOK", None)
            with self.assertRaises(SystemExit) as raised:
                teams.webhook()
        self.assertIn("hud.py set-webhook", str(raised.exception))
