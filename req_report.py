"""
Cross-project requirements report — scans all registered projects for
requirements/ directories and outputs a status summary.

Usage:
  python req_report.py                              # all projects, all statuses
  python req_report.py --project ALD-SERVICETITAN   # one project
  python req_report.py --status proposed             # filter by status
  python req_report.py --detail                      # show individual REQ IDs

Discovers projects via projects.json (auto-maintained by log_session.py).
Parses YAML frontmatter from each REQ-*.md file in requirements/.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

REGISTRY_FILE = Path("C:/Users/Tracy/Projects/claude-tracking/projects.json")

_SEP = "-" * 70

# Status display order
STATUS_ORDER = [
    "proposed",
    "approved",
    "scheduled",
    "in_progress",
    "implemented",
    "verified",
    "rejected",
    "deferred",
]


def load_project_registry() -> dict[str, dict]:
    """Load the project registry mapping project codes to working directories."""
    if REGISTRY_FILE.exists():
        try:
            return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def parse_frontmatter(filepath: Path) -> dict | None:
    """
    Parse YAML frontmatter from a markdown file.

    Reads the block between the first two '---' lines and extracts
    key: value pairs. Handles simple YAML (strings, dates, nulls, lists).
    Does not require PyYAML — uses regex for simplicity.
    """
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    # Match frontmatter block
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return None

    frontmatter: dict = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(\w+)\s*:\s*(.*)", line)
        if m:
            key = m.group(1)
            val = m.group(2).strip()
            # Handle null
            if val in ("null", "~", ""):
                frontmatter[key] = None
            # Handle lists like [tag1, tag2]
            elif val.startswith("[") and val.endswith("]"):
                items = [s.strip().strip("'\"") for s in val[1:-1].split(",") if s.strip()]
                frontmatter[key] = items
            # Handle quoted strings
            elif (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                frontmatter[key] = val[1:-1]
            else:
                frontmatter[key] = val

    return frontmatter if frontmatter.get("id") else None


def scan_requirements(cwd: str) -> list[dict]:
    """Scan a project's requirements/ directory for REQ-*.md files."""
    req_dir = Path(cwd) / "requirements"
    if not req_dir.is_dir():
        return []

    reqs = []
    for f in sorted(req_dir.glob("REQ-*.md")):
        fm = parse_frontmatter(f)
        if fm:
            fm["_file"] = f.name
            reqs.append(fm)
    return reqs


def print_report(
    all_reqs: dict[str, list[dict]],
    status_filter: str | None = None,
    detail: bool = False,
) -> None:
    """Print requirements status report to stdout."""
    print()
    title = "Requirements Report"
    if status_filter:
        title += f"  |  Status: {status_filter}"
    else:
        title += "  |  All Projects"
    print(title)
    print(_SEP)

    if not all_reqs:
        print("  No projects with requirements found.")
        print(_SEP)
        return

    grand_total = 0

    for code in sorted(all_reqs.keys()):
        reqs = all_reqs[code]
        if status_filter:
            reqs = [r for r in reqs if r.get("status") == status_filter]

        if not reqs:
            continue

        print(f"  {code}")

        # Group by status
        by_status: dict[str, list[dict]] = defaultdict(list)
        for r in reqs:
            by_status[r.get("status", "unknown")].append(r)

        for status in STATUS_ORDER:
            if status not in by_status:
                continue
            items = by_status[status]
            ids = ", ".join(r.get("id", "?") for r in items)
            if detail:
                print(f"    {status:<14} {len(items):>3}   ({ids})")
                for r in items:
                    priority = r.get("priority", "")
                    pri_tag = f" [{priority}]" if priority else ""
                    print(f"{'':20} {r.get('id', '?')}: {r.get('title', 'untitled')}{pri_tag}")
            else:
                print(f"    {status:<14} {len(items):>3}   ({ids})")

        # Unknown statuses
        for status, items in by_status.items():
            if status not in STATUS_ORDER:
                ids = ", ".join(r.get("id", "?") for r in items)
                print(f"    {status:<14} {len(items):>3}   ({ids})")

        grand_total += len(reqs)
        print()

    print(_SEP)
    project_count = sum(1 for reqs in all_reqs.values() if reqs)
    print(f"  TOTAL  {grand_total} requirements across {project_count} project{'s' if project_count != 1 else ''}")
    print(_SEP)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cross-project requirements status report."
    )
    parser.add_argument(
        "--project",
        metavar="CODE",
        help="Filter to a specific project code",
    )
    parser.add_argument(
        "--status",
        metavar="STATUS",
        help="Filter to a specific status (e.g., proposed, approved, in_progress)",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Show individual requirement titles",
    )
    args = parser.parse_args()

    registry = load_project_registry()

    if args.project:
        if args.project not in registry:
            print(f"  Project '{args.project}' not found in registry.")
            print(f"  Known projects: {', '.join(registry.keys())}")
            return
        registry = {args.project: registry[args.project]}

    all_reqs: dict[str, list[dict]] = {}
    for code, info in registry.items():
        cwd = info.get("cwd", "")
        reqs = scan_requirements(cwd) if cwd else []
        if reqs:
            all_reqs[code] = reqs

    print_report(all_reqs, status_filter=args.status, detail=args.detail)


if __name__ == "__main__":
    main()
