"""Lineage queries: walk backwards (where did this come from?) and forwards (what did this feed?)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .store import ProvenanceStore


def _row(r) -> dict:
    return dict(r) if r is not None else {}


def lineage(store: ProvenanceStore, asset_id: str, _seen: frozenset = frozenset()) -> dict:
    """Full upstream tree for an asset."""
    if asset_id in _seen:
        return {"asset_id": asset_id, "cycle": True}
    asset = _row(store.db.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone())
    if not asset:
        raise KeyError(f"unknown asset {asset_id}")
    node = {"asset": asset}
    if asset["origin"] == "generated":
        gen = _row(store.db.execute("SELECT * FROM generations WHERE generation_id = ?",
                                    (asset["generation_id"],)).fetchone())
        gen["params"] = json.loads(gen["params"])
        prompts = []
        for pr in store.db.execute(
            "SELECT p.* FROM prompts p JOIN generation_prompts gp USING (prompt_id) "
            "WHERE gp.generation_id = ? ORDER BY p.ts, p.prompt_id", (gen["generation_id"],)
        ):
            pnode = {"prompt": dict(pr)}
            if pr["asset_id"]:
                pnode["source"] = lineage(store, pr["asset_id"], _seen | {asset_id})
            prompts.append(pnode)
        node["generation"] = gen
        node["prompts"] = prompts
    return node


def root_inputs(tree: dict) -> list[dict]:
    """Every original human input behind an asset: text prompts and uploaded files."""
    out = []
    for p in tree.get("prompts", []):
        src = p.get("source")
        if src is None:
            out.append({"kind": "text_prompt", **p["prompt"]})
        elif src.get("asset", {}).get("origin") == "upload":
            out.append({"kind": "uploaded_" + p["prompt"]["modality"], **src["asset"],
                        "prompt_id": p["prompt"]["prompt_id"]})
        else:
            out.extend(root_inputs(src))
    return out


def depth(tree: dict) -> int:
    if "generation" not in tree:
        return 0
    return 1 + max((depth(p["source"]) for p in tree["prompts"] if "source" in p), default=0)


def descendants(store: ProvenanceStore, asset_id: str) -> list[dict]:
    """Every generated asset downstream of `asset_id` (impact analysis)."""
    rows = store.db.execute(
        """
        WITH RECURSIVE downstream(asset_id) AS (
            SELECT ?
            UNION
            SELECT g.output_asset_id
            FROM downstream d
            JOIN prompts p            ON p.asset_id = d.asset_id
            JOIN generation_prompts gp ON gp.prompt_id = p.prompt_id
            JOIN generations g        ON g.generation_id = gp.generation_id
        )
        SELECT a.*, (SELECT COUNT(*) FROM downloads dl WHERE dl.asset_id = a.asset_id) AS download_count
        FROM assets a JOIN downstream d USING (asset_id)
        WHERE a.asset_id != ?
        ORDER BY a.created_ts
        """,
        (asset_id, asset_id),
    )
    return [dict(r) for r in rows]


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def identify_file(store: ProvenanceStore, path: str | Path) -> dict:
    """'Where did this file on my drive come from?' Match by content hash; no filenames trusted."""
    digest = sha256_file(path)
    assets = [dict(r) for r in store.db.execute("SELECT * FROM assets WHERE sha256 = ?", (digest,))]
    downloads = [dict(r) for r in store.db.execute("SELECT * FROM downloads WHERE sha256 = ?", (digest,))]
    return {"file": str(path), "sha256": digest, "assets": assets, "downloads": downloads}


def downloads_audit(store: ProvenanceStore, show: str | None = None) -> list[dict]:
    """Every download with its lineage summary and an integrity check of the downloaded hash."""
    sql = ("SELECT d.*, a.sha256 AS asset_sha256, a.media_type FROM downloads d "
           "JOIN assets a USING (asset_id)")
    rows = store.db.execute(sql + (" WHERE d.show = ?" if show else "") + " ORDER BY d.ts",
                            (show,) if show else ())
    out = []
    for r in rows:
        tree = lineage(store, r["asset_id"])
        roots = root_inputs(tree)
        out.append({
            "download_id": r["download_id"],
            "ts": r["ts"],
            "show": r["show"],
            "user_id": r["user_id"],
            "asset_id": r["asset_id"],
            "media_type": r["media_type"],
            "filename": r["filename"],
            "hash_match": r["sha256"] == r["asset_sha256"],
            "generations_deep": depth(tree),
            "text_prompts": sum(1 for x in roots if x["kind"] == "text_prompt"),
            "uploaded_inputs": sorted({x["kind"].removeprefix("uploaded_")
                                       for x in roots if x["kind"] != "text_prompt"}),
            "models": sorted(_models(tree)),
        })
    return out


def _models(tree: dict) -> set[str]:
    if "generation" not in tree:
        return set()
    found = {tree["generation"]["model"]}
    for p in tree["prompts"]:
        if "source" in p:
            found |= _models(p["source"])
    return found


def show_summary(store: ProvenanceStore, show: str) -> dict:
    q = lambda sql: [dict(r) for r in store.db.execute(sql, (show,))]  # noqa: E731
    return {
        "show": show,
        "prompts_by_modality": {r["modality"]: r["n"] for r in q(
            "SELECT modality, COUNT(*) n FROM prompts WHERE show = ? GROUP BY modality ORDER BY n DESC")},
        "generations_by_model": {r["model"]: r["n"] for r in q(
            "SELECT model, COUNT(*) n FROM generations WHERE show = ? GROUP BY model ORDER BY n DESC")},
        "generated_assets": q("SELECT COUNT(*) n FROM assets WHERE show = ? AND origin = 'generated'")[0]["n"],
        "downloaded_assets": q("SELECT COUNT(DISTINCT asset_id) n FROM downloads WHERE show = ?")[0]["n"],
        "downloads": q("SELECT COUNT(*) n FROM downloads WHERE show = ?")[0]["n"],
        "users": q("SELECT COUNT(DISTINCT user_id) n FROM events WHERE show = ?")[0]["n"],
    }


# ---------- rendering ----------

def _label_asset(a: dict) -> str:
    return f"{a['asset_id']} [{a['media_type']}, {a['origin']}{', ' + a['filename'] if a.get('filename') else ''}]"


def render_tree(tree: dict, indent: str = "") -> str:
    lines = [indent + _label_asset(tree["asset"])]
    if "generation" in tree:
        g = tree["generation"]
        lines.append(f"{indent}  <- {g['generation_id']} via {g['tool']}/{g['model']} by {g['user_id']} at {g['ts']}")
        for p in tree["prompts"]:
            pr = p["prompt"]
            if pr["modality"] == "text":
                lines.append(f'{indent}     + text prompt {pr["prompt_id"]}: "{pr["text"]}"')
            else:
                lines.append(f"{indent}     + {pr['modality']} prompt {pr['prompt_id']}:")
                lines.append(render_tree(p["source"], indent + "         "))
    return "\n".join(lines)


def render_mermaid(tree: dict) -> str:
    edges, nodes = [], {}

    def walk(t: dict):
        a = t["asset"]
        nodes[a["asset_id"]] = f'{a["asset_id"]}["{a["media_type"]} {a["asset_id"]}<br/>{a["origin"]}"]'
        if "generation" not in t:
            return
        g = t["generation"]
        nodes[g["generation_id"]] = f'{g["generation_id"]}{{{{"{g["model"]}"}}}}'
        edges.append(f"{g['generation_id']} --> {a['asset_id']}")
        for p in t["prompts"]:
            pr = p["prompt"]
            if pr["modality"] == "text":
                text = (pr["text"][:40] + "...") if len(pr["text"]) > 40 else pr["text"]
                nodes[pr["prompt_id"]] = f'{pr["prompt_id"]}(["text: {text.replace(chr(34), "")}"])'
                edges.append(f"{pr['prompt_id']} --> {g['generation_id']}")
            else:
                walk(p["source"])
                edges.append(f"{p['source']['asset']['asset_id']} -- {pr['modality']} prompt --> {g['generation_id']}")

    walk(tree)
    return "flowchart LR\n" + "\n".join("    " + n for n in nodes.values()) + "\n" + \
        "\n".join("    " + e for e in dict.fromkeys(edges))


def manifest(store: ProvenanceStore, asset_id: str) -> dict:
    """A portable provenance record for one asset (C2PA-inspired, not a C2PA implementation)."""
    tree = lineage(store, asset_id)
    downloads = [dict(r) for r in store.db.execute(
        "SELECT download_id, user_id, ts, filename, sha256 FROM downloads WHERE asset_id = ? ORDER BY ts",
        (asset_id,))]
    return {
        "manifest_version": "1.0",
        "asset": tree["asset"],
        "ai_generated": tree["asset"]["origin"] == "generated",
        "models_used": sorted(_models(tree)),
        "generations_deep": depth(tree),
        "root_inputs": root_inputs(tree),
        "downloads": downloads,
        "lineage": tree,
    }
