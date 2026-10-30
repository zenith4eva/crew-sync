"""FastAPI routes. Run: .venv/Scripts/python -m uvicorn backend.api.app:app --port 8000"""
import asyncio
import json
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import config, jobs, media
from backend.pipeline import beats, labels as labels_mod
from backend.reel import render

async def _cleanup_loop():
    """Retention: delete jobs older than RETENTION_DAYS every hour, even when nobody uploads."""
    while True:
        await asyncio.to_thread(jobs.cleanup)
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(_app):
    config.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    jobs.fail_stale()
    threading.Thread(target=beats.warm, daemon=True).start()
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()


app = FastAPI(title="Crew Sync", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=4096)  # results.json carries per-frame outlines
app.add_middleware(CORSMiddleware, allow_origins=[config.ALLOWED_ORIGIN], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def no_stale_html(request, call_next):
    """index.html must revalidate so a rebuilt UI loads; hashed JS/CSS assets can cache normally."""
    response = await call_next(request)
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def _dir(job_id: str) -> Path:
    try:
        return jobs.job_dir(job_id)
    except KeyError:
        raise HTTPException(404, "Job not found") from None


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/jobs")
def create_job(background: BackgroundTasks, video: UploadFile = File(...),
               dancers: int = Form(..., ge=1, le=16), consent: bool = Form(...)):
    if not consent:
        raise HTTPException(400, "Every dancer must agree to analysis before upload.")
    tmp, ext = _receive(video)
    job_id = jobs.create(tmp, ext, dancers, consent)
    background.add_task(jobs.process, job_id)
    return jobs.read_status(job_id)


def _receive(video: UploadFile) -> tuple[Path, str]:
    """Validate an upload (type, size, length, readable) before any Meta API call. Returns (temp file, ext)."""
    ext = Path(video.filename or "").suffix.lower()
    if ext not in config.ALLOWED_EXTS:
        raise HTTPException(400, "Upload an MP4 or MOV file.")
    if jobs.jobs_today() >= config.MAX_JOBS_PER_DAY:
        raise HTTPException(429, "Daily job limit reached. Try again tomorrow.")
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir=config.DATA_DIR) as tmp:
        size = 0
        while chunk := video.file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                tmp.close()
                Path(tmp.name).unlink()
                raise HTTPException(413, f"File is over {config.MAX_UPLOAD_MB} MB.")
            tmp.write(chunk)
    try:
        info = media.probe(Path(tmp.name))
        if info["duration"] > config.MAX_CLIP_SECONDS + 0.5:
            raise media.MediaError(f"Clip is {info['duration']:.0f} s; the limit is {config.MAX_CLIP_SECONDS} s. Trim it first.")
        if info["duration"] < 3:
            raise media.MediaError("Clip is too short to score. Upload at least a few seconds.")
    except media.MediaError as e:
        Path(tmp.name).unlink()
        raise HTTPException(400, str(e)) from None
    return Path(tmp.name), ext


@app.post("/api/jobs/{job_id}/reference")
def add_reference(job_id: str, background: BackgroundTasks, video: UploadFile = File(...), mirror: bool = Form(False)):
    """A leader's or official take to score against. Tracked, then its footage is deleted; never shown."""
    d = _dir(job_id)
    _ready(job_id)
    if (jobs.read_status(job_id).get("reference") or {}).get("state") in ("queued", "running", "scoring"):
        raise HTTPException(409, "A reference is already processing.")
    tmp, ext = _receive(video)
    (d / "reference").mkdir(exist_ok=True)
    tmp.replace(d / "reference" / f"input{ext}")
    jobs.write_status(job_id, reference={"state": "queued", "mirror": mirror, "matches": {}})
    background.add_task(jobs.process_reference, job_id)
    return jobs.read_status(job_id)


class RefSettings(BaseModel):
    mirror: bool | None = None
    matches: dict[str, str] | None = None


@app.post("/api/jobs/{job_id}/reference/settings")
def reference_settings(job_id: str, s: RefSettings):
    st = _ready(job_id)
    if (st.get("reference") or {}).get("state") != "done":
        raise HTTPException(409, "No finished reference on this job.")
    changes = {k: v for k, v in s.model_dump().items() if v is not None}
    if s.mirror is not None and s.mirror != st["reference"].get("mirror"):
        changes.setdefault("matches", {})  # mirroring changes who stands where; redo the automatic match
    jobs.write_status(job_id, reference={**st["reference"], **changes})
    return _recompute(job_id, notes=False)


