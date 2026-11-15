"""Score the model on the independent hand-written sets and write ml/reports/INDEPENDENT.md.

    python -m ml.independent_eval
"""
from pathlib import Path

from app.services.priority_engine import PriorityEngine
from ml import independent_set as I
from ml.evaluate import _score
from ml.priority_detector import PriorityDetector

NOTES = {
    "A": "tuning half: used for error analysis while widening the vocabulary (NOT blind)",
    "B": "originally sealed, but its topics overlapped the vocabulary I then added to training (NOT blind any more)",
    "C": "written after the final retrain and never used for tuning (the only blind estimate)",
}


def main() -> None:
    d, e = PriorityDetector.load(), PriorityEngine()
    lines = ["# Independent evaluation (hand-written and hand-labelled by the project author)", "",
             "Labels are one person's judgement, so priority (severity x impact) is partly subjective. **Set C is the honest number.**", "",
             "| Set | n | Model | Category acc | Priority acc | Within 1 level | Critical recall | Safety recall |", "|---|---|---|---|---|---|---|---|"]
    for name, rows in (("A", I.set_a()), ("B", I.set_b()), ("C", I.set_c())):
        for label, fn in (("ML", d.predict), ("Rules only", e.evaluate)):
            s = _score(rows, [fn(r["text"]) for r in rows])
            lines.append(f"| {name} | {s['n']} | {label} | {s['category_accuracy']*100:.0f}% | {s['priority_accuracy']*100:.0f}% | "
                         f"{s['priority_within_one_level']*100:.0f}% | {s['critical_recall']*100:.0f}% | {s['safety_recall']*100:.0f}% |")
    lines += ["", *[f"- **{k}**: {v}" for k, v in NOTES.items()], "",
              "Why not 90%+: the model was trained on synthetic template sentences. Real complaints use wording it has never seen.",
              "The way to reach 90% is to train on a few hundred REAL labelled complaints from the college (replace `ml/data/complaints.csv`, run `python -m ml.train`).",
              "Meanwhile the system is safe by design: uncertain predictions go to the admin AI-review queue, and safety keywords force high priority."]
    Path(__file__).parent.joinpath("reports", "INDEPENDENT.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
