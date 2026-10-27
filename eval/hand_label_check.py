"""Compare the app's flagged moments with moments a person marked by watching the clip at quarter speed.

Label file (eval/hand_labels/<anything>.json), one entry per moment a dancer is visibly late or early:
    [{"dancer": "Mina", "time_s": 42.1, "kind": "late"}, {"dancer": "Dancer 3", "time_s": 50.0, "kind": "early"}]
Use the names shown on the results page ("Dancer 3" if unnamed).

A label and a flag agree when they name the same dancer, the same direction, and the label's time falls inside the
flag's beats, give or take TOLERANCE_S. Reports how many app flags a person agrees with (precision) and how many
labelled moments the app caught (recall).

Usage: python -m eval.hand_label_check <job_id> eval/hand_labels/clip1.json
"""
import json
import sys
from pathlib import Path

from backend import jobs

TOLERANCE_S = 0.5


def agreement(flags: list[dict], beats: list[float], labels: list[dict], name) -> dict:
    """flags as in results.json; name(dancer_id) -> display name. Returns matched counts, precision and recall."""
    spans = [(name(f["dancer"]), "late" if f["offset_ms"] > 0 else "early",
              beats[f["start_beat"]] - TOLERANCE_S, beats[f["end_beat"]] + TOLERANCE_S) for f in flags]
    hit = lambda lab, s: lab["dancer"].strip().lower() == s[0].lower() and lab["kind"] == s[1] and s[2] <= lab["time_s"] <= s[3]
    flags_ok = sum(any(hit(lab, s) for lab in labels) for s in spans)
    labels_ok = sum(any(hit(lab, s) for s in spans) for lab in labels)
    return {"flags": len(spans), "labels": len(labels), "flags_agreed": flags_ok, "labels_caught": labels_ok,
            "precision": flags_ok / len(spans) if spans else None, "recall": labels_ok / len(labels) if labels else None}


def main() -> None:
    job_id, label_path = sys.argv[1], Path(sys.argv[2])
    st = jobs.read_status(job_id)
    res = json.loads((jobs.job_dir(job_id) / "results.json").read_text(encoding="utf-8"))
    order = sorted(res["dancers"], key=lambda i: (len(i), i))
    name = lambda i: st["names"].get(i) or f"Dancer {order.index(i) + 1}"
    r = agreement(res["flags"], res["beats"], json.loads(label_path.read_text(encoding="utf-8")), name)
    pct = lambda v: "n/a" if v is None else f"{v:.0%}"
    print(f"{r['flags_agreed']}/{r['flags']} app flags match a hand label (precision {pct(r['precision'])})")
    print(f"{r['labels_caught']}/{r['labels']} hand labels caught by the app (recall {pct(r['recall'])})")


if __name__ == "__main__":
    main()
