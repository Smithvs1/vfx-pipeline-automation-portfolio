"""AI asset provenance tracker.

    python -m provenance_tracker ingest sample_data/genai_events.jsonl
    python -m provenance_tracker lineage out_0003
    python -m provenance_tracker identify path/to/downloaded_file.mp4
    python -m provenance_tracker impact upl_0001
    python -m provenance_tracker audit --show NVD
    python -m provenance_tracker verify
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import lineage as L
from .store import ProvenanceStore

DEFAULT_DB = Path("provenance.db")


def cmd_ingest(store, args):
    added, dupes, rejected = store.ingest_jsonl(args.events)
    print(f"ingested {added} events | {dupes} duplicates skipped | {len(rejected)} rejected")
    for r in rejected:
        print(f"  REJECTED line {r.line} ({r.event_id}): {r.reason}")
    return 0


def cmd_lineage(store, args):
    tree = L.lineage(store, args.asset_id)
    if args.format == "json":
        print(json.dumps(L.manifest(store, args.asset_id), indent=2))
    elif args.format == "mermaid":
        print(L.render_mermaid(tree))
    else:
        print(L.render_tree(tree))
        roots = L.root_inputs(tree)
        print(f"\n{L.depth(tree)} generation(s) deep | models: {', '.join(sorted(L._models(tree))) or '-'}")
        print("root inputs:")
        for r in roots:
            what = f'"{r["text"]}"' if r["kind"] == "text_prompt" else f'{r["asset_id"]} ({r.get("filename")})'
            print(f"  - {r['kind']}: {what}")
    return 0


def cmd_identify(store, args):
    found = L.identify_file(store, args.path)
    if not found["assets"] and not found["downloads"]:
        print(f"{args.path}: sha256 {found['sha256'][:16]}... has NO provenance record")
        return 1
    for a in found["assets"]:
        print(f"{args.path} is {a['asset_id']} ({a['origin']} {a['media_type']}, show {a['show']})")
        print(L.render_tree(L.lineage(store, a["asset_id"]), "  "))
    if found["downloads"]:
        print("downloaded by: " + ", ".join(f"{d['user_id']} at {d['ts']}" for d in found["downloads"]))
    return 0


def cmd_impact(store, args):
    rows = L.descendants(store, args.asset_id)
    print(f"{len(rows)} generated asset(s) derive from {args.asset_id}:")
    for r in rows:
        print(f"  {r['asset_id']}  {r['media_type']:<6} {r['show']}  downloaded {r['download_count']}x")
    return 0


def cmd_audit(store, args):
    rows = L.downloads_audit(store, args.show)
    if args.format == "json":
        payload = {"downloads": rows}
        if args.show:
            payload["summary"] = L.show_summary(store, args.show)
        print(json.dumps(payload, indent=2))
        return 0
    if args.show:
        s = L.show_summary(store, args.show)
        print(f"Show {s['show']}: {s['generated_assets']} AI-generated assets, {s['downloaded_assets']} downloaded "
              f"({s['downloads']} downloads) by {s['users']} users")
        print(f"  prompts by modality: {s['prompts_by_modality']}")
        print(f"  generations by model: {s['generations_by_model']}\n")
    print(f"{'download':<9} {'show':<4} {'user':<10} {'asset':<9} {'type':<6} {'depth':<5} {'hash':<9} models")
    for r in rows:
        flag = "ok" if r["hash_match"] else "MISMATCH"
        print(f"{r['download_id']:<9} {r['show']:<4} {r['user_id']:<10} {r['asset_id']:<9} {r['media_type']:<6} "
              f"{r['generations_deep']:<5} {flag:<9} {', '.join(r['models'])}")
    bad = [r for r in rows if not r["hash_match"]]
    if bad:
        print(f"\n{len(bad)} download(s) don't match the generated file's hash (modified or re-encoded after download)")
    return 0


def cmd_verify(store, args):
    problems = store.verify_chain()
    n = store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    if problems:
        print(f"LEDGER TAMPERED: {len(problems)} problem(s) in {n} events")
        for p in problems:
            print("  " + p)
        return 1
    print(f"ledger intact: {n} events, hash chain verified")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="provenance_tracker", description=__doc__.splitlines()[0])
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite database (default: {DEFAULT_DB})")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ingest", help="load a JSONL event log")
    s.add_argument("events", type=Path)
    s.set_defaults(fn=cmd_ingest)
    s = sub.add_parser("lineage", help="show where an asset came from")
    s.add_argument("asset_id")
    s.add_argument("--format", choices=["tree", "json", "mermaid"], default="tree")
    s.set_defaults(fn=cmd_lineage)
    s = sub.add_parser("identify", help="look up a file on disk by its content hash")
    s.add_argument("path", type=Path)
    s.set_defaults(fn=cmd_identify)
    s = sub.add_parser("impact", help="list everything generated downstream of an asset")
    s.add_argument("asset_id")
    s.set_defaults(fn=cmd_impact)
    s = sub.add_parser("audit", help="every download with lineage + integrity check")
    s.add_argument("--show")
    s.add_argument("--format", choices=["table", "json"], default="table")
    s.set_defaults(fn=cmd_audit)
    s = sub.add_parser("verify", help="check the tamper-evident event ledger")
    s.set_defaults(fn=cmd_verify)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = ProvenanceStore(args.db)
    try:
        return args.fn(store, args)
    except KeyError as exc:
        print(f"ERROR: {exc.args[0]}", file=sys.stderr)
        return 1
    finally:
        store.close()
