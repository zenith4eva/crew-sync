"""SAM 3.1 video tracking client. Results are cached by video hash so a clip is only paid for once."""
import hashlib
import json
import subprocess
import time
from pathlib import Path

import httpx

from backend import config

DECODER = Path(__file__).with_name("decode_masks.mjs")


class MetaApiError(Exception):
    pass


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    h.update(f"{config.SAM_MODEL}|{config.SAM_PROMPT}|{config.SAM_MASK_ENCODING}".encode())
    return h.hexdigest()[:32]


def _with_retries(fn):
    for attempt in range(config.API_RETRIES + 1):
        try:
            return fn()
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code != 429 and code < 500 or attempt == config.API_RETRIES:
                # Response body only, never the request: keeps the key out of logs and errors.
                raise MetaApiError(f"Meta API {code}: {e.response.text[:300]}") from None
        except httpx.TransportError as e:
            if attempt == config.API_RETRIES:
                raise MetaApiError(f"Meta API unreachable: {type(e).__name__}") from None
        time.sleep(2 ** attempt)


def _headers() -> dict:
    if not config.META_API_KEY:
        raise MetaApiError("META_API_KEY is not set")
    return {"Authorization": f"Bearer {config.META_API_KEY}"}


def _upload(client: httpx.Client, video: Path) -> str:
    def go():
        with open(video, "rb") as f:
            r = client.post(f"{config.META_API_BASE}/files", headers=_headers(),
                            data={"purpose": "user_data"}, files={"file": (video.name, f)})
        r.raise_for_status()
        return r.json()["id"]
    return _with_retries(go)


def _segment(client: httpx.Client, file_id: str) -> str:
    body = {
        "model": config.SAM_MODEL,
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": config.SAM_PROMPT},
            {"type": "input_video", "file_id": file_id},
        ]}],
        "metadata": {"mask_encoding": config.SAM_MASK_ENCODING},
        "stream": True,
    }

    def go():
        parts = []
        headers = {**_headers(), "Accept": "text/event-stream"}
        with client.stream("POST", f"{config.META_API_BASE}/responses", headers=headers, json=body) as r:
            if r.is_error:
                r.read()
                r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                event = json.loads(payload)
                kind = event.get("type")
                if kind == "response.output_text.delta":
                    parts.append(event["delta"])
                elif kind == "response.completed":
                    return "".join(parts)
                elif kind in ("response.failed", "response.incomplete", "error"):
                    raise MetaApiError(f"SAM stream ended with {kind}: {json.dumps(event)[:300]}")
        raise MetaApiError("SAM stream closed before response.completed")
    return _with_retries(go)


def track_video(video: Path) -> Path:
    """Track every person in `video`. Returns a JSONL file: one line per (frame, object) with box and packed mask bits."""
    video = Path(video)
    key = _hash(video)
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    raw = config.CACHE_DIR / f"{key}.sam.txt"
    decoded = config.CACHE_DIR / f"{key}.tracks.jsonl"
    if decoded.exists():
        return decoded
    if not raw.exists():
        with httpx.Client(timeout=config.API_TIMEOUT_S) as client:
            text = _segment(client, _upload(client, video))
        tmp = raw.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(raw)
    decode(raw, decoded)
    return decoded


def decode(raw: Path, out: Path) -> None:
    tmp = out.with_suffix(".tmp")
    proc = subprocess.run(["node", str(DECODER), str(raw), str(tmp)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise MetaApiError(f"mask decode failed: {proc.stderr[-500:]}")
    tmp.replace(out)


def estimate_pose(video: Path, tracks_jsonl: Path, fps: float, out: Path) -> Path:
    """SAM 3D Body keypoints every POSE_SAMPLE_S on each SAM 3.1 box, via the runner in the pose env. Cached."""
    if out.exists():
        return out
    step = max(1, round(config.POSE_SAMPLE_S * fps))
    frames = {}
    for line in tracks_jsonl.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec["f"] % step == 0:
                frames.setdefault(str(rec["f"]), {})[rec["id"]] = rec["box"]
    job = out.with_suffix(".in.json")
    job.write_text(json.dumps({"video": str(video), "repo": config.POSE_REPO, "hf_repo": config.POSE_HF_REPO,
                               "frames": frames}), encoding="utf-8")
    tmp = out.with_suffix(".tmp")
    proc = subprocess.run([config.POSE_PYTHON, str(Path(__file__).with_name("sam3d_runner.py")), str(job), str(tmp)],
                          capture_output=True, text=True)
    job.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise MetaApiError(f"SAM 3D Body failed: {proc.stderr.strip().splitlines()[-1] if proc.stderr else proc.returncode}")
    tmp.replace(out)
    return out


if __name__ == "__main__":
    import sys
    print(track_video(Path(sys.argv[1])))
