Write today's VFX status briefing for **{show}** as of **{as_of}** in Markdown with exactly these sections:

## Headline
One or two sentences: overall progress and the single biggest risk.

## Overdue & at-risk
Bullet list of overdue shots (most late first), then shots due in the next two weeks that are not yet in progress.

## Vendor check-in
One bullet per vendor: active load vs. capacity, and what to ask them for today.

## Data cleanup before the next vendor send
Bullet list of data errors that must be fixed in the tracker, grouped by problem type.

## Draft message to vendors
A short, friendly email (under 120 words) asking vendors for updates on their overdue and at-risk shots.

Production data (JSON):
```json
{context_json}
```
