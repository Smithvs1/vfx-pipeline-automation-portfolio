from shot_validator import Severity, ValidationConfig, validate
from shot_validator.cli import main
from shot_validator.models import Shot

from .conftest import AS_OF, DATA


def make_shot(**kw):
    base = dict(row=2, shot_code="NVD_101_ARR_0010", episode="101", sequence="ARR", description="x",
                status="ip", vendor_id="PFX", artist="A", frame_in="1001", frame_out="1050",
                due_date="2026-12-01", bid_days="3")
    return Shot(**{**base, **kw})


def rules_for(shot, vendors):
    return {i.rule for i in validate([shot], vendors, ValidationConfig(as_of=AS_OF))}


def test_clean_shot_has_no_issues(vendors):
    assert rules_for(make_shot(), vendors) == set()


def test_each_rule_fires(vendors):
    assert "naming_convention" in rules_for(make_shot(shot_code="NVD-101-ARR-0010"), vendors)
    assert "naming_mismatch" in rules_for(make_shot(episode="102"), vendors)
    assert "invalid_status" in rules_for(make_shot(status="done"), vendors)
    assert "missing_field" in rules_for(make_shot(description=""), vendors)
    assert "missing_vendor" in rules_for(make_shot(vendor_id=""), vendors)
    assert "unknown_vendor" in rules_for(make_shot(vendor_id="ZZZ"), vendors)
    assert "inactive_vendor" in rules_for(make_shot(vendor_id="ORB"), vendors)
    assert "frame_range" in rules_for(make_shot(frame_in="1100"), vendors)
    assert "date_format" in rules_for(make_shot(due_date="12/01/2026"), vendors)
    assert "overdue" in rules_for(make_shot(due_date="2026-11-01"), vendors)
    assert "missing_artist" in rules_for(make_shot(artist=""), vendors)


def test_closed_and_omitted_shots_are_not_nagged(vendors):
    assert rules_for(make_shot(status="fin", due_date="2026-01-01"), vendors) == set()
    assert rules_for(make_shot(status="omt", due_date="", bid_days="", vendor_id=""), vendors) == set()


def test_duplicates_flag_every_copy(vendors):
    issues = validate([make_shot(row=2), make_shot(row=3)], vendors, ValidationConfig(as_of=AS_OF))
    assert sorted(i.row for i in issues if i.rule == "duplicate_shot") == [2, 3]


def test_vendor_capacity(vendors):
    shots = [make_shot(row=i, shot_code=f"NVD_101_ARR_{i:04d}") for i in range(2, 6)]  # PFX limit is 3
    issues = validate(shots, vendors, ValidationConfig(as_of=AS_OF))
    assert sum(i.rule == "vendor_over_capacity" for i in issues) == 4


def test_custom_show_code(vendors):
    shot = make_shot(shot_code="HBL_101_ARR_0010")
    assert "naming_convention" in rules_for(shot, vendors)
    assert not validate([shot], vendors, ValidationConfig(show_code="HBL", as_of=AS_OF))


def test_sample_data_snapshot(shots, vendors):
    issues = validate(shots, vendors, ValidationConfig(as_of=AS_OF))
    errors = [i for i in issues if i.severity == Severity.ERROR]
    assert len(shots) == 26
    assert len(errors) == 13
    assert {i.shot_code for i in errors if i.rule == "naming_convention"} == {"NVD-101-ARR-0050", "nvd_101_bse_60"}


def test_cli_exit_codes(tmp_path, capsys):
    args = [str(DATA / "shots.csv"), "--vendors", str(DATA / "vendors.csv"), "--as-of", "2026-11-16"]
    assert main(args + ["--format", "json", "-o", str(tmp_path / "r.json")]) == 1
    assert (tmp_path / "r.json").read_text().startswith("{")
    clean = tmp_path / "clean.csv"
    lines = (DATA / "shots.csv").read_text().splitlines()
    clean.write_text("\n".join(lines[:3]) + "\n")  # header + 2 final/approved shots
    assert main([str(clean), "--vendors", str(DATA / "vendors.csv"), "--as-of", "2026-11-16"]) == 0
