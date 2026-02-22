"""
Claude Code Stop hook — logs session usage to central CSV for project billing.

Called automatically at the end of every Claude Code session via the global
Stop hook in ~/.claude/settings.json.

Reads JSON payload from stdin (provided by Claude Code hook system):
  {
    "session_id": "...",
    "transcript_path": "C:\\Users\\Tracy\\.claude\\projects\\...\\session.jsonl",
    "cwd": "C:\\Users\\Tracy\\Projects\\some-project",
    "hook_event_name": "Stop"
  }

Token usage is NOT included in the Stop hook payload. Instead, the script
reads the session transcript JSONL file (path provided in the payload) and
sums up usage from each assistant message's `message.usage` field.

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
REGISTRY_FILE = Path("C:/Users/Tracy/Projects/claude-tracking/projects.json")

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


def read_usage_from_transcript(transcript_path: str) -> dict:
    """
    Parse the session transcript JSONL and sum token usage across all messages.

    Each assistant message in the transcript has a `message.usage` dict with:
      input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens

    Returns a dict with the summed totals.
    """
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }

    path = Path(transcript_path)
    if not path.exists():
        return totals

    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = obj.get("message", {})
                if not isinstance(msg, dict):
                    continue
                usage = msg.get("usage", {})
                if not usage:
                    continue
                totals["input_tokens"] += usage.get("input_tokens", 0)
                totals["output_tokens"] += usage.get("output_tokens", 0)
                totals["cache_creation_input_tokens"] += usage.get(
                    "cache_creation_input_tokens", 0
                )
                totals["cache_read_input_tokens"] += usage.get(
                    "cache_read_input_tokens", 0
                )
    except (OSError, UnicodeDecodeError):
        pass

    return totals


def update_project_registry(project_code: str, cwd: str) -> None:
    """
    Upsert the project into projects.json so report.py can find billing.json
    files for all known projects, even those with no sessions in a given month.
    """
    try:
        registry: dict = {}
        if REGISTRY_FILE.exists():
            registry = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        registry[project_code] = {"cwd": cwd, "last_seen": now_str}

        REGISTRY_FILE.write_text(
            json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass  # Never let registry failure break session logging


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    cwd = payload.get("cwd", os.getcwd())
    now = datetime.now(timezone.utc)

    # Read token usage from the transcript file
    transcript_path = payload.get("transcript_path", "")
    usage = read_usage_from_transcript(transcript_path) if transcript_path else {}

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

    update_project_registry(row["project_code"], cwd)


if __name__ == "__main__":
    main()
