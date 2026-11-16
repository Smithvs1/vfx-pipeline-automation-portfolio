from __future__ import annotations

import csv
import io
import json
from collections import Counter

from .models import Issue, Severity, Shot


def summary(shots: list[Shot], issues: list[Issue]) -> dict:
    by_rule = Counter(i.rule for i in issues)
    by_sev = Counter(i.severity.value for i in issues)
    shots_with_errors = {i.row for i in issues if i.severity == Severity.ERROR}
    return {
        "shots_checked": len(shots),
        "shots_clean": len(shots) - len({i.row for i in issues}),
        "shots_with_errors": len(shots_with_errors),
        "errors": by_sev.get("error", 0),
        "warnings": by_sev.get("warning", 0),
        "by_rule": dict(by_rule.most_common()),
    }


def to_json(shots: list[Shot], issues: list[Issue]) -> str:
    return json.dumps({"summary": summary(shots, issues), "issues": [i.to_dict() for i in issues]}, indent=2)


def to_csv(issues: list[Issue]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["row", "shot_code", "severity", "rule", "field", "message"])
    writer.writeheader()
    for i in issues:
        writer.writerow(i.to_dict())
    return buf.getvalue()


def to_markdown(shots: list[Shot], issues: list[Issue]) -> str:
    s = summary(shots, issues)
    lines = [
        "# Shot Data Validation Report",
        "",
        f"- Shots checked: **{s['shots_checked']}**",
        f"- Clean shots: **{s['shots_clean']}**",
        f"- Errors: **{s['errors']}** across {s['shots_with_errors']} shots",
        f"- Warnings: **{s['warnings']}**",
        "",
        "## Issues by rule",
        "",
        "| Rule | Count |",
        "|---|---|",
        *[f"| `{rule}` | {n} |" for rule, n in s["by_rule"].items()],
        "",
        "## Details",
        "",
        "| Row | Shot | Severity | Rule | Message |",
        "|---|---|---|---|---|",
        *[f"| {i.row} | `{i.shot_code or '-'}` | {i.severity.value} | `{i.rule}` | {i.message} |" for i in issues],
        "",
    ]
    return "\n".join(lines)


def to_console(shots: list[Shot], issues: list[Issue], color: bool = True) -> str:
    red, yellow, green, dim, reset = ("\033[31m", "\033[33m", "\033[32m", "\033[2m", "\033[0m") if color else ("",) * 5
    out = []
    for i in issues:
        tag = f"{red}ERROR{reset}" if i.severity == Severity.ERROR else f"{yellow}WARN {reset}"
        out.append(f"{tag} {dim}row {i.row:>3}{reset}  {i.shot_code or '<blank>':<18} {i.rule:<22} {i.message}")
    s = summary(shots, issues)
    status = f"{green}PASS{reset}" if s["errors"] == 0 else f"{red}FAIL{reset}"
    out.append("")
    out.append(f"{status}  {s['shots_checked']} shots checked | {s['shots_clean']} clean | "
               f"{s['errors']} errors | {s['warnings']} warnings")
    return "\n".join(out)
