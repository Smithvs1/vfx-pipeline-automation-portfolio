import json

import pytest

from provenance_tracker import lineage as L
from provenance_tracker.cli import main
from provenance_tracker.simulate import Sim, fake_bytes
from provenance_tracker.store import ProvenanceStore

from .conftest import DATA


@pytest.fixture
def store():
    s = ProvenanceStore()
    s.ingest_jsonl(DATA / "genai_events.jsonl")
    yield s
    s.close()


def ev(i, type_, payload, ts=None):
    return {"event_id": f"e{i}", "type": type_, "timestamp": ts or f"2026-01-01T00:00:{i:02d}Z", "tool": "lumen",
            "show": "TST", "user_id": "u1", "payload": payload}


def test_sample_ingest_counts():
    s = ProvenanceStore()
    added, dupes, rejected = s.ingest_jsonl(DATA / "genai_events.jsonl")
    assert (dupes, len(rejected)) == (1, 1)
    assert "unknown asset upl_missing" in rejected[0].reason
    assert added == 88
    assert s.ingest_jsonl(DATA / "genai_events.jsonl")[0] == 0  # idempotent


def test_sample_file_is_reproducible(tmp_path):
    out = tmp_path / "events.jsonl"
    Sim().run()
    from provenance_tracker.simulate import main as sim_main
    sim_main(["-o", str(out)])
    assert out.read_text() == (DATA / "genai_events.jsonl").read_text()


def test_hero_lineage(store):
    tree = L.lineage(store, "out_0003")
    assert L.depth(tree) == 3
    roots = L.root_inputs(tree)
    assert [r["kind"] for r in roots] == ["uploaded_audio", "text_prompt", "text_prompt"]
    assert L._models(tree) == {"lumen-img-2", "lumen-vid-3", "lumen-vid-4-turbo"}


def test_impact_analysis(store):
    assert [r["asset_id"] for r in L.descendants(store, "out_0001")] == ["out_0002", "out_0003"]
    assert [r["asset_id"] for r in L.descendants(store, "upl_0001")] == ["out_0003"]


def test_identify_file_by_hash(store, tmp_path):
    f = tmp_path / "mystery.mp4"
    f.write_bytes(fake_bytes("out_0003"))
    found = L.identify_file(store, f)
    assert [a["asset_id"] for a in found["assets"]] == ["out_0003"]
    f.write_bytes(b"something else")
    assert L.identify_file(store, f)["assets"] == []


def test_audit_flags_reencoded_download(store):
    rows = L.downloads_audit(store)
    bad = [r for r in rows if not r["hash_match"]]
    assert len(bad) == 1 and bad[0]["show"] == "HBL"
    assert all(r["show"] == "NVD" for r in L.downloads_audit(store, "NVD"))


def test_out_of_order_events_are_sorted():
    s = ProvenanceStore()
    events = [
        (1, ev(2, "generation.completed", {"generation_id": "g1", "prompt_ids": ["p1"], "model": "m",
                                            "output": {"asset_id": "a1", "media_type": "image", "sha256": "x"}})),
        (2, ev(1, "prompt.submitted", {"prompt_id": "p1", "modality": "text", "text": "hi"})),
    ]
    added, _, rejected = s.ingest(events)
    assert (added, rejected) == (2, [])


@pytest.mark.parametrize("payload,reason", [
    ({"prompt_id": "p", "modality": "smell"}, "unknown modality"),
    ({"prompt_id": "p", "modality": "text"}, "no text"),
    ({"prompt_id": "p", "modality": "image"}, "no asset_id"),
])
def test_schema_rejections(payload, reason):
    _, _, rejected = ProvenanceStore().ingest([(1, ev(1, "prompt.submitted", payload))])
    assert reason in rejected[0].reason


def test_failed_event_leaves_no_partial_rows():
    s = ProvenanceStore()
    bad = ev(1, "generation.completed", {"generation_id": "g", "prompt_ids": ["nope"], "model": "m",
                                          "output": {"asset_id": "a", "media_type": "image", "sha256": "x"}})
    s.ingest([(1, bad)])
    assert s.db.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0


def test_tamper_detection(store):
    assert store.verify_chain() == []
    row = store.db.execute("SELECT seq, body FROM events WHERE type='prompt.submitted' LIMIT 1").fetchone()
    body = json.loads(row["body"])
    body["payload"]["text"] = "edited after the fact"
    store.db.execute("UPDATE events SET body = ? WHERE seq = ?", (json.dumps(body), row["seq"]))
    problems = store.verify_chain()
    assert len(problems) == 1 and "contents changed" in problems[0]


def test_mermaid_and_manifest(store):
    m = L.render_mermaid(L.lineage(store, "out_0003"))
    assert m.startswith("flowchart LR") and "upl_0001 -- audio prompt --> gen_0003" in m
    man = L.manifest(store, "out_0003")
    assert man["ai_generated"] and man["generations_deep"] == 3 and len(man["downloads"]) == 1


def test_cli_end_to_end(tmp_path, capsys):
    db = str(tmp_path / "p.db")
    assert main(["--db", db, "ingest", str(DATA / "genai_events.jsonl")]) == 0
    assert main(["--db", db, "lineage", "out_0003"]) == 0
    assert main(["--db", db, "audit", "--show", "HBL"]) == 0
    assert main(["--db", db, "verify"]) == 0
    assert main(["--db", db, "lineage", "nope"]) == 1
    out = capsys.readouterr().out
    assert "3 generation(s) deep" in out and "MISMATCH" in out and "hash chain verified" in out
