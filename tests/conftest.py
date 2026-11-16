from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "sample_data"
AS_OF = date(2026, 11, 16)


@pytest.fixture
def shots():
    from shot_validator.models import load_shots
    return load_shots(DATA / "shots.csv")


@pytest.fixture
def vendors():
    from shot_validator.models import load_vendors
    return load_vendors(DATA / "vendors.csv")
