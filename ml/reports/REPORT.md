# CampusNova: model evaluation report

Training rows: 1257, test rows: 536 (scikit-learn 1.9.1, trained in 32.3s).

> The dataset is synthetic (generated from hand-written phrasings). The test split uses issues and scope
> phrases that never appear in training, but scores will still be optimistic compared with real complaints.
> Re-train on real college complaints before trusting these numbers.
>
> Process notes (for transparency):
> - After the first run, the held-out scope phrases were redesigned to be paraphrases that share cue words with
>   training phrases, because the original ones (e.g. 'in the server room') could not be inferred from wording at all.
> - After error analysis, structural-hazard keywords (railing, beam, large crack, ...) were added to the safety rules and
>   the ML safety threshold was set to 0.35 (safety-first). The hold-out safety numbers are therefore not an independent
>   estimate; the hand-labelled set is the cleaner check, but it is small (36 rows).
> - Validation found that wide-area outages ('across the entire college') were rated too low: the rule engine had no
>   phrases for whole-college / all-labs scope, so about a quarter of the hold-out CRITICAL tickets were silently missed
>   (critical recall 64%). Those scope phrases were added to the impact rules and the models retrained: hold-out priority
>   accuracy rose from 60% to 77% and critical recall to 91%. The synthetic generator uses similar phrases, so part of this
>   gain is optimistic. The hand-labelled set contains none of them and did not change (78% priority accuracy), which
>   shows nothing else regressed, not that real-world accuracy improved by the same amount.

## Category classifier: model selection (grouped 5-fold CV on train)

| Model | Macro-F1 (mean +/- std) |
|---|---|
| tfidf_logreg | 0.683 +/- 0.083 |
| tfidf_linearsvc_calibrated **(selected)** | 0.687 +/- 0.059 |
| tfidf_complement_nb | 0.613 +/- 0.063 |

## Hold-out results per text model

| Model | Accuracy | Macro-F1 |
|---|---|---|
| category | 77.8% | 0.769 |
| severity | 73.7% | 0.738 |
| impact | 97.0% | 0.970 |
| safety_risk | 99.1% | 0.980 |

### Category confusion matrix (rows = true, columns = predicted)

| |electrical|civil|networking|sanitation|laboratory|general|
|---|---|---|---|---|---|---|
|**electrical**|64|2|2|16|16|26|
|**civil**|0|96|0|0|0|1|
|**networking**|1|1|56|4|7|12|
|**sanitation**|0|7|1|90|0|0|
|**laboratory**|0|9|1|2|65|3|
|**general**|0|1|0|2|5|46|

## Priority: multi-factor ML detector vs rule-based engine

### Synthetic hold-out (n=536)

| Metric | ML multi-factor | Rule-based |
|---|---|---|
| Category accuracy | 77.2% | 61.2% |
| Priority accuracy | 77.1% | 62.5% |
| Priority macro-F1 | 0.772 | 0.614 |
| Priority within one level | 96.6% | 93.1% |
| Critical recall | 90.3% | 69.0% |
| Critical precision | 78.5% | 100.0% |
| Safety-risk recall | 98.6% | 98.6% |
| Sent to manual review | 25.0% | 49.1% |

### Hand-labelled realistic set (n=36)

| Metric | ML multi-factor | Rule-based |
|---|---|---|
| Category accuracy | 97.2% | 83.3% |
| Priority accuracy | 83.3% | 52.8% |
| Priority macro-F1 | 0.826 | 0.498 |
| Priority within one level | 97.2% | 83.3% |
| Critical recall | 80.0% | 50.0% |
| Critical precision | 100.0% | 100.0% |
| Safety-risk recall | 100.0% | 83.3% |
| Sent to manual review | 8.3% | 38.9% |
