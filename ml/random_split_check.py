"""Second accuracy figure: a standard random 80/20 split (3 seeds).

This is the number most student projects quote, but it is OPTIMISTIC here: the dataset is synthetic, so the same wording
families land in both train and test. The strict figure in REPORT.md (whole issue types and scope phrases held out) is the
more honest estimate of how the model copes with new wording. Quote both, labelled.

Run:  python -m ml.random_split_check      (writes ml/reports/RANDOM_SPLIT.md)
"""
import csv
import random
import tempfile
from pathlib import Path

from ml.evaluate import DATASET_PATH, read_csv
from ml.priority_detector import PriorityDetector
from ml.train import train

SEEDS = (1, 2, 3)


def run() -> list[dict]:
    rows = read_csv(DATASET_PATH)
    results = []
    for seed in SEEDS:
        rng = random.Random(seed)
        split = [dict(r, split="test" if rng.random() < 0.2 else "train") for r in rows]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "complaints.csv"
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(split[0]))
                writer.writeheader()
                writer.writerows(split)
            train(out_dir=Path(tmp) / "artifacts", data_path=path, verbose=False)
            detector = PriorityDetector.load(Path(tmp) / "artifacts")
            test = [r for r in split if r["split"] == "test"]
            preds = [detector.predict(r["text"]) for r in test]
        results.append({
            "seed": seed, "n": len(test),
            "category": sum(p.category.value == r["category"] for p, r in zip(preds, test)) / len(test),
            "priority": sum(p.priority.value == r["priority"] for p, r in zip(preds, test)) / len(test),
        })
    return results


def main() -> None:
    results = run()
    lines = ["# Random 80/20 split accuracy (optimistic)", "",
             "> Synthetic data: the same wording families appear in train and test, so these numbers are inflated.",
             "> The strict hold-out in REPORT.md (unseen issue types and scope phrases) is the honest estimate for new wording.", "",
             "| Seed | Test rows | Category accuracy | Priority accuracy |", "|---|---|---|---|"]
    lines += [f"| {r['seed']} | {r['n']} | {r['category']:.1%} | {r['priority']:.1%} |" for r in results]
    mean = lambda k: sum(r[k] for r in results) / len(results)
    lines.append(f"| **mean** | | **{mean('category'):.1%}** | **{mean('priority'):.1%}** |")
    out = Path(__file__).parent / "reports" / "RANDOM_SPLIT.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
