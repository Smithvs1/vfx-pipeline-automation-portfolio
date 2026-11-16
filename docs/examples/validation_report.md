# Shot Data Validation Report

- Shots checked: **26**
- Clean shots: **10**
- Errors: **13** across 12 shots
- Warnings: **8**

## Issues by rule

| Rule | Count |
|---|---|
| `vendor_over_capacity` | 4 |
| `missing_field` | 2 |
| `overdue` | 2 |
| `naming_convention` | 2 |
| `invalid_status` | 2 |
| `missing_vendor` | 2 |
| `duplicate_shot` | 2 |
| `inactive_vendor` | 2 |
| `missing_artist` | 1 |
| `frame_range` | 1 |
| `date_format` | 1 |

## Details

| Row | Shot | Severity | Rule | Message |
|---|---|---|---|---|
| 4 | `NVD_101_ARR_0030` | error | `missing_field` | 'description' is empty |
| 4 | `NVD_101_ARR_0030` | warning | `overdue` | due 2026-11-10 (6 days ago) but status is 'ip' |
| 4 | `NVD_101_ARR_0030` | warning | `vendor_over_capacity` | Pixelforge VFX has 4 active shots (limit 3) |
| 6 | `NVD-101-ARR-0050` | error | `naming_convention` | 'NVD-101-ARR-0050' does not match NVD_<EP###>_<SEQ>_<####> |
| 7 | `NVD_101_ARR_0060` | error | `invalid_status` | status 'done' is not one of: wtg, rdy, ip, rev, apr, fin, omt, hld |
| 8 | `NVD_101_BSE_0010` | error | `missing_vendor` | status 'ip' but no vendor assigned |
| 8 | `NVD_101_BSE_0010` | warning | `missing_artist` | status 'ip' but no artist assigned |
| 11 | `NVD_101_BSE_0040` | error | `duplicate_shot` | shot code appears 2 times |
| 11 | `NVD_101_BSE_0040` | error | `frame_range` | frame_out 1040 is before frame_in 1100 |
| 12 | `NVD_101_BSE_0040` | error | `duplicate_shot` | shot code appears 2 times |
| 13 | `NVD_101_BSE_0050` | error | `inactive_vendor` | assigned to inactive vendor Orbit Lane Post |
| 14 | `nvd_101_bse_60` | error | `naming_convention` | 'nvd_101_bse_60' does not match NVD_<EP###>_<SEQ>_<####> |
| 15 | `NVD_101_STM_0010` | warning | `vendor_over_capacity` | Pixelforge VFX has 4 active shots (limit 3) |
| 17 | `NVD_101_STM_0030` | warning | `overdue` | due 2026-11-08 (8 days ago) but status is 'rev' |
| 19 | `NVD_102_CAV_0010` | warning | `missing_vendor` | not yet awarded to a vendor |
| 20 | `NVD_102_CAV_0020` | error | `missing_field` | 'bid_days' is empty |
| 22 | `NVD_102_CAV_0040` | error | `date_format` | due_date '12/19/2026' is not YYYY-MM-DD |
| 22 | `NVD_102_CAV_0040` | warning | `vendor_over_capacity` | Pixelforge VFX has 4 active shots (limit 3) |
| 23 | `NVD_102_CAV_0050` | warning | `vendor_over_capacity` | Pixelforge VFX has 4 active shots (limit 3) |
| 26 | `NVD_102_ESC_0030` | error | `inactive_vendor` | assigned to inactive vendor Orbit Lane Post |
| 27 | `NVD_102_ESC_0040` | error | `invalid_status` | status 'in progress' is not one of: wtg, rdy, ip, rev, apr, fin, omt, hld |
