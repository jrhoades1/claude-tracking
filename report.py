"""
Claude usage report — groups sessions.csv by project for monthly invoicing.

Usage:
  python report.py                  # current month
  python report.py --month 2026-02  # specific month (YYYY-MM)
  python report.py --all            # all time

Output is a plain-text summary suitable for copying into an invoice.

Sessions are logged automatically by log_session.py (the Claude Code Stop hook).
For API-billed projects, cross-reference the Anthropic Console filtered by API key
for exact USD costs. For MAX subscription sessions, use session count x your rate.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path("C:/Users/Tracy/Projects/claude-tracking/sessions.csv")

_SEP = "-" * 70


def load_sessions(month: str | None) -> list[dict]:
    """Load sessions from CSV, optionally filtered to a YYYY-MM month."""
    if not LOG_FILE.exists():
        return []

    with LOG_FILE.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if month:
        rows = [r for r in rows if r["date"].startswith(month)]

    return rows


def summarize(sessions: list[dict]) -> dict[str, dict]:
    """
    Aggregate sessions by project code.

    Returns:
        {project_code: {sessions, input_tokens, output_tokens, cache_creation, cache_read}}
    """
    totals: dict[str, dict] = defaultdict(lambda: {
        "sessions": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
    })

    for row in sessions:
        code = row["project_code"] or "UNKNOWN"
        t = totals[code]
        t["sessions"] += 1
        t["input_tokens"] += int(row.get("input_tokens") or 0)
        t["output_tokens"] += int(row.get("output_tokens") or 0)
        t["cache_creation_tokens"] += int(row.get("cache_creation_tokens") or 0)
        t["cache_read_tokens"] += int(row.get("cache_read_tokens") or 0)

    return dict(totals)


def fmt_tokens(n: int) -> str:
    """Format a token count with thousands separator."""
    return f"{n:,}"


def print_report(totals: dict[str, dict], period_label: str) -> None:
    """Print invoice-ready report to stdout."""
    print()
    print(f"Claude Usage Report  |  {period_label}")
    print(_SEP)

    if not totals:
        print("  No sessions recorded for this period.")
        print(_SEP)
        return

    # Sort by session count descending
    for code, t in sorted(totals.items(), key=lambda x: -x[1]["sessions"]):
        total_tokens = t["input_tokens"] + t["output_tokens"]
        cache_total = t["cache_creation_tokens"] + t["cache_read_tokens"]
        print(
            f"  {code:<24}  "
            f"{t['sessions']:>3} session{'s' if t['sessions'] != 1 else ' '}  |  "
            f"{fmt_tokens(t['input_tokens'])} input  |  "
            f"{fmt_tokens(t['output_tokens'])} output  |  "
            f"{fmt_tokens(cache_total)} cache"
        )
        print(
            f"  {'':24}  "
            f"Total billable tokens: {fmt_tokens(total_tokens)}"
        )
        print()

    grand_sessions = sum(t["sessions"] for t in totals.values())
    grand_input = sum(t["input_tokens"] for t in totals.values())
    grand_output = sum(t["output_tokens"] for t in totals.values())
    print(_SEP)
    print(
        f"  {'TOTAL':<24}  "
        f"{grand_sessions:>3} sessions  |  "
        f"{fmt_tokens(grand_input)} input  |  "
        f"{fmt_tokens(grand_output)} output"
    )
    print(_SEP)
    print()
    print("Notes:")
    print("  * Cache tokens (creation + read) are shown for reference.")
    print("    Most billing models charge only for input + output tokens.")
    print("  * For API-billed projects: cross-reference Anthropic Console")
    print("    filtered by project API key for exact USD costs.")
    print("  * For MAX subscription: use session count x your internal rate,")
    print("    or bill a flat project fee.")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Claude usage report for client billing."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--month",
        metavar="YYYY-MM",
        help="Report for a specific month (default: current month)",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Report all sessions regardless of date",
    )
    args = parser.parse_args()

    if args.all:
        sessions = load_sessions(month=None)
        period_label = "All Time"
    else:
        month = args.month or datetime.now(timezone.utc).strftime("%Y-%m")
        sessions = load_sessions(month=month)
        # Format "2026-02" → "Feb 2026"
        try:
            period_label = datetime.strptime(month, "%Y-%m").strftime("%b %Y")
        except ValueError:
            period_label = month

    totals = summarize(sessions)
    print_report(totals, period_label)


if __name__ == "__main__":
    main()
