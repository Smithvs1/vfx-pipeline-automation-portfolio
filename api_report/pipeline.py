"""Extract -> transform -> publish."""
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from production_assistant.context import build_context
from shot_validator import Shot, Vendor
from shot_validator.report import to_csv
from shot_validator.validator import ValidationConfig, validate

from .client import ShotTrackClient


@dataclass
class ReportBundle:
    context: dict
    issues_csv: str
    html: str
    fetched_shots: int


def records_to_models(shot_rows: list[dict], vendor_rows: list[dict]) -> tuple[list[Shot], dict[str, Vendor]]:
    shots = [Shot.from_row(i, row) for i, row in enumerate(shot_rows, start=1)]
    vendors = {
        r["vendor_id"]: Vendor(r["vendor_id"], r["name"], str(r["active"]).lower() in {"yes", "true", "1"},
                               int(r.get("max_active_shots") or 0))
        for r in vendor_rows
    }
    return shots, vendors


def build_report(client: ShotTrackClient, as_of: date, show_name: str = "Nova Drift") -> ReportBundle:
    shots, vendors = records_to_models(client.shots(per_page=10), client.vendors())
    context = build_context(shots, vendors, as_of, show_name)
    issues = validate(shots, vendors, ValidationConfig(as_of=as_of))
    return ReportBundle(context, to_csv(issues), render_html(context), len(shots))


def _bar_chart(title: str, data: dict[str, int], color: str) -> str:
    if not data:
        return ""
    width, bar_h, gap, label_w = 520, 22, 8, 150
    top = max(data.values()) or 1
    rows = []
    for i, (label, value) in enumerate(data.items()):
        y = i * (bar_h + gap)
        w = int((width - label_w - 40) * value / top)
        rows.append(
            f'<text x="{label_w - 8}" y="{y + 16}" text-anchor="end">{html.escape(str(label))}</text>'
            f'<rect x="{label_w}" y="{y}" width="{w}" height="{bar_h}" rx="3" fill="{color}"/>'
            f'<text x="{label_w + w + 6}" y="{y + 16}">{value}</text>'
        )
    h = len(data) * (bar_h + gap)
    return (f"<h3>{html.escape(title)}</h3><svg width='{width}' height='{h}' font-family='sans-serif' "
            f"font-size='13'>{''.join(rows)}</svg>")


def _table(headers: list[str], rows: list[list]) -> str:
    if not rows:
        return "<p><em>None</em></p>"
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_html(ctx: dict) -> str:
    t = ctx["totals"]
    upcoming_key = next(k for k in ctx if k.startswith("due_next_"))
    vendor_active = {f"{v['name']}": v["active"] for v in ctx["vendors"].values()}
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{html.escape(ctx['show'])} VFX Report</title>
<style>
 body{{font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#1d2433}}
 .cards{{display:flex;gap:1rem;flex-wrap:wrap}} .card{{background:#f3f5f9;border-radius:8px;padding:1rem 1.25rem}}
 .card b{{display:block;font-size:1.6rem}} table{{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}}
 th,td{{text-align:left;padding:.35rem .6rem;border-bottom:1px solid #e3e7ee;font-size:.9rem}}
 th{{background:#f3f5f9}} footer{{color:#6b7385;font-size:.8rem;margin-top:2rem}}
</style></head><body>
<h1>{html.escape(ctx['show'])}: VFX Status Report</h1>
<p>Data as of <b>{ctx['as_of']}</b>, pulled from the ShotTrack API.</p>
<div class="cards">
 <div class="card"><b>{t['shots']}</b>shots</div>
 <div class="card"><b>{t['percent_complete']}%</b>complete</div>
 <div class="card"><b>{len(ctx['overdue'])}</b>overdue</div>
 <div class="card"><b>{len(ctx['data_errors'])}</b>data errors</div>
</div>
{_bar_chart("Shots by status", t['by_status'], "#4c7bd9")}
{_bar_chart("Active shots by vendor", vendor_active, "#e08a3c")}
<h2>Overdue</h2>
{_table(["Shot", "Due", "Days late", "Status", "Vendor"],
        [[o['shot'], o['due'], o['days_late'], o['status'], o['vendor'] or '-'] for o in ctx['overdue']])}
<h2>Due in the next two weeks</h2>
{_table(["Shot", "Due", "Status", "Vendor"],
        [[u['shot'], u['due'], u['status'], u['vendor'] or '-'] for u in ctx[upcoming_key]])}
<h2>Data errors to fix in the tracker</h2>
{_table(["Shot", "Rule", "Message"],
        [[e['shot_code'] or f"row {e['row']}", e['rule'], e['message']] for e in ctx['data_errors']])}
<footer>Generated {generated} by api_report. All data is fictional sample data.</footer>
</body></html>
"""


def write_outputs(bundle: ReportBundle, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = bundle.context["as_of"]
    files = {
        out_dir / f"vfx_report_{stamp}.html": bundle.html,
        out_dir / f"vfx_issues_{stamp}.csv": bundle.issues_csv,
        out_dir / f"vfx_summary_{stamp}.json": json.dumps(bundle.context, indent=2),
    }
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")
    return list(files)


def slack_message(ctx: dict) -> dict:
    """Slack/Teams-style incoming-webhook payload."""
    t = ctx["totals"]
    late = ", ".join(f"`{o['shot']}` ({o['days_late']}d)" for o in ctx["overdue"][:5]) or "none"
    return {"text": (f"*{ctx['show']} VFX report {ctx['as_of']}*: {t['percent_complete']}% complete, "
                     f"{len(ctx['overdue'])} overdue, {len(ctx['data_errors'])} data errors.\nOverdue: {late}")}


def post_webhook(url: str, payload: dict, timeout: float = 10) -> None:
    requests.post(url, json=payload, timeout=timeout).raise_for_status()
