"""
Claude Code Stop hook — logs session usage to central CSV for project billing.

Called automatically at the end of every Claude Code session via the global
Stop hook in ~/.claude/settings.json.

Reads JSON payload from stdin (provided by Claude Code hook system):
  {
    "session_id": "...",
    "cwd": "C:\\Users\\Tracy\\Projects\\some-project",
    "hook_event_name": "Stop",
    "usage": {
      "input_tokens": 12345,
      "output_tokens": 2345,
      "cache_creation_input_tokens": 4567,
      "cache_read_input_tokens": 89012
    }
  }

Project code is read from .claude/project-code.txt in the session's working
directory. Falls back to the directory name if the file doesn't exist.

Output: one appended row in sessions.csv per session.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path("C:/Users/Tracy/Projects/claude-tracking/sessions.csv")

FIELDNAMES = [
    "date",
    "time_utc",
    "project_code",
    "cwd",
    "session_id",
    "input_tokens",
    "output_tokens",
    "cache_creation_tokens",
    "cache_read_tokens",
]


def get_project_code(cwd: str) -> str:
    """
    Return the project code for billing attribution.

    Reads from .claude/project-code.txt in the session's working directory.
    Falls back to the directory name if the file doesn't exist — this ensures
    every session is attributed to something, even for projects that haven't
    been set up with an explicit code yet.
    """
    code_file = Path(cwd) / ".claude" / "project-code.txt"
    if code_file.exists():
        code = code_file.read_text(encoding="utf-8").strip()
        if code:
            return code
    return Path(cwd).name


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # If we can't read the payload, write a minimal error row so we know
        # the hook fired but failed — don't silently drop the event.
        payload = {}

    usage = payload.get("usage", {})
    cwd = payload.get("cwd", os.getcwd())
    now = datetime.now(timezone.utc)

    row = {
        "date": now.strftime("%Y-%m-%d"),
        "time_utc": now.strftime("%H:%M:%S"),
        "project_code": get_project_code(cwd),
        "cwd": cwd,
        "session_id": payload.get("session_id", ""),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0),
        "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
    }

    write_header = not LOG_FILE.exists()
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    main()
