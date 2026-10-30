"""Hand labels: moments a person marked as late or early while watching at quarter speed, plus app flags they
judged wrong, and how well the app's flags agree with them (PRD evaluation: "how many of the app's flags match")."""

TOLERANCE_S = 0.5


def agreement(flags: list[dict], beats: list[float], labels: list[dict]) -> dict:
    """flags as in results.json; labels: [{"dancer": id, "time_s": s, "kind": "late"|"early"|"wrong"}].
    A label and a flag agree when they are the same dancer and direction and the label falls inside the flag's
    beats, give or take TOLERANCE_S. A "wrong" label inside a flag's beats says that flag is false.
    precision = agreed / (agreed + wrong), over the flags a person judged; recall = share of late/early labels
    caught. Unjudged flags are counted but don't move precision."""
    spans = [(f["dancer"], "late" if f["offset_ms"] > 0 else "early",
              beats[f["start_beat"]] - TOLERANCE_S, beats[f["end_beat"]] + TOLERANCE_S) for f in flags]
    inside = lambda lab, s: lab["dancer"] == s[0] and s[2] <= lab["time_s"] <= s[3]
    hit = lambda lab, s: lab["kind"] == s[1] and inside(lab, s)
    moments = [lab for lab in labels if lab["kind"] != "wrong"]
    wrongs = [lab for lab in labels if lab["kind"] == "wrong"]
    agreed = [any(hit(lab, s) for lab in moments) for s in spans]
    wrong = [not a and any(inside(lab, s) for lab in wrongs) for a, s in zip(agreed, spans)]
    labels_ok = sum(any(hit(lab, s) for s in spans) for lab in moments)
    judged = sum(agreed) + sum(wrong)
    return {"flags": len(spans), "labels": len(moments), "flags_agreed": sum(agreed), "flags_wrong": sum(wrong),
            "labels_caught": labels_ok,
            # with nothing judged yet, precision says nothing (not 0%)
            "precision": sum(agreed) / judged if judged else None,
            "recall": labels_ok / len(moments) if moments else None}
