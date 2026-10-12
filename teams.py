"""Post the digest to Microsoft Teams through a Power Automate Workflows webhook."""

import json
import os
import random
import re
import sys
import urllib.request
from collections.abc import Callable

import winplatform

CREDENTIAL = "cc-hud-teams-webhook"
# Credential Manager holds at most 2560 bytes per secret, which is 1280 UTF-16 characters.
MAX_WEBHOOK_LENGTH = 1280
MARKDOWN = re.compile(r"([\\*_\[\]()#>~`])")
WAITING_HEADLINES = [
    "Claude needs your attention 👀",
    "Knock knock. It's Claude. Again.",
    "Your sessions are waiting, very patiently ⏳",
    "Claude has questions. Several, in fact.",
    "Psst. Your terminals miss you.",
]
UNTOUCHED_HEADLINES = [
    "Some sessions are gathering dust 🕸️",
    "Remember these? They remember you.",
    "A few loose ends are waving at you 👋",
]


def validate_webhook(url: str) -> str:
    url = url.strip()
    if not url.startswith("https://"):
        raise ValueError("the webhook must start with https://")
    if len(url) > MAX_WEBHOOK_LENGTH:
        raise ValueError(f"the webhook is longer than {MAX_WEBHOOK_LENGTH} characters")
    return url


def escape(text: str) -> str:
    """Session titles come from transcripts; escaped, one can't restyle the card or turn into a link."""
    return MARKDOWN.sub(r"\\\1", text)


def headline(waiting: int, untouched: int, pick: Callable[[list[str]], str] = random.choice) -> str:
    """A light opening line: about sessions waiting on you when there are any, else about forgotten ones."""
    return pick(WAITING_HEADLINES if waiting else UNTOUCHED_HEADLINES)


def build_card(sections: list[tuple[str, list[str]]], board_url: str, title: str) -> dict:
    """A Teams message holding an Adaptive Card: the title, a plain count, then one line per session."""
    summary = ", ".join(f"{len(lines)} {heading.lower()}" for heading, lines in sections if lines)
    body = [
        {"type": "TextBlock", "text": escape(title), "size": "Large", "weight": "Bolder", "wrap": True},
        {"type": "TextBlock", "text": summary, "isSubtle": True, "spacing": "None", "wrap": True},
    ]
    for heading, lines in sections:
        if not lines:
            continue
        body.append(
            {"type": "TextBlock", "text": f"**{escape(heading)} ({len(lines)})**", "wrap": True, "spacing": "Medium"}
        )
        body += [{"type": "TextBlock", "text": f"- {escape(line)}", "wrap": True, "spacing": "None"} for line in lines]
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": body,
                    "actions": [{"type": "Action.OpenUrl", "title": "Open the board", "url": board_url}],
                },
            }
        ],
    }


def webhook() -> str:
    url = os.environ.get("HUD_TEAMS_WEBHOOK") or winplatform.read_credential(CREDENTIAL)
    if not url:
        sys.exit(
            f"no Teams webhook: run `hud.py set-webhook`, or set HUD_TEAMS_WEBHOOK (Credential Manager: {CREDENTIAL})"
        )
    try:
        return validate_webhook(url)
    except ValueError as e:
        sys.exit(f"Teams webhook rejected: {e}")


def post(card: dict, url: str) -> None:
    request = urllib.request.Request(url, data=json.dumps(card).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()
