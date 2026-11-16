"""Pull shots from the tracker API and publish an HTML/CSV/JSON report.

    # one-command demo: starts the bundled mock API automatically
    python -m api_report --mock --out reports/

    # against a real endpoint
    SHOTTRACK_URL=https://tracker.example.com SHOTTRACK_TOKEN=... python -m api_report --out reports/
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import os
import sys
from datetime import date
from pathlib import Path

from .client import ApiError, ShotTrackClient
from .mock_server import DEMO_TOKEN, MockServer, ServerState
from .pipeline import build_report, post_webhook, slack_message, write_outputs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="api_report", description=__doc__.splitlines()[0])
    p.add_argument("--base-url", default=os.environ.get("SHOTTRACK_URL"))
    p.add_argument("--token", default=os.environ.get("SHOTTRACK_TOKEN"))
    p.add_argument("--mock", action="store_true", help="start the bundled mock API and report against it")
    p.add_argument("--flaky", action="store_true", help="with --mock: inject 429/503 errors to exercise retries")
    p.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    p.add_argument("--out", type=Path, default=Path("reports"))
    p.add_argument("--webhook-url", default=os.environ.get("REPORT_WEBHOOK_URL"),
                   help="optional Slack/Teams incoming webhook to post a summary to")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    with contextlib.ExitStack() as stack:
        if args.mock:
            server = stack.enter_context(MockServer(state=ServerState(flaky_every=3 if args.flaky else 0)))
            args.base_url, args.token = server.url, DEMO_TOKEN
        if not args.base_url or not args.token:
            p.error("set --base-url/--token (or SHOTTRACK_URL/SHOTTRACK_TOKEN), or use --mock")

        try:
            bundle = build_report(ShotTrackClient(args.base_url, args.token), args.as_of)
        except ApiError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    for path in write_outputs(bundle, args.out):
        print(f"wrote {path}")
    ctx = bundle.context
    print(f"{bundle.fetched_shots} shots fetched | {ctx['totals']['percent_complete']}% complete | "
          f"{len(ctx['overdue'])} overdue | {len(ctx['data_errors'])} data errors")
    if args.webhook_url:
        post_webhook(args.webhook_url, slack_message(ctx))
        print("posted summary to webhook")
    return 0
