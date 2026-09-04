"""Saved matches and the record of how you are progressing.

One match tells you what you did wrong on the day.  A run of matches tells
you whether you are actually getting better, which is the only question
that matters if the goal is to win a championship.  PR is noisy over a
single short match, so the trend is the signal.
"""

import glob
import json
import os
import time
from dataclasses import is_dataclass, asdict

DEFAULT_DIR = os.path.join(os.getcwd(), "matches")


def _jsonable(value):
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, float) and value != value:      # NaN
        return None
    return value


def save(summary, decisions, directory=DEFAULT_DIR, name=None, extra=None):
    os.makedirs(directory, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = name or ("match-%s.json" % stamp)
    path = os.path.join(directory, name)
    payload = {
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": _jsonable(summary),
        "decisions": [_jsonable(d) for d in decisions],
    }
    if extra:
        payload.update(_jsonable(extra))
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=1)
    return path


def load(path):
    with open(path) as handle:
        return json.load(handle)


def history(directory=DEFAULT_DIR, limit=30):
    """Past matches, oldest first."""
    paths = sorted(glob.glob(os.path.join(directory, "match-*.json")))
    out = []
    for path in paths[-limit:]:
        try:
            data = load(path)
        except (ValueError, OSError):
            continue
        summary = data.get("summary") or {}
        overall = summary.get("overall") or {}
        out.append({
            "path": path,
            "saved_at": data.get("saved_at", ""),
            "pr": overall.get("pr"),
            "band": overall.get("band"),
            "decisions": overall.get("decisions"),
            "chequer_pr": (summary.get("chequer") or {}).get("pr"),
            "cube_pr": (summary.get("cube") or {}).get("pr"),
            "missed_doubles": summary.get("missed_doubles"),
            "meta": summary.get("meta") or {},
        })
    return out


def format_history(rows, limit=12):
    if not rows:
        return ""
    lines = ["date                 PR     chequer  cube   result"]
    for row in rows[-limit:]:
        meta = row.get("meta") or {}
        result = ""
        if meta.get("match_length"):
            result = "%s-%s to %s" % (meta.get("score_human", 0),
                                      meta.get("score_bot", 0),
                                      meta.get("match_length"))
        lines.append("%-20s %-6s %-8s %-6s %s" % (
            row.get("saved_at", "")[:19],
            "%.1f" % row["pr"] if row.get("pr") is not None else "-",
            "%.1f" % row["chequer_pr"] if row.get("chequer_pr") is not None else "-",
            "%.1f" % row["cube_pr"] if row.get("cube_pr") is not None else "-",
            result))
    prs = [r["pr"] for r in rows if r.get("pr") is not None]
    if len(prs) >= 4:
        half = len(prs) // 2
        early = sum(prs[:half]) / half
        late = sum(prs[half:]) / (len(prs) - half)
        lines.append("")
        lines.append("first %d matches averaged PR %.1f; last %d averaged %.1f (%s)"
                     % (half, early, len(prs) - half, late,
                        "improving" if late < early else "not improving yet"))
    return "\n".join(lines)
