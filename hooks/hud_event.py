"""Claude Code hook for every session lifecycle event. Records live state in the hud DB.

Must stay fast and must never fail the session: every path exits 0 and prints nothing.
Usage: hud_event.py [--db <path>]   (default: $HUD_DB, else ~/.claude/hud/hud.db)
"""

import json
import os
import re
import sqlite3
import sys
import time
import traceback
from pathlib import Path

LIVE = {
    "SessionStart": "idle",
    "UserPromptSubmit": "working",
    "PostToolUse": "working",
    "Notification": "waiting",
    "PermissionRequest": "waiting",
    "Stop": "idle",
    "SessionEnd": "detached",
}
REF = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/(pull|issues)/([0-9]+)")

UPSERT = """
INSERT INTO items (session_id, cwd, transcript_path, live, live_detail, first_prompt, last_prompt, gh_ref, gh_url,
                   state, created_at, last_activity_at)
VALUES (:sid, :cwd, :transcript, :live, :detail, :prompt, :prompt, :ref, :url,
        CASE WHEN :cleared THEN 'cleared' ELSE 'open' END, unixepoch(), unixepoch())
ON CONFLICT (session_id) DO UPDATE SET
  live = excluded.live,
  live_detail = excluded.live_detail,
  cwd = coalesce(excluded.cwd, cwd),
  transcript_path = coalesce(excluded.transcript_path, transcript_path),
  first_prompt = coalesce(first_prompt, excluded.first_prompt),
  last_prompt = coalesce(excluded.last_prompt, last_prompt),
  gh_ref = CASE WHEN gh_scanned = 2 THEN gh_ref ELSE coalesce(gh_ref, excluded.gh_ref) END,
  gh_url = CASE WHEN gh_scanned = 2 THEN gh_url ELSE coalesce(gh_url, excluded.gh_url) END,
  last_activity_at = excluded.last_activity_at,
  state = CASE WHEN :prompted AND state != 'open' THEN 'open'
               WHEN :cleared AND state != 'done' THEN 'cleared' ELSE state END,
  done_at = CASE WHEN :prompted THEN NULL ELSE done_at END
"""

PREDECESSOR = """FROM items p WHERE p.cwd = :cwd AND p.state = 'cleared' AND p.session_id != :sid
                 AND p.last_activity_at >= unixepoch() - 30"""

# /clear hands the work on to a new session in the same tab: it joins the thread of the one that just ended there
# and carries its note and PR status, so the card keeps its place on the board.
INHERIT = f"""
UPDATE items SET (thread_id, note, gh_ref, gh_url, gh_login, gh_scanned, gh_checked_at, pr_ref, pr_state, pr_rollup,
                  pr_event, pr_event_at, pr_alert, pr_checked_at) =
  (SELECT coalesce(p.thread_id, p.session_id), p.note, p.gh_ref, p.gh_url, p.gh_login,
          CASE WHEN p.gh_scanned = 2 THEN 2 END, p.gh_checked_at, p.pr_ref, p.pr_state, p.pr_rollup, p.pr_event,
          p.pr_event_at, p.pr_alert, p.pr_checked_at
   {PREDECESSOR} ORDER BY p.last_activity_at DESC LIMIT 1)
WHERE session_id = :sid AND thread_id IS NULL AND EXISTS (SELECT 1 {PREDECESSOR})
"""


def db_path(argv: list[str]) -> Path:
    if len(argv) >= 3 and argv[1] == "--db":
        return Path(argv[2])
    return Path(os.environ.get("HUD_DB", Path.home() / ".claude/hud/hud.db"))


def params(payload: dict) -> dict | None:
    """The values the SQL needs, or None when this event is not one the board tracks."""
    event = payload.get("hook_event_name") or ""
    base = LIVE.get(event)
    sid = payload.get("session_id")
    # A subagent's or parallel tool's completion must not hide a permission prompt the main thread is waiting on.
    if base is None or sid is None or (event == "PostToolUse" and payload.get("agent_id") is not None):
        return None
    live = "idle" if event == "Notification" and payload.get("notification_type") == "idle_prompt" else base
    prompt = ref = url = None
    if event == "UserPromptSubmit":
        raw = str(payload.get("prompt") or "")
        prompt = " ".join(raw.split())[:300] or None
        if m := REF.search(raw):
            ref, url = f"{m[1]}#{m[3]}", f"https://{m[0]}"
    if event == "Notification":
        detail = payload.get("message")
    elif event == "PermissionRequest":
        detail = "permission: " + (payload.get("tool_name") or "tool")
    else:
        detail = None
    return {
        "sid": str(sid),
        "cwd": payload.get("cwd") or None,
        "transcript": payload.get("transcript_path") or None,
        "live": live,
        "detail": detail or None,
        "prompt": prompt,
        "ref": ref,
        "url": url,
        "cleared": event == "SessionEnd" and payload.get("reason") == "clear",
        "prompted": event == "UserPromptSubmit",
        "inherits": event == "SessionStart" and payload.get("source") == "clear" and bool(payload.get("cwd")),
    }


def record(path: Path, payload: dict) -> None:
    values = params(payload)
    if values is None:
        return
    db = sqlite3.connect(path, timeout=2)
    try:
        with db:
            db.execute(UPSERT, values)
            if values["inherits"]:
                db.execute(INHERIT, values)
    finally:
        db.close()


def main(argv: list[str]) -> None:
    path = db_path(argv)
    if not path.is_file():
        return
    try:
        payload = json.loads(sys.stdin.buffer.read())
        if isinstance(payload, dict):
            record(path, payload)
    except Exception:
        # The session must never see a hook failure, so the reason goes to a log instead of stderr.
        try:
            with (path.parent / "hook-errors.log").open("a", encoding="utf-8") as log:
                log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {traceback.format_exc(limit=1).strip()}\n")
        except OSError:
            pass


if __name__ == "__main__":
    main(sys.argv)
    sys.exit(0)
