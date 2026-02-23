"""
Auto-generate README.md spend dashboard and push to GitHub.

Called at the end of every Claude Code session (from log_session.py).
Regenerates the entire README.md from current data, commits, and pushes.
All errors are caught and silently ignored — this must never block session exit.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Reuse existing infrastructure from report.py
from report import (
    load_sessions,
    summarize,
    load_project_registry,
    load_billing,
    compute_month_expenses,
    fmt_tokens,
    fmt_usd,
)

REPO_DIR = Path("C:/Users/Tracy/Projects/claude-tracking")
README_PATH = REPO_DIR / "README.md"
PRICING_PATH = REPO_DIR / "pricing.json"


def load_pricing() -> dict:
    """Load token pricing rates from pricing.json. Returns sensible defaults if missing."""
    defaults = {
        "input": 15.0,
        "output": 75.0,
        "cache_write": 18.75,
        "cache_read": 1.50,
    }
    try:
        data = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
        rates = data.get("rates_per_million_tokens", {})
        return {k: float(rates.get(k, defaults[k])) for k in defaults}
    except (OSError, json.JSONDecodeError, ValueError):
        return defaults


def compute_token_cost(t: dict, rates: dict) -> float:
    """Compute estimated USD cost for a project's token usage."""
    cost = 0.0
    cost += t["input_tokens"] * rates["input"] / 1_000_000
    cost += t["output_tokens"] * rates["output"] / 1_000_000
    cost += t["cache_creation_tokens"] * rates["cache_write"] / 1_000_000
    cost += t["cache_read_tokens"] * rates["cache_read"] / 1_000_000
    return cost


