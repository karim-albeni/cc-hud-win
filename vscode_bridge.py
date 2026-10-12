"""Talk to the cc-hud VS Code extension through files next to the database.

Each VS Code window lists its folders and terminal shell pids in windows/<id>.json. Requests go to
requests/<id>/ (or requests/any/), and the extension claims one by renaming it to .claimed.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import winplatform

BRIDGE = Path(os.environ.get("HUD_DB", Path.home() / ".claude/hud/hud.db")).parent / "vscode"
STALE_AFTER = 600
WINDOW_ID = re.compile(r"^[0-9a-f]{32}$")
# code is a .cmd file, so cmd parses its arguments; these characters would be interpreted rather than passed.
CMD_SPECIAL = re.compile(r'[&|<>^%"]')


@dataclass(frozen=True)
class Window:
    window_id: str
    folders: tuple[str, ...]
    shell_pids: frozenset[int]
    updated_at: int


def load_windows(bridge: Path = BRIDGE, now: int | None = None) -> list[Window]:
    """VS Code windows that reported in the last ten minutes. A crashed window never deletes its file."""
    now = int(time.time()) if now is None else now
    windows = []
    for path in sorted((bridge / "windows").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            folders, pids = data["folders"], data["shellPids"]
            if not isinstance(folders, list) or not all(isinstance(folder, str) for folder in folders):
                raise ValueError("folders must be a list of strings")
            if not isinstance(pids, list) or not all(type(pid) is int for pid in pids):
                raise ValueError("shellPids must be a list of integers")
            window = Window(str(data["windowId"]), tuple(folders), frozenset(pids), int(data["updatedAt"]))
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f"ignoring {path.name}: {e}", file=sys.stderr)
            continue
        if (
            WINDOW_ID.match(window.window_id)
            and window.window_id == path.stem
            and now - window.updated_at <= STALE_AFTER
        ):
            windows.append(window)
    return windows


def contains(folder: str, path: str) -> bool:
    folder = os.path.normcase(os.path.normpath(folder))
    path = os.path.normcase(os.path.normpath(path))
    return path == folder or path.startswith(folder.rstrip("\\") + "\\")


def window_for_folder(windows: list[Window], cwd: str) -> Window | None:
    candidates = [w for w in windows if any(contains(folder, cwd) for folder in w.folders)]
    return max(candidates, key=lambda w: w.updated_at) if candidates else None


def window_for_pid(windows: list[Window], chain: list[int]) -> tuple[Window, int] | None:
    """The window whose terminal shell is the nearest ancestor in chain, with that shell's pid."""
    for pid in chain:
        for window in windows:
            if pid in window.shell_pids:
                return window, pid
    return None


def send_request(request: dict, window_id: str | None, bridge: Path = BRIDGE, wait: float = 5.0) -> str:
    """Hand a request to one window (or any window when None) and wait for it: 'ok', 'unclaimed' or 'failed: why'."""
    folder = bridge / "requests" / (window_id or "any")
    folder.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex
    pending, claimed, failed = (folder / f"{name}{suffix}" for suffix in (".json", ".claimed", ".failed"))
    staging = folder / f"{name}.tmp"
    staging.write_text(json.dumps(request), encoding="utf-8")
    staging.replace(pending)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not pending.exists() and not claimed.exists():
            break
        time.sleep(0.05)
    else:
        try:
            pending.unlink()
            return "unclaimed"
        except (FileNotFoundError, PermissionError):
            pass
        while claimed.exists() and time.monotonic() < deadline + wait:
            time.sleep(0.05)
        if claimed.exists():
            return "failed: timed out waiting for VS Code"
    if failed.exists():
        reason = failed.read_text(encoding="utf-8").strip()
        failed.unlink()
        return f"failed: {reason}"
    return "ok"


def raise_window(folder: str) -> str | None:
    """Bring the VS Code window that has folder open to the front (or open one). None on success, else why not."""
    if CMD_SPECIAL.search(folder):
        return f"cannot pass {folder!r} to VS Code safely"
    if not Path(folder).is_dir():
        return f"{folder} does not exist"
    code = shutil.which("code")
    if not code:
        return "the code command is not on PATH"
    subprocess.run([code, folder], check=False, timeout=30, creationflags=winplatform.NO_WINDOW)
    return None
