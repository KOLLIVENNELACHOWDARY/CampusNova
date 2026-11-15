"""Preliminary rule-based priority engine.

This is both the day-one implementation and the permanent fallback for the ML
classifier (Scikit-learn / spaCy), which will plug in alongside it later.

Pipeline for one complaint:
    1. Normalise text, strip phrases that cause false alarms ("fire extinguisher").
    2. Infer category from keywords when the reporter did not choose one.
    3. Score severity, impact and safety signals from weighted keyword rules.
    4. Look up the Priority Matrix -> priority + SLA hours.
    5. Flag low-confidence results for manual review.

Pure Python: no database or framework needed, so it is trivial to unit test.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from app.core.enums import Category, Level, Priority, RuleSignal
from app.services.priority_matrix import SLA_HOURS, MatrixKey, build_default_matrix


@dataclass(frozen=True)
class KeywordRule:
    keyword: str
    signal: RuleSignal
    weight: int = 1
    category: Optional[Category] = None  # None = applies to every category


# --- Default rule set -------------------------------------------------------

DEFAULT_RULES: list[KeywordRule] = [
    # Safety: any match forces CRITICAL
    *[
        KeywordRule(k, RuleSignal.SAFETY, 5)
        for k in (
            "short circuit", "spark", "electric shock", "electrocuted", "electrocution", "exposed wire",
            "live wire", "fire", "smoke", "burning smell", "gas leak", "ceiling collapse",
            "roof collapse", "falling", "collapse", "flood", "injury", "injured",
            # structural hazards
            "railing", "beam", "structural", "melting", "swollen battery", "swollen inverter", "bulging", "gets a shock", "gives shock", "giving shock", "received a shock", "gas cylinder", "cylinder is leaking", "mercury", "acid", "fumes", "stuck inside", "people are stuck", "manhole", "large crack", "deep crack", "wide crack", "tilting", "sinking",
        )
    ],
    # Severity
    KeywordRule("not working", RuleSignal.SEVERITY, 2),
    KeywordRule("not functioning", RuleSignal.SEVERITY, 2),
    KeywordRule("broken", RuleSignal.SEVERITY, 2),
    KeywordRule("damaged", RuleSignal.SEVERITY, 2),
    KeywordRule("leak", RuleSignal.SEVERITY, 2),
    KeywordRule("crack", RuleSignal.SEVERITY, 2),
    KeywordRule("no power", RuleSignal.SEVERITY, 3),
    KeywordRule("power cut", RuleSignal.SEVERITY, 3),
    KeywordRule("power outage", RuleSignal.SEVERITY, 3),
    KeywordRule("no water", RuleSignal.SEVERITY, 3),
    KeywordRule("no internet", RuleSignal.SEVERITY, 3),
    KeywordRule("down", RuleSignal.SEVERITY, 2),
    KeywordRule("dead", RuleSignal.SEVERITY, 2),
    KeywordRule("complete", RuleSignal.SEVERITY, 1),
    KeywordRule("blocked", RuleSignal.SEVERITY, 2),
    KeywordRule("overflow", RuleSignal.SEVERITY, 3),
    KeywordRule("completely", RuleSignal.SEVERITY, 1),
    KeywordRule("urgent", RuleSignal.SEVERITY, 2),
    KeywordRule("emergency", RuleSignal.SEVERITY, 3),
    KeywordRule("flickering", RuleSignal.SEVERITY, 1),
    KeywordRule("slow", RuleSignal.SEVERITY, 1),
    KeywordRule("dirty", RuleSignal.SEVERITY, 1),
    KeywordRule("stain", RuleSignal.SEVERITY, 1),
    KeywordRule("minor", RuleSignal.SEVERITY, -1),
    KeywordRule("cosmetic", RuleSignal.SEVERITY, -2),
    # Impact (how many people / how critical the place)
    *[KeywordRule(k, RuleSignal.IMPACT, 4) for k in (
        "entire college", "whole college", "entire campus", "whole campus", "entire institute", "whole institute",
        "all labs", "all the labs", "all hostels", "all the hostels", "all departments", "all the departments",
        "all blocks", "all the blocks", "every classroom", "every lab", "every block",
    )],
    KeywordRule("whole building", RuleSignal.IMPACT, 4),
    KeywordRule("entire block", RuleSignal.IMPACT, 4),
    KeywordRule("all classrooms", RuleSignal.IMPACT, 4),
    KeywordRule("all students", RuleSignal.IMPACT, 3),
    KeywordRule("campus", RuleSignal.IMPACT, 2),
    KeywordRule("hostel", RuleSignal.IMPACT, 2),
    KeywordRule("exam", RuleSignal.IMPACT, 3),
    KeywordRule("lab", RuleSignal.IMPACT, 2),
    KeywordRule("server room", RuleSignal.IMPACT, 4),
    KeywordRule("library", RuleSignal.IMPACT, 2),
    KeywordRule("auditorium", RuleSignal.IMPACT, 2),
    KeywordRule("seminar hall", RuleSignal.IMPACT, 2),
    KeywordRule("classroom", RuleSignal.IMPACT, 2),
    KeywordRule("canteen", RuleSignal.IMPACT, 2),
    KeywordRule("wifi", RuleSignal.IMPACT, 1),
    KeywordRule("wi-fi", RuleSignal.IMPACT, 1),
    KeywordRule("department", RuleSignal.IMPACT, 1),
    KeywordRule("multiple", RuleSignal.IMPACT, 2),
    KeywordRule("many", RuleSignal.IMPACT, 1),
    KeywordRule("single", RuleSignal.IMPACT, -1),
]

# Extra safety hazards (injury, animals, entrapment) and light Hinglish for Indian campuses.
DEFAULT_RULES += [
    *[KeywordRule(k, RuleSignal.SAFETY, 5) for k in (
        "fell down", "fell from", "slipped", "got hurt", "hurt", "bite", "bitten", "snake", "scorpion",
        "trapped", "stuck between floors", "stuck inside", "unconscious", "faint", "fainted",
    )],
    KeywordRule("nahi chal", RuleSignal.SEVERITY, 2),
    KeywordRule("nahi chalta", RuleSignal.SEVERITY, 2),
    KeywordRule("kaam nahi", RuleSignal.SEVERITY, 2),
    KeywordRule("kharab", RuleSignal.SEVERITY, 2),
    KeywordRule("band hai", RuleSignal.SEVERITY, 2),
    KeywordRule("poore", RuleSignal.IMPACT, 3),
    KeywordRule("sabhi", RuleSignal.IMPACT, 3),
    KeywordRule("saare", RuleSignal.IMPACT, 3),
]

# Water next to live electrical fittings is a shock/fire hazard even when no hazard word is spelled out.
WATER_WORDS = ("water", "leak", "leaking", "dripping", "seepage", "wet", "flood", "moisture")
ELECTRICAL_POINTS = ("socket", "switch board", "switchboard", "switch", "wiring", "wire", "plug", "electrical", "electric", "mcb", "circuit")

# Phrases that contain a safety word but are routine requests.
FALSE_ALARM_PHRASES = (
    "fire extinguisher", "fire drill", "fire exit", "fire safety audit", "fire alarm test",
)

CATEGORY_KEYWORDS: dict[Category, tuple[str, ...]] = {
    Category.ELECTRICAL: (
        "electric", "electricity", "power", "light", "bulb", "tube", "fan", "switch", "socket", "wire", "wiring",
        "circuit", "mcb", "ups", "generator", "ac", "air conditioner", "voltage", "transformer",
    ),
    Category.CIVIL: (
        "wall", "ceiling", "roof", "floor", "door", "window", "crack", "paint", "tile", "bench",
        "desk", "furniture", "staircase", "building", "plaster", "gate", "ramp",
    ),
    Category.NETWORKING: (
        "wifi", "wi-fi", "internet", "network", "router", "lan", "ethernet", "bandwidth",
        "switch port", "access point", "connectivity", "firewall", "server",
    ),
    Category.SANITATION: (
        "toilet", "washroom", "restroom", "drain", "sewage", "garbage", "dustbin", "cleaning",
        "cleanliness", "water supply", "tap", "plumbing", "pipe", "sanitary", "hygiene", "dirty",
    ),
    Category.LABORATORY: (
        "lab", "laboratory", "microscope", "oscilloscope", "projector", "computer", "pc",
        "equipment", "instrument", "reagent", "fume hood", "workstation", "apparatus",
    ),
}

CATEGORY_KEYWORDS[Category.CIVIL] = CATEGORY_KEYWORDS[Category.CIVIL] + ("seepage", "dampness")
CATEGORY_KEYWORDS[Category.ELECTRICAL] = CATEGORY_KEYWORDS[Category.ELECTRICAL] + ("bijli", "pankha")
CATEGORY_KEYWORDS[Category.SANITATION] = CATEGORY_KEYWORDS[Category.SANITATION] + ("paani", "nal", "bathroom")

# Category-specific baseline: some categories are riskier by nature.
CATEGORY_SEVERITY_BASELINE: dict[Category, int] = {
    Category.ELECTRICAL: 1,
    Category.CIVIL: 1,
}

SEVERITY_THRESHOLDS = (2, 5)  # score >=2 -> MEDIUM, >=5 -> HIGH
IMPACT_THRESHOLDS = (2, 4)  # score >=2 -> MEDIUM, >=4 -> HIGH
CATEGORY_REVIEW_CONFIDENCE = 0.5


@dataclass
class PriorityResult:
    category: Category
    category_confidence: float
    priority: Priority
    severity: Level
    impact: Level
    safety_risk: bool
    sla_hours: int
    needs_manual_review: bool
    matched_rules: list[str] = field(default_factory=list)
    source: str = "rule_based"
    confidence: float = 0.0  # overall confidence of the decision (0 for pure rule-based results)


def _contains(text: str, phrase: str) -> bool:
    """Whole-word match that tolerates common endings.

    'spark' hits 'sparks'/'sparking'; 'lab' does NOT hit 'label'/'table'; 'down' does
    NOT hit 'download'. Stems that need other endings are listed explicitly in the rules.
    """
    phrase = phrase.strip()
    return re.search(rf"(?<![a-z]){re.escape(phrase)}(?:s|es|d|ed|ing|al)?(?![a-z])", text) is not None


def _to_level(score: int, thresholds: tuple[int, int]) -> Level:
    medium, high = thresholds
    if score >= high:
        return Level.HIGH
    if score >= medium:
        return Level.MEDIUM
    return Level.LOW


class PriorityEngine:
    def __init__(
        self,
        rules: Optional[list[KeywordRule]] = None,
        matrix: Optional[dict[MatrixKey, Priority]] = None,
        sla_hours: Optional[dict[Priority, int]] = None,
    ):
        self.rules = rules if rules is not None else DEFAULT_RULES
        self.matrix = matrix if matrix is not None else build_default_matrix()
        self.sla_hours = sla_hours if sla_hours is not None else SLA_HOURS

    # -- text helpers -------------------------------------------------------

    @staticmethod
    def _normalise(title: str, description: str) -> str:
        text = f"{title} {description}".lower()
        for phrase in FALSE_ALARM_PHRASES:
            text = text.replace(phrase, " ")
        return re.sub(r"\s+", " ", text).strip() + " "

    # -- category -----------------------------------------------------------

    def infer_category(self, text: str) -> tuple[Category, float]:
        scores = {
            cat: sum(1 for kw in kws if _contains(text, kw)) for cat, kws in CATEGORY_KEYWORDS.items()
        }
        total = sum(scores.values())
        if total == 0:
            return Category.GENERAL, 0.0
        best = max(scores, key=lambda c: scores[c])
        # Confidence = share of matches won by the best category, damped when evidence is thin.
        confidence = (scores[best] / total) * min(1.0, 0.5 + 0.25 * scores[best])
        return best, round(confidence, 2)

    # -- scoring ------------------------------------------------------------

    def _score(self, text: str, category: Category) -> tuple[dict[RuleSignal, int], list[str]]:
        totals = {sig: 0 for sig in RuleSignal}
        matched: list[str] = []
        for rule in self.rules:
            if rule.category is not None and rule.category != category:
                continue
            if _contains(text, rule.keyword):
                totals[rule.signal] += rule.weight
                matched.append(f"{rule.signal.value}:{rule.keyword}({rule.weight:+d})")
        if any(_contains(text, w) for w in WATER_WORDS) and any(_contains(text, e) for e in ELECTRICAL_POINTS):
            totals[RuleSignal.SAFETY] += 5
            matched.append("safety:water+electrical(+5)")
        return totals, matched

    def _strip_negated_safety(self, text: str) -> str:
        """'no fire or smoke', 'without sparks', 'not a fire' must not count as safety hazards."""
        words = sorted({r.keyword for r in self.rules if r.signal == RuleSignal.SAFETY}, key=len, reverse=True)
        if not words:
            return text
        alt = "|".join(re.escape(w) for w in words)
        pattern = (
            rf"(?<![a-z])(?:no|not|without|never|zero|nothing like|no sign of|no signs of)\s+"
            rf"(?:a\s+|an\s+|any\s+|the\s+)?(?:{alt})(?:s|es|d|ed|ing)?"
            rf"(?:\s*(?:,|or|nor|and)\s*(?:a\s+|an\s+|any\s+|the\s+)?(?:{alt})(?:s|es|d|ed|ing)?)*"
        )
        return re.sub(pattern, " ", text)

    # -- public API ---------------------------------------------------------

    def signal_scores(self, text: str) -> tuple[dict[RuleSignal, int], dict[Category, int]]:
        """Raw rule signals for ML feature engineering: (severity/impact/safety scores, category keyword hits)."""
        norm = self._strip_negated_safety(self._normalise(text, ""))
        totals, _ = self._score(norm, Category.GENERAL)
        cat_hits = {cat: sum(1 for kw in kws if _contains(norm, kw)) for cat, kws in CATEGORY_KEYWORDS.items()}
        return totals, cat_hits

    def evaluate(
        self, title: str, description: str = "", category: Optional[Category] = None
    ) -> PriorityResult:
        text = self._strip_negated_safety(self._normalise(title, description))

        if category is None:
            category, cat_conf = self.infer_category(text)
        else:
            cat_conf = 1.0  # reporter chose it explicitly

        totals, matched = self._score(text, category)
        severity_score = totals[RuleSignal.SEVERITY] + CATEGORY_SEVERITY_BASELINE.get(category, 0)
        severity = _to_level(severity_score, SEVERITY_THRESHOLDS)
        impact = _to_level(totals[RuleSignal.IMPACT], IMPACT_THRESHOLDS)
        safety_risk = totals[RuleSignal.SAFETY] > 0

        priority = self.matrix.get((severity, impact, safety_risk)) or Priority.MEDIUM

        # Nothing matched at all -> we are guessing; a human should look.
        no_signal = not matched
        needs_review = cat_conf < CATEGORY_REVIEW_CONFIDENCE or no_signal

        return PriorityResult(
            category=category,
            category_confidence=cat_conf,
            priority=priority,
            severity=severity,
            impact=impact,
            safety_risk=safety_risk,
            sla_hours=self.sla_hours[priority],
            needs_manual_review=needs_review,
            matched_rules=matched,
        )