def generate_readme(month: str) -> str:
    """Generate the complete README.md content for the current month."""
    now = datetime.now(timezone.utc)
    sessions = load_sessions(month=month)
    totals = summarize(sessions)
    registry = load_project_registry()
    rates = load_pricing()

    try:
        period_label = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
    except ValueError:
        period_label = month

    lines: list[str] = []
    lines.append("# Claude Code Spend Dashboard")
    lines.append("")
    lines.append(f"**{period_label}** | Last updated: {now.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    if not totals:
        lines.append("_No sessions recorded this month._")
        lines.append("")
        return "\n".join(lines)

    # --- Per-project token table ---
    lines.append("## Token Usage by Project")
    lines.append("")
    lines.append("| Project | Sessions | Input | Output | Cache Write | Cache Read | Est. Cost |")
    lines.append("|---------|----------|-------|--------|-------------|------------|-----------|")

    grand_token_cost = 0.0
    all_codes = set(totals.keys())
    if registry:
        all_codes |= set(registry.keys())

    for code in sorted(all_codes, key=lambda c: -(totals.get(c, {}).get("sessions", 0))):
        t = totals.get(code)
        if t:
            cost = compute_token_cost(t, rates)
            grand_token_cost += cost
            lines.append(
                f"| {code} | {t['sessions']} | "
                f"{fmt_tokens(t['input_tokens'])} | "
                f"{fmt_tokens(t['output_tokens'])} | "
                f"{fmt_tokens(t['cache_creation_tokens'])} | "
                f"{fmt_tokens(t['cache_read_tokens'])} | "
                f"{fmt_usd(cost)} |"
            )
        else:
            lines.append(f"| {code} | 0 | -- | -- | -- | -- | -- |")

    # Grand total row
    grand_sessions = sum(t["sessions"] for t in totals.values())
    grand_input = sum(t["input_tokens"] for t in totals.values())
    grand_output = sum(t["output_tokens"] for t in totals.values())
    grand_cache_write = sum(t["cache_creation_tokens"] for t in totals.values())
    grand_cache_read = sum(t["cache_read_tokens"] for t in totals.values())
    lines.append(
        f"| **TOTAL** | **{grand_sessions}** | "
        f"**{fmt_tokens(grand_input)}** | "
        f"**{fmt_tokens(grand_output)}** | "
        f"**{fmt_tokens(grand_cache_write)}** | "
        f"**{fmt_tokens(grand_cache_read)}** | "
        f"**{fmt_usd(grand_token_cost)}** |"
    )
    lines.append("")

    # --- Expenses section ---
    grand_expenses = 0.0
    expense_lines: list[str] = []
    for code in sorted(all_codes):
        if code not in registry:
            continue
        cwd = registry[code].get("cwd", "")
        billing = load_billing(cwd) if cwd else None
        if not billing:
            continue
        expenses = compute_month_expenses(billing, month)
        if not expenses:
            continue
        expense_lines.append(f"### {code}")
        expense_lines.append("")
        expense_lines.append("| Expense | Rate | Due This Month |")
        expense_lines.append("|---------|------|----------------|")
        subtotal = 0.0
        for exp in expenses:
            amt_str = fmt_usd(exp["amount_due"]) if exp["amount_due"] > 0 else "--"
            note = f" {exp['note']}" if exp["note"] else ""
            expense_lines.append(
                f"| {exp['description']}{note} | {exp['rate_label']} | {amt_str} |"
            )
            subtotal += exp["amount_due"]
        expense_lines.append(f"| **Subtotal** | | **{fmt_usd(subtotal)}** |")
        expense_lines.append("")
        grand_expenses += subtotal

    if expense_lines:
        lines.append("## Project Expenses")
        lines.append("")
        lines.extend(expense_lines)

    # --- Grand total ---
    lines.append("## Monthly Total")
    lines.append("")
    lines.append("| Category | Amount |")
    lines.append("|----------|--------|")
    lines.append(f"| Estimated token cost | {fmt_usd(grand_token_cost)} |")
    if grand_expenses > 0:
        lines.append(f"| Project expenses | {fmt_usd(grand_expenses)} |")
        lines.append(f"| **Grand total** | **{fmt_usd(grand_token_cost + grand_expenses)}** |")
    lines.append("")

    # --- Pricing reference ---
    lines.append("## Pricing Rates")
    lines.append("")
    lines.append("| Token Type | Rate (per 1M tokens) |")
    lines.append("|------------|---------------------|")
    lines.append(f"| Input | ${rates['input']:.2f} |")
    lines.append(f"| Output | ${rates['output']:.2f} |")
    lines.append(f"| Cache Write | ${rates['cache_write']:.2f} |")
    lines.append(f"| Cache Read | ${rates['cache_read']:.2f} |")
    lines.append("")

    # --- Footer ---
    lines.append("---")
    lines.append("")
    lines.append(
        "_Auto-generated by [claude-tracking](https://github.com/jrhoades1/claude-tracking). "
        "Do not edit manually._"
    )
    lines.append("")

    return "\n".join(lines)


def git_commit_and_push() -> None:
    """Stage README.md + data files, commit, and push. Silently ignores all failures."""
    now = datetime.now(timezone.utc)
    msg = f"dashboard: {now.strftime('%Y-%m-%d %H:%M UTC')}"

    try:
        run = lambda args: subprocess.run(
            args, cwd=str(REPO_DIR), capture_output=True, timeout=30
        )

        # Stage data files so the dashboard stays in sync with its data
        run(["git", "add", "README.md", "sessions.csv", "projects.json"])

        # Check if there are staged changes (avoid empty commits)
        result = run(["git", "diff", "--cached", "--quiet"])
        if result.returncode == 0:
            return  # Nothing to commit

        run(["git", "commit", "-m", msg])
        run(["git", "push"])
    except (subprocess.TimeoutExpired, OSError):
        pass  # Network issues, git not found, etc. — never block session exit


def main() -> None:
    """Entry point: regenerate README and push."""
    try:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        content = generate_readme(month)
        README_PATH.write_text(content, encoding="utf-8")
        git_commit_and_push()
    except Exception:
        pass  # Absolute safety net — never crash, never block
