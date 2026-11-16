# VFX Pipeline Automation & AI Workflows: Python Portfolio

[![tests](https://github.com/Smithvs1/vfx-pipeline-automation-portfolio/actions/workflows/ci.yml/badge.svg)](https://github.com/Smithvs1/vfx-pipeline-automation-portfolio/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)

These Python tools come from my work in VFX and media production. Each one automates a task I've done by hand:
checking shot data, writing status updates, pulling reports from tracking systems, and tracking where
AI-generated assets came from.

> **All data in this repository is fictional.** *Nova Drift* and *Harbor Lights* are made-up shows, and the
> vendors, artists and the generative-AI tool "Lumen" are invented. No employer code, production data or credentials are included.

| # | Project | What it shows | Run it |
|---|---|---|---|
| 1 | [**Shot Data Validator**](shot_validator/) | Rule-based checks on shot data: naming conventions, invalid statuses, missing or inactive vendors, duplicate shots, frame ranges, overdue dates, vendor capacity | `python -m shot_validator sample_data/shots.csv --vendors sample_data/vendors.csv` |
| 2 | [**AI Production Assistant**](production_assistant/) | LLM workflow: structured data → JSON summary → prompt → daily producer briefing, with a check that catches made-up shot codes. Works with OpenAI, Anthropic or an offline mode | `python -m production_assistant sample_data/shots.csv --vendors sample_data/vendors.csv` |
| 3 | [**API Automation Report**](api_report/) | REST client with auth, paging and retry/backoff (429/503) → transform → HTML/CSV/JSON report + Slack/Teams webhook. Ships with a mock tracker API | `python -m api_report --mock --flaky` |
| 4 | [**AI Asset Provenance Tracker**](provenance_tracker/) | Lineage for generative-AI assets: text, image, audio and video prompts → generations → outputs → downloads. Uses SQLite, recursive lineage queries, file lookup by content hash, impact analysis and a tamper-evident hash-chained event log | `python -m provenance_tracker ingest sample_data/genai_events.jsonl` |

## Quick start

```bash
git clone https://github.com/Smithvs1/vfx-pipeline-automation-portfolio.git
cd vfx-pipeline-automation-portfolio
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
./demo.sh            # runs all four projects against the sample data
pytest               # 35 tests
```

None of the projects need an API key. Project 2 can use a real LLM if you set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`.

## How the projects fit together

```mermaid
flowchart LR
    T[(Shot tracker<br/>CSV / REST API)] --> V[1. Shot Data Validator]
    T --> R[3. API Automation Report]
    V --> A[2. AI Production Assistant]
    V --> R
    A --> B[Producer briefing<br/>+ vendor email draft]
    R --> H[HTML / CSV / JSON<br/>+ Slack/Teams post]
    G[(Gen-AI tool<br/>event logs)] --> P[4. Provenance Tracker]
    P --> L[Lineage, audit,<br/>file identification]
```

## Example output (committed so you can see it without running anything)

- [Validation report](docs/examples/validation_report.md): Project 1
- [Producer briefing](docs/examples/briefing_offline.md): Project 2
- [HTML status report](docs/examples/api_report/) + screenshot below: Project 3
- [Provenance CLI session](docs/examples/provenance_session.txt) and a [provenance manifest](docs/examples/provenance_manifest_out_0003.json): Project 4

![API report screenshot](docs/examples/api_report/report_screenshot.png)

Lineage of one AI-generated previs shot (Project 4, `lineage out_0003 --format mermaid`): a text prompt makes
an image, the image becomes a video, and the video is combined with an uploaded temp voice-over:

```mermaid
flowchart LR
    out_0003["video out_0003<br/>generated"]
    gen_0003{{"lumen-vid-4-turbo"}}
    upl_0001["audio upl_0001<br/>upload"]
    out_0002["video out_0002<br/>generated"]
    gen_0002{{"lumen-vid-3"}}
    out_0001["image out_0001<br/>generated"]
    gen_0001{{"lumen-img-2"}}
    prm_0001(["text: frozen alien moon at dusk, twin suns low..."])
    prm_0003(["text: slow dolly forward across the ice, light..."])
    gen_0003 --> out_0003
    upl_0001 -- audio prompt --> gen_0003
    gen_0002 --> out_0002
    gen_0001 --> out_0001
    prm_0001 --> gen_0001
    out_0001 -- image prompt --> gen_0002
    prm_0003 --> gen_0002
    out_0002 -- video prompt --> gen_0003
```

## Skills demonstrated

- **Python**: dataclasses, type hints, argparse CLIs, a simple rule registry, generators, `sqlite3` with recursive CTEs, `http.server`, `hashlib`
- **AI / LLM integration**: prompt templates kept in their own files, structured JSON input for the model, more than one provider, a fallback that runs offline, and output checks against the source data
- **APIs**: `requests` sessions, bearer auth, paging, retries with backoff and `Retry-After`, webhooks
- **Data quality and lineage**: validation rules, safe re-imports (duplicates skipped), each event saved all-or-nothing, tamper-evident audit log
- **Engineering practice**: pytest suite, ruff linting, GitHub Actions CI, reproducible sample-data generator

## About me

My background is in VFX production, and I build automation and AI-assisted workflows for media pipelines. These projects take the problems I've dealt with in production
(messy tracker data, vendor follow-ups, status reporting, AI-asset accountability) and turn them into tested,
reusable tools.
