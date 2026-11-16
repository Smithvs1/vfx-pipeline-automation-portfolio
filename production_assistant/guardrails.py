"""Post-checks on LLM output. A briefing that names a shot that doesn't exist is worse than no briefing."""
from __future__ import annotations

import re

SHOT_CODE_RE = re.compile(r"\b[A-Za-z]{3}[_-]\d{3}[_-][A-Za-z]{3}[_-]\d{2,4}\b")


def find_unknown_shots(text: str, known: set[str]) -> list[str]:
    seen = dict.fromkeys(m.group(0) for m in SHOT_CODE_RE.finditer(text))
    return [code for code in seen if code not in known]
