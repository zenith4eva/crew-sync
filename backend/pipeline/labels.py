"""Hand labels: moments a person marked as late or early while watching at quarter speed, and how well the app's
flags agree with them (PRD evaluation: "how many of the app's flags match")."""

TOLERANCE_S = 0.5


def agreement(flags: list[dict], beats: list[float], labels: list[dict]) -> dict:
    """flags as in results.json; labels: [{"dancer": id, "time_s": s, "kind": "late"|"early"}].
    A label and a flag agree when they are the same dancer and direction and the label falls inside the flag's
    beats, give or take TOLERANCE_S. precision = share of flags a person agrees with; recall = share of labels caught."""
    spans = [(f["dancer"], "late" if f["offset_ms"] > 0 else "early",
              beats[f["start_beat"]] - TOLERANCE_S, beats[f["end_beat"]] + TOLERANCE_S) for f in flags]
    hit = lambda lab, s: lab["dancer"] == s[0] and lab["kind"] == s[1] and s[2] <= lab["time_s"] <= s[3]
    flags_ok = sum(any(hit(lab, s) for lab in labels) for s in spans)
    labels_ok = sum(any(hit(lab, s) for s in spans) for lab in labels)
    return {"flags": len(spans), "labels": len(labels), "flags_agreed": flags_ok, "labels_caught": labels_ok,
            # with no labels yet, precision says nothing (not 0%)
            "precision": flags_ok / len(spans) if spans and labels else None,
            "recall": labels_ok / len(labels) if labels else None}
