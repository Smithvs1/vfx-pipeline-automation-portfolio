from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date

from .models import Issue, Severity, Shot, Vendor

# Status codes follow the common ShotGrid-style short codes.
DEFAULT_STATUSES = {
    "wtg": "Waiting to start",
    "rdy": "Ready to start",
    "ip": "In progress",
    "rev": "Pending review",
    "apr": "Approved",
    "fin": "Final",
    "omt": "Omitted",
    "hld": "On hold",
}
ACTIVE_STATUSES = {"rdy", "ip", "rev"}
CLOSED_STATUSES = {"apr", "fin", "omt"}


@dataclass
class ValidationConfig:
    show_code: str = "NVD"
    # e.g. NVD_101_ARR_0010  ->  SHOW_EPISODE_SEQUENCE_SHOT
    shot_pattern: str = r"^{show}_(?P<episode>\d{{3}})_(?P<sequence>[A-Z]{{3}})_(?P<shot>\d{{4}})$"
    statuses: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_STATUSES))
    required_fields: tuple[str, ...] = ("shot_code", "description", "status", "due_date", "bid_days")
    as_of: date = field(default_factory=date.today)

    @property
    def shot_regex(self) -> re.Pattern[str]:
        return re.compile(self.shot_pattern.format(show=re.escape(self.show_code)))


Rule = Callable[[list[Shot], dict[str, Vendor], ValidationConfig], Iterable[Issue]]
RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    RULES.append(fn)
    return fn


def _issue(shot: Shot, rule_name: str, severity: Severity, message: str, field_name: str = "") -> Issue:
    return Issue(shot.row, shot.shot_code, rule_name, severity, message, field_name)


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@rule
def required_fields(shots, vendors, cfg):
    for s in shots:
        for f in cfg.required_fields:
            if s.status == "omt" and f in {"due_date", "bid_days"}:
                continue
            if not getattr(s, f):
                yield _issue(s, "missing_field", Severity.ERROR, f"'{f}' is empty", f)


@rule
def naming_convention(shots, vendors, cfg):
    regex = cfg.shot_regex
    for s in shots:
        if not s.shot_code:
            continue
        m = regex.match(s.shot_code)
        if not m:
            yield _issue(
                s, "naming_convention", Severity.ERROR,
                f"'{s.shot_code}' does not match {cfg.show_code}_<EP###>_<SEQ>_<####>", "shot_code",
            )
            continue
        if s.episode and m["episode"] != s.episode:
            yield _issue(s, "naming_mismatch", Severity.ERROR,
                         f"shot code episode {m['episode']} != episode column {s.episode}", "episode")
        if s.sequence and m["sequence"] != s.sequence:
            yield _issue(s, "naming_mismatch", Severity.ERROR,
                         f"shot code sequence {m['sequence']} != sequence column {s.sequence}", "sequence")


@rule
def duplicate_codes(shots, vendors, cfg):
    counts = Counter(s.shot_code for s in shots if s.shot_code)
    for s in shots:
        if counts[s.shot_code] > 1:
            yield _issue(s, "duplicate_shot", Severity.ERROR,
                         f"shot code appears {counts[s.shot_code]} times", "shot_code")


@rule
def valid_status(shots, vendors, cfg):
    allowed = ", ".join(cfg.statuses)
    for s in shots:
        if s.status and s.status not in cfg.statuses:
            yield _issue(s, "invalid_status", Severity.ERROR,
                         f"status '{s.status}' is not one of: {allowed}", "status")


@rule
def vendor_assignment(shots, vendors, cfg):
    for s in shots:
        if not s.vendor_id:
            if s.status in ACTIVE_STATUSES:
                yield _issue(s, "missing_vendor", Severity.ERROR,
                             f"status '{s.status}' but no vendor assigned", "vendor_id")
            elif s.status in {"wtg", ""}:
                yield _issue(s, "missing_vendor", Severity.WARNING,
                             "not yet awarded to a vendor", "vendor_id")
            continue
        vendor = vendors.get(s.vendor_id)
        if vendor is None:
            yield _issue(s, "unknown_vendor", Severity.ERROR,
                         f"vendor '{s.vendor_id}' is not in the vendor list", "vendor_id")
        elif not vendor.active and s.status not in CLOSED_STATUSES:
            yield _issue(s, "inactive_vendor", Severity.ERROR,
                         f"assigned to inactive vendor {vendor.name}", "vendor_id")


@rule
def artist_assignment(shots, vendors, cfg):
    for s in shots:
        if s.status in ACTIVE_STATUSES and not s.artist:
            yield _issue(s, "missing_artist", Severity.WARNING,
                         f"status '{s.status}' but no artist assigned", "artist")


@rule
def frame_range(shots, vendors, cfg):
    for s in shots:
        try:
            fin, fout = int(s.frame_in), int(s.frame_out)
        except ValueError:
            yield _issue(s, "frame_range", Severity.ERROR,
                         f"frame range '{s.frame_in}-{s.frame_out}' is not numeric", "frame_in")
            continue
        if fout < fin:
            yield _issue(s, "frame_range", Severity.ERROR,
                         f"frame_out {fout} is before frame_in {fin}", "frame_out")


@rule
def due_dates(shots, vendors, cfg):
    for s in shots:
        if not s.due_date:
            continue
        d = _parse_date(s.due_date)
        if d is None:
            yield _issue(s, "date_format", Severity.ERROR,
                         f"due_date '{s.due_date}' is not YYYY-MM-DD", "due_date")
        elif d < cfg.as_of and s.status not in CLOSED_STATUSES:
            days = (cfg.as_of - d).days
            yield _issue(s, "overdue", Severity.WARNING,
                         f"due {d.isoformat()} ({days} days ago) but status is '{s.status}'", "due_date")


@rule
def vendor_capacity(shots, vendors, cfg):
    active_by_vendor: dict[str, list[Shot]] = defaultdict(list)
    for s in shots:
        if s.status in ACTIVE_STATUSES and s.vendor_id:
            active_by_vendor[s.vendor_id].append(s)
    for vid, vendor_shots in active_by_vendor.items():
        vendor = vendors.get(vid)
        if vendor and vendor.max_active_shots and len(vendor_shots) > vendor.max_active_shots:
            for s in vendor_shots:
                yield _issue(s, "vendor_over_capacity", Severity.WARNING,
                             f"{vendor.name} has {len(vendor_shots)} active shots "
                             f"(limit {vendor.max_active_shots})", "vendor_id")


def validate(shots: list[Shot], vendors: dict[str, Vendor], config: ValidationConfig | None = None) -> list[Issue]:
    cfg = config or ValidationConfig()
    issues = [issue for r in RULES for issue in r(shots, vendors, cfg)]
    return sorted(issues, key=lambda i: (i.row, i.severity != Severity.ERROR, i.rule))
