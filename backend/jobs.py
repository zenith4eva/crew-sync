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
from backend.pipeline import beats, pose, reference, score, tracks


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
        if not p.exists():
            continue
        st = json.loads(p.read_text(encoding="utf-8"))
        if st.get("state") in ("queued", "running"):
            write_status(d.name, state="failed", error="Server restarted while this job was running. Retry it.")
        if (st.get("reference") or {}).get("state") in ("queued", "running", "scoring"):
            shutil.rmtree(d / "reference", ignore_errors=True)  # never keep reference footage around
            _ref_status(d.name, state="failed", error="Server restarted while the reference was processing. Upload it again.")


def process(job_id: str) -> None:
    """Full run: preprocess, SAM tracking (cached by video hash), then scoring."""
    d = config.JOBS_DIR / job_id
    try:
        write_status(job_id, state="running", step="preparing video", error=None)
        if not (d / "video.mp4").exists():
            inp = next(d.glob("input.*"))
            media.prepare(inp, d / "video.mp4", d / "audio.wav")
        if "camera_motion" not in read_status(job_id):
            write_status(job_id, camera_motion=media.camera_motion(d / "video.mp4"))
        write_status(job_id, step="tracking dancers with SAM 3.1")
        log(job_id, "sam_start")
        tracks_path = sam_client.track_video(d / "video.mp4")
        write_status(job_id, tracks=str(tracks_path.name))
        if config.POSE_PYTHON:
            write_status(job_id, step="estimating body pose with SAM 3D Body")
            try:
                sam_client.estimate_pose(d / "video.mp4", tracks_path, config.FPS, d / "pose.json")
                write_status(job_id, pose_error=None)
            except sam_client.MetaApiError as e:  # pose is optional: score without it and say why
                write_status(job_id, pose_error=str(e))
        write_status(job_id, step="scoring")
        compute(job_id, notes=True)
        write_status(job_id, state="done", step=None)
        log(job_id, "done")
    except (media.MediaError, sam_client.MetaApiError) as e:
        write_status(job_id, state="failed", error=str(e), step=None)
        log(job_id, "failed", error=str(e))
    except Exception as e:  # unexpected: keep the job retryable, show a generic message, log the type only
        write_status(job_id, state="failed", error=f"Internal error ({type(e).__name__}). Retry, or report it.", step=None)
        log(job_id, "crashed", error=type(e).__name__, where=traceback.format_exc().splitlines()[-3:])


def process_reference(job_id: str) -> None:
    """Track a reference take and align it to the crew's clip by audio. The reference footage is deleted as soon as
    it is tracked: only its tracks (no pixels) are kept, and it never appears in results or the Reel."""
    d = config.JOBS_DIR / job_id / "reference"
    try:
        _ref_status(job_id, state="running", error=None)
        inp = next(d.glob("input.*"))
        media.prepare(inp, d / "video.mp4", d / "audio.wav")
        width = media.probe(d / "video.mp4")["width"]
        tracks_path = sam_client.track_video(d / "video.mp4")
        main_audio = config.JOBS_DIR / job_id / "audio.wav"
        aligned = main_audio.exists() and (d / "audio.wav").exists()
        lag = reference.align(str(main_audio), str(d / "audio.wav")) if aligned else 0.0
        # "scoring" lets compute() use the reference; "done" only once results include it, so the UI never
        # fetches results that are still crew-only.
        _ref_status(job_id, state="scoring", tracks=tracks_path.name, width=width, lag_s=round(lag, 3), aligned=aligned)
        compute(job_id, notes=True)
        _ref_status(job_id, state="done")
        log(job_id, "reference_done", lag_s=round(lag, 3))
    except (media.MediaError, sam_client.MetaApiError) as e:
        _ref_status(job_id, state="failed", error=str(e))
    except Exception as e:
        _ref_status(job_id, state="failed", error=f"Internal error ({type(e).__name__}). Try again.")
        log(job_id, "reference_crashed", error=type(e).__name__, where=traceback.format_exc().splitlines()[-3:])
    finally:
        for f in d.glob("*"):
            if f.is_file():
                f.unlink()


def _ref_status(job_id: str, **changes) -> None:
    st = read_status(job_id)
    write_status(job_id, reference={**(st.get("reference") or {}), **changes})


def _reference(st: dict, trk: dict, n_frames: int, warnings: list) -> tuple[dict, dict | None]:
    """Matched reference dancers on this clip's timeline, plus what the UI needs to show and edit the match."""
    r = st.get("reference") or {}
    if r.get("state") not in ("scoring", "done"):
        return {}, None
    ref_trk, _ = tracks.load(config.CACHE_DIR / r["tracks"], st["dancers"])
    tl = {j: reference.to_timeline(t, r["lag_s"], config.FPS, n_frames, r["width"] if r.get("mirror") else None)
          for j, t in ref_trk.items()}
    auto, frame = reference.match(trk, tl)
    matches = {**auto, **{i: j for i, j in (r.get("matches") or {}).items() if i in trk and j in tl}}
    if not r.get("aligned"):
        warnings.append("Couldn't align the reference by audio, so both takes are assumed to start together.")
    if len(matches) < len(trk):
        warnings.append(f"Matched {len(matches)} of {len(trk)} dancers to the reference; the rest are scored within the crew.")
    f = frame or 0
    ref_order = sorted(tl, key=lambda j: (np.isnan(tl[j]["feet"][f][0]), np.nan_to_num(tl[j]["feet"][f][0])))
    info = {"lag_s": r["lag_s"], "mirror": bool(r.get("mirror")), "matches": matches, "ref_order": ref_order}
    return {i: tl[j] for i, j in matches.items()}, info


