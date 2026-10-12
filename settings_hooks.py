"""Add or remove the cc-hud hook in Claude Code's settings.json, leaving every other setting and hook alone.

Usage: settings_hooks.py add <settings.json> <python> <hook> [--db <path>]
       settings_hooks.py remove <settings.json>
"""

import copy
import json
import os
import re
import sys
from pathlib import Path

EVENTS = ("SessionStart", "UserPromptSubmit", "Notification", "PermissionRequest", "Stop", "SessionEnd", "PostToolUse")
# Any hook that runs a hooks/hud_event.py is ours, so a clone that moved since the last install is cleaned up too.
OUR_HOOK = re.compile(r"[\\/]hooks[\\/]hud_event\.py\b")


def is_ours(hook: dict) -> bool:
    return bool(OUR_HOOK.search(str(hook.get("command") or "")))


def remove_ours(settings: dict) -> dict:
    result = copy.deepcopy(settings)
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        return result
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        kept = []
        for group in groups:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if isinstance(inner, list) and any(isinstance(h, dict) and is_ours(h) for h in inner):
                remaining = [h for h in inner if not (isinstance(h, dict) and is_ours(h))]
                if not remaining:
                    continue
                kept.append({**group, "hooks": remaining})
            else:
                kept.append(group)
        hooks[event] = kept
    return result


def add_ours(settings: dict, command: str) -> dict:
    result = remove_ours(settings)
    hooks = result.setdefault("hooks", {})
    for event in EVENTS:
        hooks.setdefault(event, []).append({"hooks": [{"type": "command", "command": command, "timeout": 3}]})
    return result


def hook_command(python: str, hook: str, db: str | None) -> str:
    command = f'"{python}" "{hook}"'
    if db:
        command += f' --db "{db}"'
    return command


def main(argv: list[str]) -> int:
    action, path = argv[1], Path(argv[2])
    try:
        text = path.read_text(encoding="utf-8-sig") if path.exists() else "{}"
        settings = json.loads(text)
    except ValueError as e:  # UnicodeDecodeError and JSONDecodeError are both ValueErrors
        print(f"{path} is not valid JSON ({e}); left it unchanged", file=sys.stderr)
        return 1
    if not isinstance(settings, dict):
        print(f"{path} does not hold a JSON object; left it unchanged", file=sys.stderr)
        return 1
    if "hooks" in settings and not isinstance(settings["hooks"], dict):
        print(f"{path} has a 'hooks' value that is not an object; left it unchanged", file=sys.stderr)
        return 1
    if action == "add":
        db = argv[argv.index("--db") + 1] if "--db" in argv else None
        updated = add_ours(settings, hook_command(argv[3], argv[4], db))
    else:
        updated = remove_ours(settings)
    output = json.dumps(updated, indent=2, ensure_ascii=False) + "\n"
    # Written next to the real file and swapped in, so a crash mid-write never leaves settings.json empty.
    # Resolving first keeps a symlinked settings.json (dotfiles) pointing at the updated file.
    target = path.resolve()
    staging = target.with_name(f"{target.name}.cc-hud.tmp")
    with staging.open("w", encoding="utf-8", newline="\n") as f:
        f.write(output)
    os.replace(staging, target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
