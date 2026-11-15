"""Typo tolerance: fix misspelled words ("lisght" -> "light") before the AI reads a complaint.

Only words that are NOT already known are touched, and only when a known word is a very close match
(difflib ratio >= 0.8, same first letter). The vocabulary is built from the training data and saved to
ml/artifacts/vocab.json (so it ships with the app). Rebuild with:  python -m ml.typos
"""
import csv
import json
import re
from difflib import get_close_matches
from functools import lru_cache
from pathlib import Path

ART = Path(__file__).parent / "artifacts" / "vocab.json"
DATA = Path(__file__).parent / "data" / "complaints.csv"
WORD = re.compile(r"[A-Za-z]{4,}")
# very common English words that must never be "corrected" into domain words
COMMON = set("""this that with have from they them their there these those when where which while what will would could should
about after again being below between both cannot does doing done down during each either else even ever every
for into just kindly like made make many more most much must near need only other over please really same since some such than then
still students student teacher teachers class classroom room hostel block floor lab library please urgent""".split())


def build() -> int:
    from app.services.priority_engine import PriorityEngine
    words: dict[str, int] = {}
    with open(DATA, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for w in WORD.findall(row["text"].lower()):
                words[w] = words.get(w, 0) + 1
    vocab = {w for w, n in words.items() if n >= 2}
    eng = PriorityEngine()
    for attr in dir(eng):
        v = getattr(eng, attr, None)
        if isinstance(v, (set, list, tuple, frozenset)):
            for item in v:
                if isinstance(item, str):
                    vocab.update(w.lower() for w in WORD.findall(item))
    ART.write_text(json.dumps(sorted(vocab)))
    return len(vocab)


@lru_cache(maxsize=1)
def _vocab() -> tuple[frozenset, dict]:
    if not ART.exists():
        return frozenset(), {}
    words = frozenset(json.loads(ART.read_text()))
    by_first: dict[str, list] = {}
    for w in words:
        by_first.setdefault(w[0], []).append(w)
    return words, by_first


def correct(text: str) -> str:
    words, by_first = _vocab()
    if not words or not text:
        return text

    def fix(m: re.Match) -> str:
        w = m.group(0)
        lw = w.lower()
        if lw in words or lw in COMMON:
            return w
        hit = get_close_matches(lw, by_first.get(lw[0], []), n=1, cutoff=0.8)
        if not hit:
            return w
        out = hit[0]
        if out.startswith(lw) or lw.startswith(out):  # plural/suffix variants are real words, not typos
            return w
        return out.capitalize() if w[0].isupper() else out

    return WORD.sub(fix, text)


if __name__ == "__main__":
    print("vocabulary words:", build())