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
    """Load pricing config from pricing.json."""
    defaults = {
        "billing_model": "subscription",
        "monthly_cost": 100.0,
        "plan": "Claude Pro",
    }
    try:
        data = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
        model = data.get("billing_model", "subscription")
        if model == "subscription":
            sub = data.get("subscription", {})
            return {
                "billing_model": "subscription",
                "monthly_cost": float(sub.get("monthly_cost", 100.0)),
                "plan": sub.get("plan", "Claude Pro"),
            }
        return defaults
    except (OSError, json.JSONDecodeError, ValueError):
        return defaults


def total_tokens(t: dict) -> int:
    """Sum all token types for a project (used for proportional allocation)."""
    return (
        t["input_tokens"]
        + t["output_tokens"]
        + t["cache_creation_tokens"]
        + t["cache_read_tokens"]
    )


def generate_readme(month: str) -> str:
    """Generate the complete README.md content for the current month."""
    now = datetime.now(timezone.utc)
    sessions = load_sessions(month=month)
    totals = summarize(sessions)
    registry = load_project_registry()
    pricing = load_pricing()

    try:
        period_label = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
    except ValueError:
        period_label = month

    lines: list[str] = []
    lines.append("# Claude Code Spend Dashboard")
    lines.append("")
    lines.append(f"**{period_label}** | Last updated: {now.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    monthly_cost = pricing["monthly_cost"]
    plan_name = pricing["plan"]

    lines.append(f"> **Plan:** {plan_name} ({fmt_usd(monthly_cost)}/mo)")
    lines.append(">")
    lines.append("> Subscription cost is allocated across projects by share of total token usage.")
    lines.append("")

    if not totals:
        lines.append("_No sessions recorded this month._")
        lines.append("")
        return "\n".join(lines)

    # Calculate grand total tokens for proportional allocation
    grand_total_tokens = sum(total_tokens(t) for t in totals.values())

    # --- Per-project table ---
    all_codes = set(totals.keys())
    if registry:
        all_codes |= set(registry.keys())

    lines.append("## Usage by Project")
    lines.append("")
    lines.append("| Project | Sessions | Input | Output | Cache | Share | Allocated |")
    lines.append("|---------|----------|-------|--------|-------|-------|-----------|")

    for code in sorted(all_codes, key=lambda c: -(totals.get(c, {}).get("sessions", 0))):
        t = totals.get(code)
        if t:
            proj_tokens = total_tokens(t)
            share = proj_tokens / grand_total_tokens if grand_total_tokens > 0 else 0
            allocated = monthly_cost * share
            cache_total = t["cache_creation_tokens"] + t["cache_read_tokens"]
            lines.append(
                f"| {code} | {t['sessions']} | "
                f"{fmt_tokens(t['input_tokens'])} | "
                f"{fmt_tokens(t['output_tokens'])} | "
                f"{fmt_tokens(cache_total)} | "
                f"{share:.0%} | "
                f"{fmt_usd(allocated)} |"
            )
        else:
            lines.append(f"| {code} | 0 | -- | -- | -- | -- | -- |")

    # Grand total row
    grand_sessions = sum(t["sessions"] for t in totals.values())
    grand_input = sum(t["input_tokens"] for t in totals.values())
    grand_output = sum(t["output_tokens"] for t in totals.values())
    grand_cache = sum(
        t["cache_creation_tokens"] + t["cache_read_tokens"] for t in totals.values()
    )
    lines.append(
        f"| **TOTAL** | **{grand_sessions}** | "
        f"**{fmt_tokens(grand_input)}** | "
        f"**{fmt_tokens(grand_output)}** | "
        f"**{fmt_tokens(grand_cache)}** | "
        f"**100%** | "
        f"**{fmt_usd(monthly_cost)}** |"
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
    lines.append(f"| {plan_name} subscription | {fmt_usd(monthly_cost)} |")
    if grand_expenses > 0:
        lines.append(f"| Project expenses | {fmt_usd(grand_expenses)} |")
    lines.append(f"| **Total** | **{fmt_usd(monthly_cost + grand_expenses)}** |")
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
