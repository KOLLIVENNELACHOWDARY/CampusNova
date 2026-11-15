# Independent evaluation (hand-written and hand-labelled by the project author)

Labels are one person's judgement, so priority (severity x impact) is partly subjective. **Set C is the honest number.**

| Set | n | Model | Category acc | Priority acc | Within 1 level | Critical recall | Safety recall |
|---|---|---|---|---|---|---|---|
| A | 60 | ML | 83% | 57% | 95% | 68% | 79% |
| A | 60 | Rules only | 68% | 52% | 82% | 53% | 71% |
| B | 60 | ML | 85% | 60% | 83% | 70% | 73% |
| B | 60 | Rules only | 70% | 47% | 77% | 55% | 67% |
| C | 41 | ML | 73% | 61% | 88% | 67% | 70% |
| C | 41 | Rules only | 56% | 49% | 71% | 25% | 30% |

- **A**: tuning half: used for error analysis while widening the vocabulary (NOT blind)
- **B**: originally sealed, but its topics overlapped the vocabulary I then added to training (NOT blind any more)
- **C**: written after the final retrain and never used for tuning (the only blind estimate)

Why not 90%+: the model was trained on synthetic template sentences. Real complaints use wording it has never seen.
The way to reach 90% is to train on a few hundred REAL labelled complaints from the college (replace `ml/data/complaints.csv`, run `python -m ml.train`).
Meanwhile the system is safe by design: uncertain predictions go to the admin AI-review queue, and safety keywords force high priority.
