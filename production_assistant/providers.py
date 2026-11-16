"""LLM back-ends. All of them take (system, user, context) and return Markdown."""
from __future__ import annotations

import os
from typing import Protocol

import requests


class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str, context: dict) -> str: ...


class OpenAIProvider:
    """Any OpenAI-compatible Chat Completions endpoint (OpenAI, Azure OpenAI, Ollama, vLLM, ...)."""

    name = "openai"

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None,
                 timeout: float = 60):
        self.api_key = api_key or os.environ["OPENAI_API_KEY"]
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.timeout = timeout

    def complete(self, system: str, user: str, context: dict) -> str:
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": 0.2,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: float = 60):
        self.api_key = api_key or os.environ["ANTHROPIC_API_KEY"]
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
        self.timeout = timeout

    def complete(self, system: str, user: str, context: dict) -> str:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            json={
                "model": self.model,
                "max_tokens": 1500,
                "temperature": 0.2,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return "".join(block.get("text", "") for block in resp.json()["content"])


class OfflineProvider:
    """Deterministic, template-based stand-in so the demo and tests run with no API key."""

    name = "offline"

    def complete(self, system: str, user: str, context: dict) -> str:
        t = context["totals"]
        overdue = context["overdue"]
        upcoming_key = next(k for k in context if k.startswith("due_next_"))
        upcoming = [u for u in context[upcoming_key] if u["status"] in {"wtg", "rdy", "hld"}]
        risk = (f"`{overdue[0]['shot']}` is {overdue[0]['days_late']} days late" if overdue
                else "no shots are overdue")

        out = [
            "## Headline",
            f"{context['show']} is **{t['percent_complete']}% complete** ({t['closed']}/{t['shots']} shots "
            f"approved, final or omitted). Biggest risk: {risk}.",
            "",
            "## Overdue & at-risk",
        ]
        out += [f"- `{o['shot']}`: due {o['due']}, **{o['days_late']} days late**, status `{o['status']}`, "
                f"vendor {o['vendor'] or 'UNASSIGNED'}" for o in overdue] or ["- Nothing overdue."]
        out += [f"- `{u['shot']}`: due {u['due']} and still `{u['status']}` "
                f"(vendor {u['vendor'] or 'UNASSIGNED'})" for u in upcoming] \
            or ["- No unstarted shots due in the next two weeks."]
        out += ["", "## Vendor check-in"]
        for vid, v in context["vendors"].items():
            cap = v["capacity"]
            load = f"{v['active']} active / limit {cap}" if cap else f"{v['active']} active"
            flag = ""
            if not v["vendor_active"]:
                flag = " **Vendor is inactive: reassign these shots.**"
            elif cap and v["active"] > cap:
                flag = " **Over capacity: confirm they can hold dates or rebalance.**"
            out.append(f"- **{v['name']}** ({vid}): {load}, {v['waiting']} waiting, "
                       f"{v['bid_days_open']} bid days open.{flag}")
        out += ["", "## Data cleanup before the next vendor send"]
        by_rule: dict[str, list[str]] = {}
        for e in context["data_errors"] + context["data_warnings"]:
            by_rule.setdefault(e["rule"], []).append(f"`{e['shot_code'] or 'row ' + str(e['row'])}`")
        out += [f"- **{rule}**: {', '.join(dict.fromkeys(codes))}" for rule, codes in by_rule.items()] \
            or ["- Tracker data is clean."]
        late_codes = ", ".join(o["shot"] for o in overdue) or "none"
        out += [
            "",
            "## Draft message to vendors",
            "> Hi all, quick check-in on *" + context["show"] + "*. Could you send an updated ETA and "
            f"current version for these overdue shots: {late_codes}? Please also flag any shots in the next two "
            "weeks you think are at risk so we can plan reviews. Thanks!",
        ]
        return "\n".join(out) + "\n"


def get_provider(name: str = "auto") -> LLMProvider:
    if name == "auto":
        if os.environ.get("OPENAI_API_KEY"):
            name = "openai"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            name = "anthropic"
        else:
            name = "offline"
    return {"openai": OpenAIProvider, "anthropic": AnthropicProvider, "offline": OfflineProvider}[name]()
