from production_assistant.assistant import generate_briefing, render_prompts
from production_assistant.context import build_context, known_shot_codes
from production_assistant.guardrails import find_unknown_shots
from production_assistant.providers import OfflineProvider, get_provider

from .conftest import AS_OF


class FakeLLM:
    name = "fake"

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def complete(self, system, user, context):
        self.calls.append((system, user))
        return self.reply


def test_context_numbers(shots, vendors):
    ctx = build_context(shots, vendors, AS_OF)
    assert ctx["totals"]["shots"] == 26
    assert [o["shot"] for o in ctx["overdue"]] == ["NVD_101_STM_0030", "NVD_101_ARR_0030"]
    assert ctx["vendors"]["PFX"]["active"] == 4
    assert ctx["vendors"]["ORB"]["vendor_active"] is False


def test_prompt_contains_data_and_rules(shots, vendors):
    system, user = render_prompts(build_context(shots, vendors, AS_OF))
    assert "Use ONLY the facts" in system
    assert "NVD_101_STM_0030" in user and "## Vendor check-in" in user


def test_offline_briefing_passes_guardrails(shots, vendors):
    b = generate_briefing(build_context(shots, vendors, AS_OF), OfflineProvider())
    assert b.passed_guardrails
    assert "## Headline" in b.markdown and "Pixelforge VFX" in b.markdown


def test_guardrail_catches_hallucinated_shot(shots, vendors):
    ctx = build_context(shots, vendors, AS_OF)
    llm = FakeLLM("Chase `NVD_101_ARR_0030` and also `NVD_105_XYZ_0990`.")
    b = generate_briefing(ctx, llm)
    assert b.unknown_shots == ["NVD_105_XYZ_0990"]
    assert len(llm.calls) == 1


def test_guardrail_regex():
    assert find_unknown_shots("NVD_101_ARR_0010 nvd_101_bse_60", {"NVD_101_ARR_0010"}) == ["nvd_101_bse_60"]


def test_known_codes_include_data_errors(shots, vendors):
    assert "nvd_101_bse_60" in known_shot_codes(build_context(shots, vendors, AS_OF))


def test_auto_provider_without_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert get_provider().name == "offline"
