"""Upload -> process -> results -> fix-swap through the real API, on a synthetic clip with a seeded SAM cache."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("META_API_KEY", "")
    from backend import config
    importlib.reload(config)
    from backend.api import app as app_mod
    with TestClient(app_mod.app) as c:
        yield c, tmp_path


def test_full_flow(client):
    c, data = client
    from eval import make_synthetic
    clip = make_synthetic.make(data / "clip.mp4")

    with open(clip, "rb") as f:
        r = c.post("/api/jobs", files={"video": ("clip.mp4", f, "video/mp4")}, data={"dancers": 5, "consent": "true"})
    assert r.status_code == 200, r.text
    job = r.json()["id"]

    st = c.get(f"/api/jobs/{job}").json()
    assert st["state"] == "done", st
    assert st["warnings"] == [], st["warnings"]  # beat grid found in the click track
    res = c.get(f"/api/jobs/{job}/results").json()
    assert len(res["dancers"]) == 5
    late_flags = [f for f in res["flags"] if f["dancer"] == "7"]  # dancer 2 -> SAM id 7
    assert late_flags and all(7.5 <= f["time_s"] < 12.5 and 100 < f["offset_ms"] < 200 for f in late_flags), res["flags"]
    assert res["lowest_dancer"] in ("7", "13")
    assert res["dancers"]["13"]["formation"] < 90  # dancer 4 -> SAM id 13 leaves the line for 3 s
    assert res["dancers"]["1"]["formation"] == 100
    assert res["notes_source"] == "template" and res["notes"]
    assert c.get(f"/api/jobs/{job}/video").status_code == 200

    before = res["dancers"]["7"]["score"]
    swapped = c.post(f"/api/jobs/{job}/fix-swap", json={"frame": 0, "a": "7", "b": "1"}).json()
    assert swapped["dancers"]["1"]["score"] == before

    r = c.get(f"/api/jobs/{job}/reel")
    assert r.status_code == 200
    (data / "reel.mp4").write_bytes(r.content)
    from backend import media
    info = media.probe(data / "reel.mp4")
    assert (info["width"], info["height"]) == (720, 1280) and 19 < info["duration"] < 21 and info["audio"], info

    # Hand labels: one agrees with the app's flag on the late dancer (id 1 after the swap above), one the app missed.
    labels = [{"dancer": "1", "time_s": 9.0, "kind": "late"}, {"dancer": "7", "time_s": 3.0, "kind": "early"}]
    r = c.put(f"/api/jobs/{job}/labels", json=labels).json()
    assert r["agreement"]["labels_caught"] == 1 and r["agreement"]["flags_agreed"] >= 1, r
    assert c.get(f"/api/jobs/{job}/labels").json()["labels"] == labels
    assert c.put(f"/api/jobs/{job}/labels", json=[{"dancer": "7", "time_s": 1, "kind": "sideways"}]).status_code == 422

    named = c.post(f"/api/jobs/{job}/settings", json={"names": {"7": "Mina"}, "bpm": 120, "first_beat": 0.5}).json()
    assert any("Mina" in n["text"] for n in named["notes"]) or named["notes"]


def test_reference_take(client):
    """Crew take vs a clean reference that starts 1 s later into the routine and is mirrored."""
    c, data = client
    from eval import make_synthetic
    clip = make_synthetic.make(data / "crew.mp4")
    ref = make_synthetic.make(data / "ref.mp4", fixed=True, start_s=1.0, mirror=True)
    with open(clip, "rb") as f:
        job = c.post("/api/jobs", files={"video": ("crew.mp4", f, "video/mp4")}, data={"dancers": 5, "consent": "true"}).json()["id"]
    with open(ref, "rb") as f:
        r = c.post(f"/api/jobs/{job}/reference", files={"video": ("ref.mp4", f, "video/mp4")}, data={"mirror": "true"})
    assert r.status_code == 200, r.text

    st = c.get(f"/api/jobs/{job}").json()
    assert st["reference"]["state"] == "done", st["reference"]
    assert abs(st["reference"]["lag_s"] + 1.0) < 0.05, st["reference"]  # reference started 1 s in: ref time = crew time - 1
    assert not list((data / "jobs" / job / "reference").glob("*")), "reference footage must be deleted"

    res = c.get(f"/api/jobs/{job}/results").json()
    assert res["reference"]["matches"] == {i: i for i in ("1", "4", "7", "10", "13")}, res["reference"]
    late = [f for f in res["flags"] if f["dancer"] == "7"]
    assert late and all(7.5 <= f["time_s"] < 12.5 and 100 < f["offset_ms"] < 200 for f in late), res["flags"]
    assert res["dancers"]["13"]["formation"] < res["dancers"]["1"]["formation"]

    # Wrong mirror setting scrambles the match; the API redoes it automatically.
    unmirrored = c.post(f"/api/jobs/{job}/reference/settings", json={"mirror": False}).json()
    assert unmirrored["reference"]["matches"] != res["reference"]["matches"]
    assert c.delete(f"/api/jobs/{job}/reference").json()["reference"] is None


def test_camera_motion_detected(tmp_path):
    import subprocess
    from backend import config, media
    from eval import make_synthetic
    clip = tmp_path / "still.mp4"
    make_synthetic.render(clip)
    panned = tmp_path / "panned.mp4"
    subprocess.run([media.FFMPEG, "-y", "-loglevel", "error", "-i", str(clip), "-vf",
                    "crop=iw*0.7:ih*0.7:'iw*0.3*(0.5+0.5*sin(t*1.3))':'ih*0.3*(0.5+0.5*cos(t*0.9))'",
                    "-an", str(panned)], check=True)
    assert media.camera_motion(clip) < config.CAMERA_MOTION_MAX < media.camera_motion(panned)


def test_rejects_bad_uploads(client):
    c, _ = client
    r = c.post("/api/jobs", files={"video": ("x.mp4", b"not a video", "video/mp4")}, data={"dancers": 5, "consent": "true"})
    assert r.status_code == 400
    r = c.post("/api/jobs", files={"video": ("x.avi", b"x", "video/x-msvideo")}, data={"dancers": 5, "consent": "true"})
    assert r.status_code == 400
    r = c.post("/api/jobs", files={"video": ("x.mp4", b"x", "video/mp4")}, data={"dancers": 5, "consent": "false"})
    assert r.status_code == 400
