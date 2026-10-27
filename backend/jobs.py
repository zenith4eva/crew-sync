"""Job lifecycle. Each job is a folder under data/jobs/<id>/ with status.json holding state and user settings."""
import json
import shutil
import time
import traceback
import uuid
from pathlib import Path

import numpy as np

from backend import config, media
from backend.meta import muse_client, sam_client
from backend.pipeline import beats, score, tracks


def log(job_id: str, event: str, **fields) -> None:
    print(json.dumps({"ts": round(time.time(), 3), "job": job_id, "event": event, **fields}), flush=True)


def job_dir(job_id: str) -> Path:
    d = config.JOBS_DIR / job_id
    if not job_id.isalnum() or not d.is_dir():
        raise KeyError(job_id)
    return d


def read_status(job_id: str) -> dict:
    return json.loads((job_dir(job_id) / "status.json").read_text(encoding="utf-8"))


def write_status(job_id: str, **changes) -> dict:
    path = config.JOBS_DIR / job_id / "status.json"
    status = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    status.update(changes)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, indent=1), encoding="utf-8")
    tmp.replace(path)
    return status


def create(upload: Path, ext: str, dancers: int, consent: bool) -> str:
    job_id = uuid.uuid4().hex[:12]
    d = config.JOBS_DIR / job_id
    d.mkdir(parents=True)
    shutil.move(upload, d / f"input{ext}")
    write_status(job_id, id=job_id, state="queued", error=None, created=time.time(), consent=consent,
                 dancers=dancers, names={}, bpm=None, first_beat=None, swaps=[], warnings=[])
    log(job_id, "created", dancers=dancers)
    return job_id


def jobs_today() -> int:
    if not config.JOBS_DIR.exists():
        return 0
    return sum(1 for d in config.JOBS_DIR.iterdir() if d.is_dir() and time.time() - d.stat().st_ctime < 86400)


def cleanup() -> None:
    """Delete jobs older than RETENTION_DAYS."""
    if not config.JOBS_DIR.exists():
        return
    cutoff = time.time() - config.RETENTION_DAYS * 86400
    for d in config.JOBS_DIR.iterdir():
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)


def delete(job_id: str) -> None:
    shutil.rmtree(job_dir(job_id))


def fail_stale() -> None:
    """On startup, jobs left running by a crash or restart are marked failed so the UI can offer retry."""
    if not config.JOBS_DIR.exists():
        return
    for d in config.JOBS_DIR.iterdir():
        p = d / "status.json"
        if p.exists() and json.loads(p.read_text(encoding="utf-8")).get("state") in ("queued", "running"):
            write_status(d.name, state="failed", error="Server restarted while this job was running. Retry it.")


def process(job_id: str) -> None:
    """Full run: preprocess, SAM tracking (cached by video hash), then scoring."""
    d = config.JOBS_DIR / job_id
    try:
        write_status(job_id, state="running", step="preparing video", error=None)
        if not (d / "video.mp4").exists():
            inp = next(d.glob("input.*"))
            media.prepare(inp, d / "video.mp4", d / "audio.wav")
        write_status(job_id, step="tracking dancers with SAM 3.1")
        log(job_id, "sam_start")
        tracks_path = sam_client.track_video(d / "video.mp4")
        write_status(job_id, tracks=str(tracks_path.name), step="scoring")
        compute(job_id, notes=True)
        write_status(job_id, state="done", step=None)
        log(job_id, "done")
    except (media.MediaError, sam_client.MetaApiError) as e:
        write_status(job_id, state="failed", error=str(e), step=None)
        log(job_id, "failed", error=str(e))
    except Exception as e:  # unexpected: keep the job retryable, show a generic message, log the type only
        write_status(job_id, state="failed", error=f"Internal error ({type(e).__name__}). Retry, or report it.", step=None)
        log(job_id, "crashed", error=type(e).__name__, where=traceback.format_exc().splitlines()[-3:])


