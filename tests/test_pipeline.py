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


def test_hand_label_agreement():
    from backend.pipeline.labels import agreement
    beats = [i * 0.5 for i in range(40)]
    flags = [{"dancer": "7", "start_beat": 16, "end_beat": 19, "offset_ms": 140},   # 8.0-9.5 s, late
             {"dancer": "1", "start_beat": 30, "end_beat": 31, "offset_ms": -120}]  # 15.0-15.5 s, early
    labels = [{"dancer": "7", "time_s": 8.7, "kind": "late"},
              {"dancer": "1", "time_s": 15.2, "kind": "late"},    # wrong direction
              {"dancer": "10", "time_s": 3.0, "kind": "early"}]   # app missed it
    r = agreement(flags, beats, labels)
    assert (r["flags_agreed"], r["labels_caught"]) == (1, 1)
    assert r["precision"] == 0.5 and r["recall"] == pytest.approx(1 / 3)


def _skeleton(arm_deg=0.0, yaw_deg=0.0, shift=(0, 0, 0)):
    """MHR70-shaped keypoints: standing, right forearm raised arm_deg from hanging, whole body turned yaw_deg."""
    from backend.pipeline import pose as P
    kp = np.zeros((70, 3))
    pts = {P.L_SHOULDER: (-0.2, 1.5, 0), P.R_SHOULDER: (0.2, 1.5, 0), P.L_HIP: (-0.15, 1.0, 0), P.R_HIP: (0.15, 1.0, 0),
           P.L_ELBOW: (-0.25, 1.2, 0), P.R_ELBOW: (0.25, 1.2, 0), P.L_WRIST: (-0.25, 0.95, 0),
           P.L_KNEE: (-0.15, 0.5, 0), P.R_KNEE: (0.15, 0.5, 0), P.L_ANKLE: (-0.15, 0.05, 0), P.R_ANKLE: (0.15, 0.05, 0)}
    for k, v in pts.items():
        kp[k] = v
    a = np.radians(arm_deg)  # forearm swings forward (towards -z) from hanging down
    kp[P.R_WRIST] = kp[P.R_ELBOW] + 0.25 * np.array([0, -np.cos(a), -np.sin(a)])
    y = np.radians(yaw_deg)
    rot = np.array([[np.cos(y), 0, np.sin(y)], [0, 1, 0], [-np.sin(y), 0, np.cos(y)]])
    return kp @ rot.T + np.array(shift)


def test_pose_compares_limbs_not_facing():
    from backend.pipeline import pose as P
    crew = {"1": _skeleton(), "2": _skeleton(yaw_deg=20, shift=(3, 0, 1)), "3": _skeleton(yaw_deg=-15),
            "4": _skeleton(arm_deg=60)}
    out = P.compare(crew)
    assert max(out["2"].values()) < 1 and max(out["3"].values()) < 1  # turned dancers aren't penalized
    assert out["4"]["right forearm"] == pytest.approx(60, abs=1)
    assert max(v for k, v in out["4"].items() if k != "right forearm") < 1
    score, flags = P.scores([out, out, {}, out], ["1", "2", "3", "4"], np.array([1.0, 1.5, 2.0, 2.5]))
    assert score["1"] == 100 and score["4"] == 0
    assert flags == [  # consecutive beats merge into one run; a beat without pose ends it
        {"dancer": "4", "start_beat": 0, "end_beat": 1, "time_s": 1.0, "limb": "right forearm", "deg": 60},
        {"dancer": "4", "start_beat": 3, "end_beat": 3, "time_s": 2.5, "limb": "right forearm", "deg": 60}]


def test_score_weights_with_pose():
    assert score.dancer_score(100.0, 50.0) == pytest.approx(80)            # 0.6 / 0.4
    assert score.dancer_score(100.0, 50.0, 0.0) == pytest.approx(55)       # 0.4 / 0.3 / 0.3
    assert score.dancer_score(100.0, np.nan, 0.0) == pytest.approx(40 / 0.7)  # missing part's weight redistributed


def test_crop_iou():
    m = np.ones((10, 10), bool)
    assert tracks.crop_iou((0, 0, m), (0, 0, m)) == 1.0
    assert tracks.crop_iou((0, 0, m), (5, 0, m)) == pytest.approx(50 / 150)
    assert tracks.crop_iou((0, 0, m), (20, 0, m)) == 0.0
