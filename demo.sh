#!/usr/bin/env bash
# Runs every project against the fictional sample data.
set -uo pipefail
cd "$(dirname "$0")"
AS_OF=2026-11-16
hr() { printf '\n\033[1m=== %s ===\033[0m\n' "$1"; }

hr "1. Shot Data Validator"
python -m shot_validator sample_data/shots.csv --vendors sample_data/vendors.csv --as-of $AS_OF

hr "2. AI Production Assistant"
python -m production_assistant sample_data/shots.csv --vendors sample_data/vendors.csv --as-of $AS_OF

hr "3. API Automation Report (mock API with injected 429/503 errors)"
python -m api_report --mock --flaky --as-of $AS_OF --out reports/

hr "4. AI Asset Provenance Tracker"
rm -f demo_provenance.db
P="python -m provenance_tracker --db demo_provenance.db"
python -m provenance_tracker.simulate -o /dev/null --files-dir demo_downloads >/dev/null
$P ingest sample_data/genai_events.jsonl
$P lineage out_0003
$P identify demo_downloads/out_0003.bin
$P impact out_0001
$P audit --show HBL
$P verify
