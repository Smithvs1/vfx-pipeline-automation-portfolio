# Project 4: AI Asset Provenance Tracker

**Problem:** Productions now use generative-AI tools for previs, concept art, temp VO and more. Legal,
clearances and post teams need answers to questions like these:

- *Where did this file come from?* Which prompts, reference images, audio and models made it?
- *Which AI-generated files have left the tool?* Who downloaded what, and when?
- *A reference image turned out to be unlicensed. What was made from it?*
- *Can we prove this record hasn't been edited since?*

**Solution:** A tool-agnostic lineage tracker. Each tool's logs are converted into four event types, loaded
into SQLite, and connected into a lineage graph you can query. **Only metadata and content hashes are stored,
never the media itself.**

> This is a generic design built from scratch for this portfolio. The tool ("Lumen"/"Chorus"), shows, users
> and events are fictional and come from [`simulate.py`](simulate.py).

## Data model

```
asset.uploaded ─┐                         (reference image / audio / video a user supplies)
                ▼
prompt.submitted (text | image | audio | video) ──► generation.completed ──► output asset ──► asset.downloaded
                ▲                                                                 │
                └─────────────── output reused as the next prompt ◄───────────────┘
```

| Table | Purpose |
|---|---|
| `events` | append-only ledger. Each row stores `hash = sha256(prev_hash + event)`, so editing any past event breaks the chain |
| `assets` | uploads and generated outputs: media type, **sha256**, and which generation made it |
| `prompts` | one row per prompt. Text prompts store the text, media prompts point to an asset |
| `generations` + `generation_prompts` | model, parameters (seed, duration...), and the many-to-many link to prompts |
| `downloads` | who downloaded which asset and when, plus the downloaded file's hash |

## Run it

```bash
python -m provenance_tracker ingest sample_data/genai_events.jsonl   # skips duplicates, re-runs safely
python -m provenance_tracker lineage out_0003                         # full upstream tree
python -m provenance_tracker lineage out_0003 --format mermaid        # diagram
python -m provenance_tracker lineage out_0003 --format json           # portable provenance manifest
python -m provenance_tracker identify ~/Downloads/some_file.mp4       # look up a file by content hash
python -m provenance_tracker impact upl_0001                          # everything made from this asset
python -m provenance_tracker audit --show NVD                         # downloads + lineage + integrity
python -m provenance_tracker verify                                   # tamper check
```

```
out_0003 [video, generated, NVD_gen_0003.mp4]
  <- gen_0003 via lumen/lumen-vid-4-turbo by artist-03 at 2026-11-02T10:55:02Z
     + audio prompt prm_0004:
         upl_0001 [audio, upload, temp_vo_scene12_take3.wav]
     + video prompt prm_0005:
         out_0002 [video, generated, NVD_gen_0002.mp4]
           <- gen_0002 via lumen/lumen-vid-3 by artist-07
              + image prompt prm_0002:
                  out_0001 [image, generated, NVD_gen_0001.png]
                    <- gen_0001 via lumen/lumen-img-2 by artist-07
                       + text prompt prm_0001: "frozen alien moon at dusk, twin suns low on the horizon..."
              + text prompt prm_0003: "slow dolly forward across the ice, light snow falling"

3 generation(s) deep | models: lumen-img-2, lumen-vid-3, lumen-vid-4-turbo
```

Full session: [docs/examples/provenance_session.txt](../docs/examples/provenance_session.txt) ·
Manifest: [docs/examples/provenance_manifest_out_0003.json](../docs/examples/provenance_manifest_out_0003.json)

## Engineering details

- **Messy input handled:** events are sorted by timestamp, so late-arriving log lines still connect correctly.
  Duplicate deliveries are skipped by `event_id`. Events that point to unknown assets or prompts, or fail the
  schema check, are rejected with a reason instead of being half-saved.
- **All-or-nothing writes:** each event's rows and its ledger entry are saved in one transaction.
- **Recursive SQL:** impact analysis uses a `WITH RECURSIVE` query to find everything made downstream of an asset.
- **Matching by content, not filename:** `identify` hashes the file on disk, so renamed files still match.
  Downloads whose hash differs from the generated output (re-encoded or modified files) are flagged in `audit`.
- **Tamper-evident:** `verify` recomputes the hash chain and names the exact event that was changed.
- **Extensible:** to support a new AI tool, convert its logs into the four event types. Nothing downstream changes.
