from __future__ import annotations

import csv
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Shot:
    row: int
    shot_code: str
    episode: str
    sequence: str
    description: str
    status: str
    vendor_id: str
    artist: str
    frame_in: str
    frame_out: str
    due_date: str
    bid_days: str

    @classmethod
    def from_row(cls, row_number: int, row: dict[str, str]) -> Shot:
        clean = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        return cls(row=row_number, **{f: clean.get(f, "") for f in _SHOT_FIELDS})


_SHOT_FIELDS = [f for f in Shot.__dataclass_fields__ if f != "row"]


@dataclass(frozen=True)
class Vendor:
    vendor_id: str
    name: str
    active: bool
    max_active_shots: int


@dataclass(frozen=True)
class Issue:
    row: int
    shot_code: str
    rule: str
    severity: Severity
    message: str
    field: str = ""

    def to_dict(self) -> dict:
        return {
            "row": self.row,
            "shot_code": self.shot_code,
            "rule": self.rule,
            "severity": self.severity.value,
            "field": self.field,
            "message": self.message,
        }


def load_shots(path: str | Path) -> list[Shot]:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = [f for f in _SHOT_FIELDS if f not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing required columns: {', '.join(missing)}")
        # Row 1 is the header, so data starts at spreadsheet row 2.
        return [Shot.from_row(i, row) for i, row in enumerate(reader, start=2)]


def load_vendors(path: str | Path) -> dict[str, Vendor]:
    with open(path, newline="", encoding="utf-8") as fh:
        vendors = {}
        for row in csv.DictReader(fh):
            vid = row["vendor_id"].strip()
            vendors[vid] = Vendor(
                vendor_id=vid,
                name=row["name"].strip(),
                active=row["active"].strip().lower() in {"yes", "y", "true", "1"},
                max_active_shots=int(row.get("max_active_shots") or 0),
            )
        return vendors