def compute(job_id: str, notes: bool) -> dict:
    """Score from cached tracks. No SAM call; Muse is called only when notes=True."""
    d = config.JOBS_DIR / job_id
    st = read_status(job_id)
    trk, n_frames = tracks.load(config.CACHE_DIR / st["tracks"], st["dancers"], st["swaps"])
    warnings = []
    if len(trk) < st["dancers"]:
        warnings.append(f"Found {len(trk)} of {st['dancers']} dancers; each is scored only where tracked.")
    if not trk:
        raise media.MediaError("No dancers were found in this video. Film the whole crew, front-facing.")
    duration = n_frames / config.FPS
    if st["bpm"]:
        grid = beats.manual(st["bpm"], st["first_beat"] or 0.0, duration)
    else:
        grid = beats.detect(str(d / "audio.wav")) if (d / "audio.wav").exists() else np.array([])
    if len(grid) < 4:
        warnings.append("Couldn't find a beat in the audio. Set the BPM by hand.")
        grid = beats.manual(120, 0.0, duration)

    res = score.run(trk, grid, config.FPS)
    res["n_frames"], res["fps"] = n_frames, config.FPS
    res["overlay"] = {i: {"box": [None if np.isnan(b[0]) else [round(v) for v in b] for b in t["box"]],
                          "feet": [None if np.isnan(p[0]) else [round(v, 1) for v in p] for p in t["feet"]],
                          "outline": t["outline"]}
                      for i, t in trk.items()}
    old = d / "results.json"
    if notes:
        res["notes"], res["notes_source"] = make_notes(res, st["names"])
    elif old.exists():
        prev = json.loads(old.read_text(encoding="utf-8"))
        res["notes"], res["notes_source"] = prev.get("notes", []), prev.get("notes_source")
    res = _clean(res)
    tmp = old.with_suffix(".tmp")
    tmp.write_text(json.dumps(res), encoding="utf-8")
    tmp.replace(old)
    write_status(job_id, warnings=warnings)
    return res


def make_notes(res: dict, names: dict) -> tuple[list, str]:
    order = sorted(res["dancers"], key=lambda i: (len(i), i))  # numeric order, same default labels as the UI
    name = lambda i: names.get(i) or f"Dancer {order.index(i) + 1}"
    summary = {
        "crew_score": round(res["crew_score"]),
        "dancers": {name(i): {"timing": _r(v["timing"]), "formation": _r(v["formation"])} for i, v in res["dancers"].items()},
        "flagged_moments": [{**f, "dancer": name(f["dancer"])} for f in res["flags"][:10]],
    }
    try:
        return muse_client.coaching_notes(summary), "muse"
    except sam_client.MetaApiError:
        return template_notes(res, name), "template"


def template_notes(res: dict, name) -> list[dict]:
    notes = []
    for f in sorted(res["flags"], key=lambda f: -abs(f["offset_ms"]))[:3]:
        word = "late" if f["offset_ms"] > 0 else "early"
        notes.append({"dancer": name(f["dancer"]), "time_s": f["time_s"],
                      "text": f"{name(f['dancer'])} is {abs(f['offset_ms'])} ms {word} at {_mmss(f['time_s'])}. "
                              f"Run that count slowly with the crew."})
    weak = [(i, v["formation"]) for i, v in res["dancers"].items() if not np.isnan(v["formation"]) and v["formation"] < 70]
    for i, fscore in sorted(weak, key=lambda x: x[1])[:2]:
        notes.append({"dancer": name(i), "time_s": 0, "text": f"{name(i)} is out of formation on "
                      f"{round(100 - fscore)}% of beats. Mark floor spots and check spacing to neighbors."})
    if not notes:
        notes.append({"dancer": "crew", "time_s": 0, "text": "The crew is in sync. Push energy and clean up arms next."})
    return notes


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _r(v):
    return None if v is None or np.isnan(v) else round(v)


def _clean(o):
    """NaN -> None so results.json is valid JSON."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, float) and np.isnan(o):
        return None
    return o
