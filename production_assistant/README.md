# Project 2: AI Production Assistant

**Problem:** Every morning a VFX producer needs to know what's late, which vendors to chase, and what has to be
fixed in the tracker. Writing that update by hand from a spreadsheet takes a coordinator about an hour.

**Solution:** Python works out the facts. An LLM turns them into a readable briefing and a draft email to vendors.
Then a check confirms the model didn't make anything up.

```
shots.csv + vendors.csv
   │  (Project 1 validator + plain Python math)
   ▼
context JSON ── prompts/system.md + prompts/briefing.md ──► LLM ──► Markdown briefing
   │                                                                  │
   └──────────── known shot codes ───────► guardrail check ◄──────────┘
```

## Run it

```bash
# No API key needed: uses the built-in offline writer
python -m production_assistant sample_data/shots.csv --vendors sample_data/vendors.csv

# Use a real model
export OPENAI_API_KEY=...            # or ANTHROPIC_API_KEY=...
python -m production_assistant sample_data/shots.csv --vendors sample_data/vendors.csv --provider openai

# See exactly what the model receives
python -m production_assistant sample_data/shots.csv --vendors sample_data/vendors.csv --dump-prompt
```

Sample output: [docs/examples/briefing_offline.md](../docs/examples/briefing_offline.md)

## Design choices that matter for production use

- **The model never does math.** Overdue days, percent complete and vendor load are all computed in
  `context.py`. The model only writes up numbers that are already worked out, so every figure can be checked.
- **The model only sees a summary.** It gets a short JSON summary, not the raw spreadsheet. That keeps
  the prompt small and cheap and limits what data goes to a third-party API.
- **Prompts live in their own files** (`prompts/*.md`). Producers can change tone or sections without
  touching code, and prompt changes are visible in git diffs.
- **Output check.** `guardrails.py` pulls every shot code out of the model's reply and compares it to the
  data. A briefing that names a shot that doesn't exist exits with code `2` and is never sent.
- **Swappable providers.** OpenAI-compatible (OpenAI, Azure OpenAI, Ollama, vLLM via `OPENAI_BASE_URL`),
  Anthropic, or `offline`. Each provider is one small class, and tests use a fake LLM, so CI needs no keys.
