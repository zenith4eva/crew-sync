"""FastAPI routes. Run: .venv/Scripts/python -m uvicorn backend.api.app:app --port 8000"""
import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import config, jobs, media
from backend.reel import render

@asynccontextmanager
async def lifespan(_app):
    config.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    jobs.fail_stale()
    jobs.cleanup()
    yield


app = FastAPI(title="Crew Sync", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=4096)  # results.json carries per-frame outlines
app.add_middleware(CORSMiddleware, allow_origins=[config.ALLOWED_ORIGIN], allow_methods=["*"], allow_headers=["*"])


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
    jobs.cleanup()
    job_id = jobs.create(Path(tmp.name), ext, dancers, consent)
    background.add_task(jobs.process, job_id)
    return jobs.read_status(job_id)


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
