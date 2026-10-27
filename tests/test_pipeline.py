import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from backend.pipeline import formation, score, timing, tracks

FPS = 15
BEATS = np.arange(1.0, 20.0, 0.5)  # 120 BPM
FIXTURES = Path(__file__).parent / "fixtures"


def motion(shift_s=0.0, late_beats=(), late_s=0.0, n=FPS * 21, sigma=0.1):
    t = np.arange(n) / FPS
    sig = np.zeros(n)
    for b, bt in enumerate(BEATS):
        c = bt + shift_s + (late_s if b in late_beats else 0.0)
        sig += np.exp(-0.5 * ((t - c) / sigma) ** 2)
    return sig


def crew(n=5, **late):
    sigs = {str(i): motion() for i in range(n)}
    if late:
        sigs["0"] = motion(**late)
    return {i: timing.hit_times(s, BEATS, FPS) for i, s in sigs.items()}


@pytest.mark.parametrize("shift_ms", [50, 100, 200])
def test_shift_recovered(shift_ms):
    offs = timing.offsets(crew(shift_s=shift_ms / 1000))
    measured = np.nanmedian(offs["0"]) * 1000
    assert abs(measured - shift_ms) < 25, measured


def test_crew_late_together_scores_100():
    hits = {str(i): timing.hit_times(motion(shift_s=0.15), BEATS, FPS) for i in range(4)}
    offs = timing.offsets(hits)
    assert all(timing.score(o) == 100 for o in offs.values())


def test_flags_need_consecutive_beats():
    offs = timing.offsets(crew(late_beats={4, 5, 6, 20}, late_s=0.15))
    f = timing.flags(offs, BEATS)
    assert [(x["dancer"], x["start_beat"], x["end_beat"]) for x in f] == [("0", 4, 6)]
    assert f[0]["offset_ms"] > 100
    assert timing.score(offs["0"]) == pytest.approx(100 * (len(BEATS) - 4) / len(BEATS))


def test_untracked_dancer_not_scored():
    sig = motion()
    sig[: FPS * 10] = np.nan
    hits = timing.hit_times(sig, BEATS, FPS)
    assert np.isnan(hits[BEATS < 9.5]).all() and not np.isnan(hits[BEATS > 11]).any()


def test_formation_line_and_spacing():
    line = {str(i): (i * 100.0, 500.0) for i in range(5)}
    assert all(formation.beat_ok(line, 200).values())
    off_line = {**line, "2": (200.0, 560.0)}
    assert formation.beat_ok(off_line, 200) == {"0": True, "1": True, "2": False, "3": True, "4": True}
    end_off_line = {**line, "4": (400.0, 545.0)}  # an end dancer must not tilt the fitted line
    assert formation.beat_ok(end_off_line, 130) == {"0": True, "1": True, "2": True, "3": True, "4": False}
    bunched = {**line, "4": (310.0, 500.0)}
    assert not formation.beat_ok(bunched, 200)["4"]
    assert formation.beat_ok({"0": (0, 0), "1": (1, 1)}, 200) == {}


def test_score_end_to_end_synthetic():
    n = FPS * 21
    trk = {}
    for i in range(5):
        trk[str(i)] = {"motion": motion(shift_s=0.15 if i == 0 else 0.0),
                       "feet": np.tile([i * 100.0, 500.0], (n, 1)),
                       "box": np.tile([i * 100.0, 300.0, i * 100.0 + 60, 500.0], (n, 1)),
                       "present": np.ones(n, bool)}
    res = score.run(trk, BEATS, FPS)
    assert res["lowest_dancer"] == "0"
    assert res["dancers"]["1"]["score"] == 100
    assert res["dancers"]["0"]["timing"] < 10 and res["dancers"]["0"]["formation"] == 100


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_sam_fixture_decodes(tmp_path):
    from backend.meta import sam_client
    out = tmp_path / "t.jsonl"
    sam_client.decode(FIXTURES / "sample.sam.txt", out)
    trk, n = tracks.load(out, 2)
    assert n == 1 and set(trk) == {"0", "1"}
    assert trk["0"]["box"][0].tolist() == [211, 228, 271, 255]
    x, y = trk["0"]["feet"][0]
    assert 211 <= x < 271 and 228 <= y < 255


def test_crop_iou():
    m = np.ones((10, 10), bool)
    assert tracks.crop_iou((0, 0, m), (0, 0, m)) == 1.0
    assert tracks.crop_iou((0, 0, m), (5, 0, m)) == pytest.approx(50 / 150)
    assert tracks.crop_iou((0, 0, m), (20, 0, m)) == 0.0
