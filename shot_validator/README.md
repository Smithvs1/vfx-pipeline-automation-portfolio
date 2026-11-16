# Project 1: Shot Data Validator

**Problem:** Before a turnover goes to vendors, or a status report goes to the studio, someone has to go through
the shot list by hand. They look for typos in shot codes, statuses nobody else uses ("done", "in progress"),
shots marked in progress with no vendor, duplicate rows, and dates in the wrong format. Each one missed causes
trouble later.

**Solution:** One command checks the whole tracker export and lists every problem, with the row number, what's
wrong, and how serious it is.

## Run it

```bash
python -m shot_validator sample_data/shots.csv --vendors sample_data/vendors.csv
python -m shot_validator sample_data/shots.csv --vendors sample_data/vendors.csv --format markdown -o report.md
python -m shot_validator my_show.csv --show HBL --as-of 2026-12-01 --format csv
```

```
ERROR row   6  NVD-101-ARR-0050   naming_convention      'NVD-101-ARR-0050' does not match NVD_<EP###>_<SEQ>_<####>
ERROR row   7  NVD_101_ARR_0060   invalid_status         status 'done' is not one of: wtg, rdy, ip, rev, apr, fin, omt, hld
ERROR row   8  NVD_101_BSE_0010   missing_vendor         status 'ip' but no vendor assigned
ERROR row  13  NVD_101_BSE_0050   inactive_vendor        assigned to inactive vendor Orbit Lane Post
WARN  row  22  NVD_102_CAV_0040   vendor_over_capacity   Pixelforge VFX has 4 active shots (limit 3)
...
FAIL  26 shots checked | 10 clean | 13 errors | 8 warnings
```

The exit code is `1` when there are errors (`--strict` also fails on warnings), so this can run in CI, as a
pre-send check, or on a schedule. Full sample report: [docs/examples/validation_report.md](../docs/examples/validation_report.md).

## Checks

| Rule | Severity | Catches |
|---|---|---|
| `missing_field` | error | empty description, status, due date, bid days (omitted shots are skipped) |
| `naming_convention` / `naming_mismatch` | error | codes that don't match `SHOW_EPISODE_SEQ_SHOT`, or don't agree with the episode or sequence columns |
| `duplicate_shot` | error | the same shot code on more than one row |
| `invalid_status` | error | statuses that aren't on the status list |
| `missing_vendor` | error / warning | shot is active with no vendor (error), or waiting and not yet awarded (warning) |
| `unknown_vendor` / `inactive_vendor` | error | vendor code not in the vendor list, or vendor marked inactive |
| `missing_artist` | warning | shot is active but has no artist |
| `frame_range` | error | non-numeric frame range, or out frame before in frame |
| `date_format` / `overdue` | error / warning | dates not in ISO format, past-due shots that are still open |
| `vendor_over_capacity` | warning | vendor has more active shots than their limit |

## Design

- `models.py`: typed `Shot` / `Vendor` / `Issue` dataclasses and CSV loaders, with clear errors when a column is missing.
- `validator.py`: each check is a small function registered with `@rule`, so adding a check is one function
  and its own test. Show code, naming pattern, status list and "as of" date all live in `ValidationConfig`.
- `report.py`: console, JSON, CSV and Markdown output. Project 2 and Project 3 reuse the same validator.
