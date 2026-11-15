"""Shared constants and helpers for the ML package."""
import re
from pathlib import Path

from app.core.enums import Level
from app.services.priority_matrix import lookup_priority

ML_DIR = Path(__file__).resolve().parent
DATA_DIR = ML_DIR / "data"
REPORTS_DIR = ML_DIR / "reports"
DEFAULT_ARTIFACTS_DIR = ML_DIR / "artifacts"
DATASET_PATH = DATA_DIR / "complaints.csv"

LEVELS = ["low", "medium", "high"]
PRIORITY_ORDER = ["low", "medium", "high", "critical"]
CATEGORIES = ["electrical", "civil", "networking", "sanitation", "laboratory", "general"]

_URGENCY_RE = re.compile(r"\b(urgent(ly)?|immediate(ly)?|emergency|asap|right away)\b", re.IGNORECASE)


_NEGATED_URGENCY_RE = re.compile(
    r"\b(?:not|no|isn't|is not|never|without|hardly)\s+(?:a\s+|an\s+|very\s+|that\s+|so\s+|really\s+|too\s+)?"
    r"(?:urgent(?:ly)?|immediate(?:ly)?|emergency|asap|rush)\b"
    r"|\bno\s+need\b[^.!?,;]{0,40}?\b(?:urgent(?:ly)?|immediate(?:ly)?|asap)\b"
    r"|\bno\s+rush\b",
    re.IGNORECASE,
)
_PROBLEM_CUE_RE = re.compile(
    r"\b(not|no|nahi|broken|damage\w*|fail\w*|leak\w*|dirty|missing|slow|stuck|error|issue|problem|fault\w*|dead|bad|"
    r"smell\w*|block\w*|overflow\w*|crack\w*|spark\w*|smoke|fire|flood\w*|down|off|jam\w*|wobbl\w*|loose|burn\w*|"
    r"nois\w*|trip\w*|fell|hurt|bite|bitten|snake|collaps\w*|shock\w*|unable|cannot|can't|cant|doesn't|isn't|won't|"
    r"kharab|band|outage|cut|empty|unavailable|delay\w*|flicker\w*|peeling|rust\w*|torn|clogged|dripping|seepage|"
    r"overheat\w*|trapped|slipped|beeping|dusty|stain\w*|infest\w*|rats?|pest\w*|mosquito\w*)\b",
    re.IGNORECASE,
)


def has_urgency(text: str) -> bool:
    """Urgency wording is a separate factor: it bumps severity one level. Negations ("not urgent") don't count."""
    return _URGENCY_RE.search(_NEGATED_URGENCY_RE.sub(" ", text)) is not None


def has_problem_cue(text: str) -> bool:
    """False for thank-you notes, questions and requests that describe no problem at all."""
    return _PROBLEM_CUE_RE.search(text) is not None


def bump(level: str) -> str:
    return LEVELS[min(LEVELS.index(level) + 1, len(LEVELS) - 1)]


def final_priority(severity: str, impact: str, safety_risk: bool, urgent: bool) -> str:
    """Multi-factor priority = matrix(severity (+urgency bump), impact, safety)."""
    sev = bump(severity) if urgent else severity
    return lookup_priority(Level(sev), Level(impact), bool(safety_risk)).value
