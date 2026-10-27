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
    assert late_flags and all(8 <= f["time_s"] < 12.5 for f in late_flags), res["flags"]
    assert res["lowest_dancer"] in ("7", "13")
    assert res["dancers"]["13"]["formation"] < 90  # dancer 4 -> SAM id 13 leaves the line for 3 s
    assert res["dancers"]["1"]["formation"] == 100
    assert res["notes_source"] == "template" and res["notes"]
    assert c.get(f"/api/jobs/{job}/video").status_code == 200

    before = res["dancers"]["7"]["score"]
    swapped = c.post(f"/api/jobs/{job}/fix-swap", json={"frame": 0, "a": "7", "b": "1"}).json()
    assert swapped["dancers"]["1"]["score"] == before

    named = c.post(f"/api/jobs/{job}/settings", json={"names": {"7": "Mina"}, "bpm": 120, "first_beat": 0.5}).json()
    assert any("Mina" in n["text"] for n in named["notes"]) or named["notes"]


def test_rejects_bad_uploads(client):
    c, _ = client
    r = c.post("/api/jobs", files={"video": ("x.mp4", b"not a video", "video/mp4")}, data={"dancers": 5, "consent": "true"})
    assert r.status_code == 400
    r = c.post("/api/jobs", files={"video": ("x.avi", b"x", "video/x-msvideo")}, data={"dancers": 5, "consent": "true"})
    assert r.status_code == 400
    r = c.post("/api/jobs", files={"video": ("x.mp4", b"x", "video/mp4")}, data={"dancers": 5, "consent": "false"})
    assert r.status_code == 400
