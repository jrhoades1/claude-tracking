"""
Claude usage report — groups sessions.csv by project for monthly invoicing.

Usage:
  python report.py                  # current month
  python report.py --month 2026-02  # specific month (YYYY-MM)
  python report.py --all            # all time (expenses skipped)

Output is a plain-text summary suitable for copying into an invoice.
Merges token usage (from sessions.csv) with project expenses (from each
project's .claude/billing.json, discovered via projects.json registry).

Sessions are logged automatically by log_session.py (the Claude Code Stop hook).
For API-billed projects, cross-reference the Anthropic Console filtered by API key
for exact USD costs. For MAX subscription sessions, use session count x your rate.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path("C:/Users/Tracy/Projects/claude-tracking/sessions.csv")
REGISTRY_FILE = Path("C:/Users/Tracy/Projects/claude-tracking/projects.json")

_SEP = "-" * 70


# ---------------------------------------------------------------------------
# Session loading (unchanged)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Project registry & expense loading
# ---------------------------------------------------------------------------

def load_project_registry() -> dict[str, dict]:
    """
    Load the project registry mapping project codes to their working directories.

    Falls back to scanning sessions.csv for unique (project_code, cwd) pairs
    if projects.json does not exist yet.
    """
    if REGISTRY_FILE.exists():
        try:
            return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback: build registry from sessions.csv
    registry: dict[str, dict] = {}
    if LOG_FILE.exists():
        with LOG_FILE.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                code = row.get("project_code", "")
                cwd = row.get("cwd", "")
                if code and cwd:
                    registry[code] = {"cwd": cwd, "last_seen": row.get("date", "")}
    return registry


def load_billing(cwd: str) -> dict | None:
    """Read .claude/billing.json from a project directory. Returns None if missing."""
    billing_file = Path(cwd) / ".claude" / "billing.json"
    if not billing_file.exists():
        return None
    try:
        data = json.loads(billing_file.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def compute_month_expenses(billing: dict, month: str) -> list[dict]:
    """
    Given a parsed billing.json and a YYYY-MM month string, return a list of
    expense dicts for display:

        {"description", "rate_label", "amount_due", "note"}

    amount_due is the dollar amount due THIS month (0.0 if not due).
    """
    month_start = datetime.strptime(month + "-01", "%Y-%m-%d")
    month_year = month_start.year
    month_num = month_start.month

    result = []
    for exp in billing.get("expenses", []):
        exp_type = exp.get("type", "")
        desc = exp.get("description", "unknown")
        amount = float(exp.get("amount", 0))

        if exp_type == "one-time":
            exp_date = exp.get("date", "")
            if exp_date.startswith(month):
                result.append({
                    "description": desc,
                    "rate_label": "one-time",
                    "amount_due": amount,
                    "note": f"[{exp_date}]",
                })
            else:
                # Show one-time expenses from other months only if they exist
                # (skip — they clutter the report)
                pass

        elif exp_type == "recurring":
            freq = exp.get("frequency", "monthly")
            start = exp.get("start_date", "")
            end = exp.get("end_date")

            # Check if expense is active this month
            if start:
                start_dt = datetime.strptime(start[:7] + "-01", "%Y-%m-%d")
                if month_start < start_dt:
                    continue  # Not started yet
            if end:
                end_dt = datetime.strptime(end[:7] + "-01", "%Y-%m-%d")
                if month_start > end_dt:
                    continue  # Already ended

            start_month = int(start[:4]) * 12 + int(start[5:7]) if start else 0
            current_month = month_year * 12 + month_num
            diff = current_month - start_month

            due_this_month = False
            freq_label = ""
            renew_note = ""

            if freq == "monthly":
                due_this_month = True
                freq_label = f"${amount:.2f}/mo"
            elif freq == "quarterly":
                due_this_month = (diff % 3 == 0)
                freq_label = f"${amount:.2f}/qtr"
                if not due_this_month:
                    # Calculate next due month
                    months_until = 3 - (diff % 3)
                    next_month_num = ((month_num - 1 + months_until) % 12) + 1
                    next_name = datetime(2000, next_month_num, 1).strftime("%b")
                    renew_note = f"[next: {next_name}]"
            elif freq == "yearly":
                start_mo = int(start[5:7]) if start else month_num
                due_this_month = (month_num == start_mo)
                freq_label = f"${amount:.2f}/yr"
                if not due_this_month:
                    renew_name = datetime(2000, start_mo, 1).strftime("%b")
                    renew_note = f"[renews {renew_name}]"

            result.append({
                "description": desc,
                "rate_label": freq_label,
                "amount_due": amount if due_this_month else 0.0,
                "note": renew_note,
            })

    return result


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_tokens(n: int) -> str:
    """Format a token count with thousands separator."""
    return f"{n:,}"


def fmt_usd(n: float) -> str:
    """Format a dollar amount."""
    return f"${n:,.2f}"


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------

def print_report(
    totals: dict[str, dict],
    period_label: str,
    registry: dict[str, dict] | None = None,
    month: str | None = None,
) -> None:
    """Print invoice-ready report to stdout."""
    print()
    print(f"Claude Usage Report  |  {period_label}")
    print(_SEP)

    if not totals and not registry:
        print("  No sessions recorded for this period.")
        print(_SEP)
        return

    # Merge: ensure projects with expenses but no sessions still appear
    all_codes = set(totals.keys())
    if registry and month:
        all_codes |= set(registry.keys())

    grand_expenses = 0.0

    for code in sorted(all_codes, key=lambda c: -(totals.get(c, {}).get("sessions", 0))):
        t = totals.get(code)

        # Print token section if there are sessions
        if t:
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
        else:
            print(f"  {code:<24}  (no sessions this period)")

        # Print expenses if we have a month and registry
        if month and registry and code in registry:
            cwd = registry[code].get("cwd", "")
            billing = load_billing(cwd) if cwd else None
            if billing:
                expenses = compute_month_expenses(billing, month)
                if expenses:
                    print()
                    print(f"    Expenses:")
                    subtotal = 0.0
                    for exp in expenses:
                        amt_str = fmt_usd(exp["amount_due"]) if exp["amount_due"] > 0 else "--"
                        note = f"   {exp['note']}" if exp["note"] else ""
                        print(
                            f"      {exp['description']:<32} "
                            f"{exp['rate_label']:<12} "
                            f"{amt_str:>8}"
                            f"{note}"
                        )
                        subtotal += exp["amount_due"]
                    print(f"      {'':32} {'':12} {'--------':>8}")
                    print(f"      {'Expenses this month:':<44} {fmt_usd(subtotal):>8}")
                    grand_expenses += subtotal

        print()

    # Grand totals
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
    if grand_expenses > 0:
        print(f"  {'TOTAL EXPENSES':<24}  {fmt_usd(grand_expenses):>40}")
    print(_SEP)
    print()
    print("Notes:")
    print("  * Cache tokens (creation + read) are shown for reference.")
    print("    Most billing models charge only for input + output tokens.")
    print("  * For API-billed projects: cross-reference Anthropic Console")
    print("    filtered by project API key for exact USD costs.")
    print("  * For MAX subscription: use session count x your internal rate,")
    print("    or bill a flat project fee.")
    if grand_expenses > 0:
        print("  * Expense amounts reflect what is due THIS month only.")
        print("    Yearly/quarterly items appear only in their renewal month.")
    if not month:
        print("  * Use --month YYYY-MM for expense details (skipped in --all mode).")
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

    registry = load_project_registry()

    if args.all:
        sessions = load_sessions(month=None)
        period_label = "All Time"
        month = None
    else:
        month = args.month or datetime.now(timezone.utc).strftime("%Y-%m")
        sessions = load_sessions(month=month)
        try:
            period_label = datetime.strptime(month, "%Y-%m").strftime("%b %Y")
        except ValueError:
            period_label = month

    totals = summarize(sessions)
    print_report(totals, period_label, registry=registry, month=month)


if __name__ == "__main__":
    main()
