import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from backend.pipeline import formation, score, timing, tracks

FPS = 15
BEATS = np.arange(1.0, 20.0, 0.5)  # 120 BPM
FIXTURES = Path(__file__).parent / "fixtures"


_rng = np.random.default_rng(7)
# Shared choreography: one move per beat with varying size and length, plus off-beat accents. Not periodic,
# like real dance, so cross-correlation has one clear answer.
MOVES = [(bt, _rng.uniform(0.3, 1.5), _rng.uniform(0.06, 0.14)) for bt in BEATS] + \
        [(bt + 0.25, _rng.uniform(0.0, 0.8), 0.08) for bt in BEATS]


def motion(shift_s=0.0, late_from=None, late_to=None, late_s=0.0, n=FPS * 21):
    t = np.arange(n) / FPS
    sig = np.zeros(n)
    for c, amp, sigma in MOVES:
        late = late_from is not None and late_from <= c < late_to
        sig += amp * np.exp(-0.5 * ((t - c - shift_s - (late_s if late else 0.0)) / sigma) ** 2)
    return sig


def crew(n=5, **late):
    sigs = {str(i): motion() for i in range(n)}
    if late:
        sigs["0"] = motion(**late)
    return timing.offsets(sigs, BEATS, FPS)


@pytest.mark.parametrize("shift_ms", [30, 50, 100, 200])
def test_shift_recovered(shift_ms):
    measured = np.nanmedian(crew(shift_s=shift_ms / 1000)["0"]) * 1000
    assert abs(measured - shift_ms) < 25, measured


def test_crew_late_together_scores_100():
    offs = timing.offsets({str(i): motion(shift_s=0.15) for i in range(4)}, BEATS, FPS)
    assert all(timing.score(o) == 100 for o in offs.values())


def test_flags_late_section_only():
    offs = crew(late_from=8.0, late_to=12.0, late_s=0.15)
    f = timing.flags(offs, BEATS)
    assert [x["dancer"] for x in f] == ["0"], f
    assert 7.0 <= f[0]["time_s"] <= 9.0 and f[0]["offset_ms"] > 100
    assert BEATS[f[0]["end_beat"]] <= 12.5
    assert 50 < timing.score(offs["0"]) < 95 and timing.score(offs["1"]) == 100


def test_untracked_dancer_not_scored():
    sig = motion()
    sig[: FPS * 10] = np.nan
    offs = timing.offsets({"0": sig, "1": motion(), "2": motion()}, BEATS, FPS)["0"]
    assert np.isnan(offs[BEATS < 9]).all() and not np.isnan(offs[(BEATS > 12) & (BEATS < 18)]).any()


def test_different_choreography_not_scored():
    other = np.random.default_rng(1).uniform(0, 1, FPS * 21)
    offs = timing.offsets({"0": other, "1": motion(), "2": motion()}, BEATS, FPS)["0"]
    assert np.isnan(offs).mean() > 0.8


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


def test_formation_skips_transitions():
    n, beat_frames = 60, np.array([0, 10, 20, 30, 40, 50])
    trk = {}
    for i in range(4):
        x = np.full(n, i * 100.0)
        x[25:] += 80 * (i % 2)  # half the crew walks to a new spot between beats 20 and 30
        trk[str(i)] = {"feet": np.stack([x, np.full(n, 500.0)], 1), "box": np.tile([0, 300, 60, 500.0], (n, 1))}
    _, per_beat = formation.scores(trk, beat_frames)
    assert per_beat[3] == {} and all(per_beat[k] for k in (0, 1, 2, 4, 5))


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


def test_dancetrack_switch_count():
    from eval.dancetrack_switches import count_switches
    a, b = [0, 0, 10, 20], [50, 0, 60, 20]
    gt = {f: {"1": a, "2": b} for f in range(6)}
    clean = {f: {"7": a, "9": b} for f in range(6)}
    assert count_switches(gt, clean)["switches"] == 0
    swapped = {f: ({"7": a, "9": b} if f < 3 else {"9": a, "7": b}) for f in range(6)}
    r = count_switches(gt, swapped)
    assert r["switches"] == 2 and r["matched"] == 1.0  # both dancers switch at the crossing
    assert count_switches(gt, {})["matched"] == 0.0

    from eval.dancetrack_switches import lasting_switches
    flip = [{"frame": 10, "gt": "1", "from": "7", "to": "9"}, {"frame": 12, "gt": "1", "from": "9", "to": "7"}]
    assert lasting_switches(flip, 20) == 0  # 2-frame flip that corrects itself
    assert lasting_switches(flip[:1], 20) == 1  # swap that never corrects
    assert lasting_switches(r["detail"], 2) == 2


def test_crop_iou():
    m = np.ones((10, 10), bool)
    assert tracks.crop_iou((0, 0, m), (0, 0, m)) == 1.0
    assert tracks.crop_iou((0, 0, m), (5, 0, m)) == pytest.approx(50 / 150)
    assert tracks.crop_iou((0, 0, m), (20, 0, m)) == 0.0
