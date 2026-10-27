"""Muse Spark coaching notes via Chat Completions with a JSON schema (dev.meta.ai/docs/structured-output)."""
import json

import httpx

from backend import config
from backend.meta.sam_client import MetaApiError, _headers, _with_retries

SCHEMA = {
    "type": "object",
    "properties": {"notes": {"type": "array", "minItems": 3, "maxItems": 5, "items": {
        "type": "object",
        "properties": {"dancer": {"type": "string"}, "time_s": {"type": "number"}, "text": {"type": "string"}},
        "required": ["dancer", "time_s", "text"], "additionalProperties": False}}},
    "required": ["notes"], "additionalProperties": False,
}

INSTRUCTIONS = (
    "You are a dance rehearsal coach. From the crew sync numbers, write 3 to 5 short, plain-language fixes "
    "a crew leader can say out loud at the next run-through. Name the dancer and the moment (time in seconds). "
    "Positive offset_ms means late, negative means early. Use \"crew\" as the dancer for whole-crew notes. "
    "Only use facts in the data."
)


def coaching_notes(summary: dict) -> list[dict]:
    """Raises MetaApiError (shared Meta API error) when Muse is unavailable; the caller falls back to templates."""
    body = {
        "model": config.MUSE_MODEL,
        "messages": [{"role": "system", "content": INSTRUCTIONS},
                     {"role": "user", "content": json.dumps(summary)}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "CoachingNotes", "schema": SCHEMA, "strict": True}},
    }

    def go():
        with httpx.Client(timeout=60) as client:
            r = client.post(f"{config.META_API_BASE}/chat/completions", headers=_headers(), json=body)
            r.raise_for_status()
            return r.json()

    data = _with_retries(go)
    try:
        return json.loads(data["choices"][0]["message"]["content"])["notes"]
    except (KeyError, IndexError, TypeError, ValueError):
        raise MetaApiError("Muse returned an unexpected response") from None
