"""Event schema. Every tool integration normalises its logs into these four event types."""
from __future__ import annotations

from dataclasses import dataclass

EVENT_TYPES = {"asset.uploaded", "prompt.submitted", "generation.completed", "asset.downloaded"}
MODALITIES = {"text", "image", "audio", "video"}
ENVELOPE = ("event_id", "type", "timestamp", "tool", "show", "user_id", "payload")

REQUIRED_PAYLOAD = {
    "asset.uploaded": ("asset_id", "media_type", "sha256"),
    "prompt.submitted": ("prompt_id", "modality"),
    "generation.completed": ("generation_id", "prompt_ids", "model", "output"),
    "asset.downloaded": ("download_id", "asset_id", "sha256"),
}


class EventError(ValueError):
    pass


@dataclass(frozen=True)
class RejectedEvent:
    line: int
    event_id: str
    reason: str


def check_event(ev: dict) -> None:
    missing = [k for k in ENVELOPE if k not in ev]
    if missing:
        raise EventError(f"missing envelope fields: {', '.join(missing)}")
    if ev["type"] not in EVENT_TYPES:
        raise EventError(f"unknown event type '{ev['type']}'")
    payload = ev["payload"]
    missing = [k for k in REQUIRED_PAYLOAD[ev["type"]] if k not in payload]
    if missing:
        raise EventError(f"{ev['type']} payload missing: {', '.join(missing)}")
    if ev["type"] == "prompt.submitted":
        modality = payload["modality"]
        if modality not in MODALITIES:
            raise EventError(f"unknown modality '{modality}'")
        if modality == "text" and not payload.get("text"):
            raise EventError("text prompt has no text")
        if modality != "text" and not payload.get("asset_id"):
            raise EventError(f"{modality} prompt has no asset_id")
    if ev["type"] == "generation.completed":
        out = payload["output"]
        if not all(k in out for k in ("asset_id", "media_type", "sha256")):
            raise EventError("generation output needs asset_id, media_type, sha256")
        if not payload["prompt_ids"]:
            raise EventError("generation has no prompt_ids")