@app.delete("/api/jobs/{job_id}/reference")
def remove_reference(job_id: str):
    st = _ready(job_id)
    if (st.get("reference") or {}).get("state") in ("queued", "running", "scoring"):
        raise HTTPException(409, "Wait for the reference to finish processing.")
    jobs.write_status(job_id, reference=None)
    return _recompute(job_id, notes=True)


@app.get("/api/jobs/{job_id}")
def status(job_id: str):
    _dir(job_id)
    return jobs.read_status(job_id)


@app.post("/api/jobs/{job_id}/retry")
def retry(job_id: str, background: BackgroundTasks):
    _dir(job_id)
    if jobs.read_status(job_id)["state"] not in ("failed", "done"):
        raise HTTPException(409, "Job is still running.")
    jobs.write_status(job_id, state="queued", error=None)
    background.add_task(jobs.process, job_id)
    return jobs.read_status(job_id)


@app.delete("/api/jobs/{job_id}")
def delete(job_id: str):
    _dir(job_id)
    jobs.delete(job_id)
    return {"deleted": job_id}


@app.get("/api/jobs/{job_id}/video")
def video(job_id: str):
    path = _dir(job_id) / "video.mp4"
    if not path.exists():
        raise HTTPException(404, "Video not ready")
    return FileResponse(path, media_type="video/mp4")


@app.get("/api/jobs/{job_id}/results")
def results(job_id: str):
    path = _dir(job_id) / "results.json"
    if not path.exists():
        raise HTTPException(404, "Results not ready")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/jobs/{job_id}/reel")
def reel(job_id: str):
    """Renders on first request and whenever results changed since (rename, BPM, fix-swap)."""
    d = _dir(job_id)
    _ready(job_id)
    out, res_path = d / "reel.mp4", d / "results.json"
    if not out.exists() or out.stat().st_mtime < res_path.stat().st_mtime:
        tmp = d / "tmp_reel.mp4"
        try:
            render.render(d, json.loads(res_path.read_text(encoding="utf-8")), tmp)
        except media.MediaError as e:
            raise HTTPException(500, str(e)) from None
        tmp.replace(out)
    return FileResponse(out, media_type="video/mp4", filename="crew-sync-reel.mp4")


class Settings(BaseModel):
    names: dict[str, str] = Field(default_factory=dict)
    bpm: float | None = Field(None, ge=40, le=240)
    first_beat: float | None = Field(None, ge=0)
    regenerate_notes: bool = True


@app.post("/api/jobs/{job_id}/settings")
def settings(job_id: str, s: Settings):
    _ready(job_id)
    names = {k: v.strip()[:40] for k, v in s.names.items() if v.strip()}
    jobs.write_status(job_id, names=names, bpm=s.bpm, first_beat=s.first_beat)
    return _recompute(job_id, notes=s.regenerate_notes)


class Label(BaseModel):
    dancer: str
    time_s: float = Field(ge=0)
    kind: Literal["late", "early"]


def _labels_response(d: Path) -> dict:
    labels = json.loads((d / "labels.json").read_text(encoding="utf-8")) if (d / "labels.json").exists() else []
    res = json.loads((d / "results.json").read_text(encoding="utf-8"))
    return {"labels": labels, "agreement": labels_mod.agreement(res["flags"], res["beats"], labels)}


@app.get("/api/jobs/{job_id}/labels")
def get_labels(job_id: str):
    _ready(job_id)
    return _labels_response(_dir(job_id))


@app.put("/api/jobs/{job_id}/labels")
def put_labels(job_id: str, labels: list[Label]):
    """Hand labels for the evaluation: moments a person saw a dancer late or early. Replaces the whole list."""
    _ready(job_id)
    d = _dir(job_id)
    (d / "labels.json").write_text(json.dumps([lab.model_dump() for lab in labels]), encoding="utf-8")
    return _labels_response(d)


class Swap(BaseModel):
    frame: int = Field(ge=0)
    a: str
    b: str


@app.post("/api/jobs/{job_id}/fix-swap")
def fix_swap(job_id: str, swap: Swap):
    st = _ready(job_id)
    if swap.a == swap.b:
        raise HTTPException(400, "Pick two different dancers.")
    jobs.write_status(job_id, swaps=st["swaps"] + [swap.model_dump()])
    return _recompute(job_id, notes=False)


def _ready(job_id: str) -> dict:
    _dir(job_id)
    st = jobs.read_status(job_id)
    if st["state"] != "done":
        raise HTTPException(409, "Job isn't finished yet.")
    return st


def _recompute(job_id: str, notes: bool):
    try:
        return jobs.compute(job_id, notes=notes)
    except media.MediaError as e:
        raise HTTPException(400, str(e)) from None


# Built frontend (npm run build) served from the same origin; dev uses the Vite proxy instead.
_dist = config.ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
