"""SQLite-backed provenance store with a hash-chained (tamper-evident) event ledger."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from .schema import EventError, RejectedEvent, check_event

GENESIS = "0" * 64

DDL = """
CREATE TABLE IF NOT EXISTS events (
    seq        INTEGER PRIMARY KEY,
    event_id   TEXT UNIQUE NOT NULL,
    type       TEXT NOT NULL,
    ts         TEXT NOT NULL,
    tool       TEXT NOT NULL,
    show       TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    body       TEXT NOT NULL,
    prev_hash  TEXT NOT NULL,
    hash       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
    asset_id      TEXT PRIMARY KEY,
    origin        TEXT NOT NULL CHECK (origin IN ('upload', 'generated')),
    media_type    TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    filename      TEXT,
    show          TEXT NOT NULL,
    created_by    TEXT NOT NULL,
    created_ts    TEXT NOT NULL,
    generation_id TEXT
);
CREATE INDEX IF NOT EXISTS assets_sha ON assets(sha256);
CREATE TABLE IF NOT EXISTS prompts (
    prompt_id TEXT PRIMARY KEY,
    modality  TEXT NOT NULL,
    text      TEXT,
    asset_id  TEXT REFERENCES assets(asset_id),
    show      TEXT NOT NULL,
    user_id   TEXT NOT NULL,
    ts        TEXT NOT NULL,
    tool      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS generations (
    generation_id   TEXT PRIMARY KEY,
    tool            TEXT NOT NULL,
    model           TEXT NOT NULL,
    params          TEXT NOT NULL,
    show            TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    ts              TEXT NOT NULL,
    output_asset_id TEXT NOT NULL REFERENCES assets(asset_id)
);
CREATE TABLE IF NOT EXISTS generation_prompts (
    generation_id TEXT NOT NULL REFERENCES generations(generation_id),
    prompt_id     TEXT NOT NULL REFERENCES prompts(prompt_id),
    PRIMARY KEY (generation_id, prompt_id)
);
CREATE TABLE IF NOT EXISTS downloads (
    download_id TEXT PRIMARY KEY,
    asset_id    TEXT NOT NULL REFERENCES assets(asset_id),
    user_id     TEXT NOT NULL,
    ts          TEXT NOT NULL,
    filename    TEXT,
    sha256      TEXT NOT NULL,
    size_bytes  INTEGER,
    show        TEXT NOT NULL
);
"""


def canonical(ev: dict) -> str:
    return json.dumps(ev, sort_keys=True, separators=(",", ":"))


def chain_hash(prev_hash: str, ev: dict) -> str:
    return hashlib.sha256((prev_hash + canonical(ev)).encode()).hexdigest()


class ProvenanceStore:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(DDL)

    def close(self) -> None:
        self.db.close()

    # ---------- ingest ----------

    def _last_hash(self) -> str:
        row = self.db.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        return row["hash"] if row else GENESIS

    def _exists(self, table: str, key: str, value: str) -> bool:
        return self.db.execute(f"SELECT 1 FROM {table} WHERE {key} = ?", (value,)).fetchone() is not None

    def _apply(self, ev: dict) -> None:
        p, t = ev["payload"], ev["type"]
        common = (ev["show"], ev["user_id"], ev["timestamp"])
        if t == "asset.uploaded":
            self.db.execute(
                "INSERT INTO assets VALUES (?, 'upload', ?, ?, ?, ?, ?, ?, NULL)",
                (p["asset_id"], p["media_type"], p["sha256"], p.get("filename"), *common),
            )
        elif t == "prompt.submitted":
            if p.get("asset_id") and not self._exists("assets", "asset_id", p["asset_id"]):
                raise EventError(f"prompt references unknown asset {p['asset_id']}")
            self.db.execute(
                "INSERT INTO prompts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (p["prompt_id"], p["modality"], p.get("text"), p.get("asset_id"), *common, ev["tool"]),
            )
        elif t == "generation.completed":
            for pid in p["prompt_ids"]:
                if not self._exists("prompts", "prompt_id", pid):
                    raise EventError(f"generation references unknown prompt {pid}")
            out = p["output"]
            self.db.execute(
                "INSERT INTO assets VALUES (?, 'generated', ?, ?, ?, ?, ?, ?, ?)",
                (out["asset_id"], out["media_type"], out["sha256"], out.get("filename"), *common,
                 p["generation_id"]),
            )
            self.db.execute(
                "INSERT INTO generations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (p["generation_id"], ev["tool"], p["model"], json.dumps(p.get("params", {}), sort_keys=True),
                 *common, out["asset_id"]),
            )
            self.db.executemany("INSERT INTO generation_prompts VALUES (?, ?)",
                                [(p["generation_id"], pid) for pid in p["prompt_ids"]])
        elif t == "asset.downloaded":
            if not self._exists("assets", "asset_id", p["asset_id"]):
                raise EventError(f"download references unknown asset {p['asset_id']}")
            self.db.execute(
                "INSERT INTO downloads VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (p["download_id"], p["asset_id"], ev["user_id"], ev["timestamp"], p.get("filename"),
                 p["sha256"], p.get("size_bytes"), ev["show"]),
            )

    def ingest(self, events: Iterable[tuple[int, dict]]) -> tuple[int, int, list[RejectedEvent]]:
        """Ingest (line_no, event) pairs in timestamp order. Returns (added, duplicates, rejected)."""
        added, dupes, rejected = 0, 0, []
        for line, ev in sorted(events, key=lambda x: (x[1].get("timestamp", ""), x[0])):
            eid = str(ev.get("event_id", f"line-{line}"))
            try:
                check_event(ev)
                if self._exists("events", "event_id", eid):
                    dupes += 1
                    continue
                with self.db:  # one transaction per event: all-or-nothing
                    self._apply(ev)
                    prev = self._last_hash()
                    self.db.execute(
                        "INSERT INTO events (event_id, type, ts, tool, show, user_id, body, prev_hash, hash) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (eid, ev["type"], ev["timestamp"], ev["tool"], ev["show"], ev["user_id"],
                         canonical(ev), prev, chain_hash(prev, ev)),
                    )
                added += 1
            except (EventError, sqlite3.IntegrityError) as exc:
                rejected.append(RejectedEvent(line, eid, str(exc)))
        return added, dupes, rejected

    def ingest_jsonl(self, path: str | Path):
        def read():
            with open(path, encoding="utf-8") as fh:
                for i, line in enumerate(fh, start=1):
                    if line.strip():
                        yield i, json.loads(line)
        return self.ingest(read())

    # ---------- integrity ----------

    def verify_chain(self) -> list[str]:
        """Recompute the hash chain. Returns a list of problems (empty = intact)."""
        problems, prev = [], GENESIS
        for row in self.db.execute("SELECT seq, event_id, body, prev_hash, hash FROM events ORDER BY seq"):
            if row["prev_hash"] != prev:
                problems.append(f"seq {row['seq']} ({row['event_id']}): prev_hash does not link to previous event")
            expected = chain_hash(row["prev_hash"], json.loads(row["body"]))
            if row["hash"] != expected:
                problems.append(f"seq {row['seq']} ({row['event_id']}): contents changed after ingest")
            prev = row["hash"]
        return problems
