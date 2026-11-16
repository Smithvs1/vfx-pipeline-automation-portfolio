from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .context import known_shot_codes
from .guardrails import find_unknown_shots
from .providers import LLMProvider

PROMPTS = Path(__file__).parent / "prompts"


@dataclass
class Briefing:
    markdown: str
    provider: str
    unknown_shots: list[str]

    @property
    def passed_guardrails(self) -> bool:
        return not self.unknown_shots


def render_prompts(context: dict) -> tuple[str, str]:
    system = (PROMPTS / "system.md").read_text(encoding="utf-8")
    user = (PROMPTS / "briefing.md").read_text(encoding="utf-8").format(
        show=context["show"], as_of=context["as_of"], context_json=json.dumps(context, indent=2)
    )
    return system, user


def generate_briefing(context: dict, provider: LLMProvider) -> Briefing:
    system, user = render_prompts(context)
    text = provider.complete(system, user, context)
    return Briefing(text, provider.name, find_unknown_shots(text, known_shot_codes(context)))
