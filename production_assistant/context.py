"""Build the structured facts the LLM is allowed to talk about.

The model never sees the raw CSV. It gets a compact JSON digest built by
plain Python, so every number in the briefing can be traced back to code.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

from shot_validator import Severity, Shot, Vendor, validate
from shot_validator.validator import ACTIVE_STATUSES, CLOSED_STATUSES, DEFAULT_STATUSES, ValidationConfig


def _due(shot: Shot) -> date | None:
    try:
        return date.fromisoformat(shot.due_date)
    except ValueError:
        return None


def build_context(shots: list[Shot], vendors: dict[str, Vendor], as_of: date, show_name: str = "Nova Drift",
                  lookahead_days: int = 14) -> dict:
    issues = validate(shots, vendors, ValidationConfig(as_of=as_of))
    status_counts = Counter(s.status if s.status in DEFAULT_STATUSES else "invalid" for s in shots)
    closed = sum(status_counts[s] for s in CLOSED_STATUSES)

    vendor_load: dict[str, dict] = defaultdict(lambda: {"active": 0, "waiting": 0, "bid_days_open": 0, "shots": []})
    for s in shots:
        if not s.vendor_id or s.status in CLOSED_STATUSES:
            continue
        v = vendor_load[s.vendor_id]
        v["shots"].append(s.shot_code)
        if s.status in ACTIVE_STATUSES:
            v["active"] += 1
        elif s.status in {"wtg", "hld"}:
            v["waiting"] += 1
        if s.bid_days.isdigit():
            v["bid_days_open"] += int(s.bid_days)
    for vid, v in vendor_load.items():
        vendor = vendors.get(vid)
        v["name"] = vendor.name if vendor else f"UNKNOWN ({vid})"
        v["capacity"] = vendor.max_active_shots if vendor else None
        v["vendor_active"] = vendor.active if vendor else False

    horizon = as_of + timedelta(days=lookahead_days)
    upcoming = [
        {"shot": s.shot_code, "due": d.isoformat(), "status": s.status, "vendor": s.vendor_id or None}
        for s in shots
        if (d := _due(s)) and as_of <= d <= horizon and s.status not in CLOSED_STATUSES
    ]
    overdue = [
        {"shot": s.shot_code, "due": d.isoformat(), "days_late": (as_of - d).days, "status": s.status,
         "vendor": s.vendor_id or None}
        for s in shots
        if (d := _due(s)) and d < as_of and s.status not in CLOSED_STATUSES
    ]

    return {
        "show": show_name,
        "as_of": as_of.isoformat(),
        "totals": {
            "shots": len(shots),
            "closed": closed,
            "percent_complete": round(100 * closed / len(shots), 1) if shots else 0.0,
            "by_status": dict(status_counts.most_common()),
        },
        "overdue": sorted(overdue, key=lambda x: -x["days_late"]),
        f"due_next_{lookahead_days}_days": sorted(upcoming, key=lambda x: x["due"]),
        "vendors": dict(sorted(vendor_load.items())),
        "data_errors": [i.to_dict() for i in issues if i.severity == Severity.ERROR],
        "data_warnings": [i.to_dict() for i in issues if i.severity == Severity.WARNING and i.rule != "overdue"],
    }


def known_shot_codes(context: dict) -> set[str]:
    codes = set()
    for v in context["vendors"].values():
        codes.update(v["shots"])
    for items in context.values():
        if isinstance(items, list):
            codes.update(i.get("shot") or i.get("shot_code") for i in items if isinstance(i, dict))
    codes.discard(None)
    return codes
