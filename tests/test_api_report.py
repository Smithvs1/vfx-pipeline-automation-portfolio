import json

import pytest

from api_report.cli import main
from api_report.client import ApiError, ShotTrackClient
from api_report.mock_server import DEMO_TOKEN, MockServer, ServerState
from api_report.pipeline import build_report, slack_message, write_outputs

from .conftest import AS_OF


@pytest.fixture
def server():
    with MockServer() as s:
        yield s


def test_pagination_collects_everything(server):
    client = ShotTrackClient(server.url, DEMO_TOKEN)
    assert len(client.shots(per_page=7)) == 26
    assert len(client.vendors()) == 4


def test_filters(server):
    client = ShotTrackClient(server.url, DEMO_TOKEN)
    assert {s["vendor_id"] for s in client.shots(vendor_id="PFX")} == {"PFX"}


def test_bad_token(server):
    with pytest.raises(ApiError, match="401"):
        ShotTrackClient(server.url, "wrong").shots()


def test_retries_through_429_and_503():
    with MockServer(state=ServerState(flaky_every=2)) as s:
        client = ShotTrackClient(s.url, DEMO_TOKEN, backoff=0)
        assert len(client.shots()) == 26
        assert s.state.request_count > 3


def test_report_outputs(server, tmp_path):
    bundle = build_report(ShotTrackClient(server.url, DEMO_TOKEN), AS_OF)
    files = write_outputs(bundle, tmp_path)
    assert {f.suffix for f in files} == {".html", ".csv", ".json"}
    html = next(f for f in files if f.suffix == ".html").read_text()
    assert "<svg" in html and "NVD_101_STM_0030" in html
    assert json.loads(next(f for f in files if f.suffix == ".json").read_text())["totals"]["shots"] == 26
    assert "2 overdue" in slack_message(bundle.context)["text"]


def test_cli_mock(tmp_path, capsys):
    assert main(["--mock", "--flaky", "--as-of", "2026-11-16", "--out", str(tmp_path)]) == 0
    assert "26 shots fetched" in capsys.readouterr().out
