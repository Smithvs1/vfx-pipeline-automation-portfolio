"""Command line entry point.

    python -m shot_validator sample_data/shots.csv --vendors sample_data/vendors.csv
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from . import report
from .models import Severity, load_shots, load_vendors
from .validator import ValidationConfig, validate


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="shot_validator", description="Validate VFX shot tracking data.")
    p.add_argument("shots", type=Path, help="CSV export of the shot list")
    p.add_argument("--vendors", type=Path, help="CSV of vendors (enables vendor checks)")
    p.add_argument("--show", default="NVD", help="show code used in the naming convention (default: NVD)")
    p.add_argument("--as-of", type=date.fromisoformat, default=date.today(),
                   help="date used for overdue checks, YYYY-MM-DD (default: today)")
    p.add_argument("--format", choices=["console", "json", "csv", "markdown"], default="console")
    p.add_argument("-o", "--output", type=Path, help="write the report to a file instead of stdout")
    p.add_argument("--strict", action="store_true", help="exit non-zero on warnings as well as errors")
    p.add_argument("--no-color", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    shots = load_shots(args.shots)
    vendors = load_vendors(args.vendors) if args.vendors else {}
    issues = validate(shots, vendors, ValidationConfig(show_code=args.show, as_of=args.as_of))

    if args.format == "json":
        text = report.to_json(shots, issues)
    elif args.format == "csv":
        text = report.to_csv(issues)
    elif args.format == "markdown":
        text = report.to_markdown(shots, issues)
    else:
        text = report.to_console(shots, issues, color=not args.no_color and sys.stdout.isatty() and not args.output)

    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote {args.format} report to {args.output}")
    else:
        print(text)

    has_errors = any(i.severity == Severity.ERROR for i in issues)
    return 1 if has_errors or (args.strict and issues) else 0
