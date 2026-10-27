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

INSTRUCTIONS = """You coach a dance crew's rehearsal. Write 3 to 5 fixes the leader can read out at the next run-through.

The data:
- dancers.<name>.timing: % of beats where that dancer hit the move with the crew (within 100 ms).
- dancers.<name>.formation: % of beats where that dancer kept even spacing and stayed on the line.
- flagged_moments: runs of beats where one dancer was off. offset_ms > 0 is late, < 0 is early. time_s is when it starts.
- dancers.<name>.pose (if present): % of beats where every limb was within 25 degrees of the crew's.
- pose_moments (if present): a limb (e.g. "left forearm") far off the crew's shape at time_s.

Rules:
- One concrete fix per note: what to do in the next rehearsal (count it slowly, drill the section, mark floor spots, watch a neighbor), not just "be on the beat".
- Put the most costly problem first. Skip dancers whose numbers are fine.
- time_s: use a flagged moment's time_s when the note is about that moment; otherwise 0. Never invent times.
- Don't read scores back as numbers; say what they mean ("late through the chorus", "drifting off the line").
- dancer is the dancer's name, or "crew" for whole-crew notes. One or two plain sentences each, no jargon.
- Only use facts in the data."""


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