def _pose_beats(d: Path, st: dict, trk: dict, grid: np.ndarray) -> list | None:
    """Per-beat pose comparison from the cached SAM 3D Body keypoints (nearest sampled frame to each beat), with
    tap-to-fix swaps applied. None when pose wasn't run for this job."""
    path = d / "pose.json"
    if not path.exists():
        return None
    kps = json.loads(path.read_text(encoding="utf-8"))
    sampled = np.array(sorted(int(f) for f in kps))
    if not sampled.size:
        return None
    per_beat = []
    for t in grid:
        f = int(sampled[np.argmin(np.abs(sampled - t * config.FPS))])
        people = {tracks.relabel(raw, f, st["swaps"]): kp for raw, kp in kps[str(f)].items()}
        per_beat.append(pose.compare({i: np.array(kp) for i, kp in people.items() if i in trk}))
    return per_beat


def compute(job_id: str, notes: bool) -> dict:
    """Score from cached tracks. No SAM call; Muse is called only when notes=True."""
    d = config.JOBS_DIR / job_id
    st = read_status(job_id)
    trk, n_frames = tracks.load(config.CACHE_DIR / st["tracks"], st["dancers"], st["swaps"])
    warnings = []
    if len(trk) < st["dancers"]:
        warnings.append(f"Found {len(trk)} of {st['dancers']} dancers; each is scored only where tracked.")
    if st.get("camera_motion", 0) > config.CAMERA_MOTION_MAX:
        warnings.append("The camera seems to move. Positions and formation are measured on screen, so film "
                        "from a tripod for accurate scores.")
    if st["dancers"] > config.MAX_RELIABLE_DANCERS:
        warnings.append(f"With more than {config.MAX_RELIABLE_DANCERS} dancers, colors can swap when dancers cross. "
                        "Watch the outlines and use Fix swap where they do.")
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

    ref, ref_info = _reference(st, trk, n_frames, warnings)
    if st.get("pose_error"):
        warnings.append(f"Body pose was skipped: {st['pose_error']}")
    res = score.run(trk, grid, config.FPS, ref=ref, pose_beats=_pose_beats(d, st, trk, grid))
    res["n_frames"], res["fps"], res["reference"] = n_frames, config.FPS, ref_info
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


def display_names(res: dict, names: dict) -> dict:
    """{dancer id: name shown in the UI}: the crew's name, else "Dancer k" in numeric id order (same as the UI)."""
    order = sorted(res["dancers"], key=lambda i: (len(i), i))
    return {i: names.get(i) or f"Dancer {k + 1}" for k, i in enumerate(order)}


def make_notes(res: dict, names: dict) -> tuple[list, str]:
    name = display_names(res, names).get
    summary = {
        "crew_score": round(res["crew_score"]),
        "dancers": {name(i): {"timing": _r(v["timing"]), "formation": _r(v["formation"]),
                              **({"pose": _r(v["pose"])} if "pose" in v else {})} for i, v in res["dancers"].items()},
        "flagged_moments": [{**f, "dancer": name(f["dancer"])} for f in res["flags"][:10]],
        **({"pose_moments": [{"dancer": name(f["dancer"]), "time_s": f["time_s"], "limb": f["limb"],
                              "degrees_off_crew": f["deg"]} for f in sorted(res["pose_flags"], key=lambda f: -f["deg"])[:10]]}
           if res.get("pose_flags") else {}),
        "measured_against": "the reference take (timing and positions vs the matched reference dancer)"
                            if res.get("reference") else "the rest of the crew",
    }
    try:
        return muse_client.coaching_notes(summary), "muse"
    except sam_client.MetaApiError:
        return template_notes(res, name), "template"


def template_notes(res: dict, name) -> list[dict]:
    notes = []
    for f in sorted(res["flags"], key=lambda f: (f.get("moving", False), -abs(f["offset_ms"])))[:3]:
        word = "late" if f["offset_ms"] > 0 else "early"
        notes.append({"dancer": name(f["dancer"]), "time_s": f["time_s"],
                      "text": f"{name(f['dancer'])} is {abs(f['offset_ms'])} ms {word} at {_mmss(f['time_s'])}. "
                              f"Run that count slowly with the crew."})
    weak = [(i, v["formation"]) for i, v in res["dancers"].items() if not np.isnan(v["formation"]) and v["formation"] < 70]
    for i, fscore in sorted(weak, key=lambda x: x[1])[:2]:
        notes.append({"dancer": name(i), "time_s": 0, "text": f"{name(i)} is out of formation on "
                      f"{round(100 - fscore)}% of beats. Mark floor spots and hold them through the count."})
    for f in sorted(res.get("pose_flags") or [], key=lambda f: -f["deg"])[:1]:
        notes.append({"dancer": name(f["dancer"]), "time_s": f["time_s"],
                      "text": f"{name(f['dancer'])}'s {f['limb']} is {f['deg']} degrees off the crew at {_mmss(f['time_s'])}. "
                              "Match the shape in the mirror with the crew."})
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
