"""Plan usage limits that Claude Code's status line saved next to the database, shaped for the board."""

import json
import sys
from pathlib import Path

WINDOWS = {"five_hour": ("5-hour limit", 5 * 3600), "seven_day": ("Weekly limit", 7 * 86400)}
# The limits only change when Claude replies, so after half an hour without one the numbers may be out of date.
STALE_AFTER = 1800


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def window(key: str, raw, now: int) -> dict | None:
    label, length = WINDOWS[key]
    if not isinstance(raw, dict):
        return None
    used, resets_at = raw.get("used_percentage"), raw.get("resets_at")
    # type() rather than isinstance(): JSON true/false arrive as bool, which isinstance counts as an int.
    if type(used) not in (int, float) or type(resets_at) is not int:
        return None
    if resets_at <= now:
        return {"key": key, "label": label, "used": 0.0, "resets_at": resets_at, "elapsed": 0.0, "reset": True}
    elapsed = clamp(1 - (resets_at - now) / length, 0.0, 1.0)
    return {
        "key": key,
        "label": label,
        "used": float(clamp(used, 0, 100)),
        "resets_at": resets_at,
        "elapsed": elapsed,
        "reset": False,
    }


def load(path: Path, now: int) -> dict:
    """The 5-hour and weekly windows from the saved file, with how much of each window's time has passed."""
    empty = {"seen_at": None, "stale": True, "windows": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return empty
    except (OSError, ValueError) as e:
        print(f"could not read {path}: {e}", file=sys.stderr)
        return empty
    if not isinstance(data, dict) or not isinstance(data.get("rate_limits"), dict):
        return empty
    seen_at = data.get("seen_at") if isinstance(data.get("seen_at"), int) else None
    windows = [w for key in WINDOWS if (w := window(key, data["rate_limits"].get(key), now))]
    stale = seen_at is None or now - seen_at > STALE_AFTER
    return {"seen_at": seen_at, "stale": stale, "windows": windows}
