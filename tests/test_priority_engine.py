import pytest

from app.core.enums import Category, Level, Priority
from app.services.priority_engine import PriorityEngine
from app.services.priority_matrix import SLA_HOURS, build_default_matrix, lookup_priority

engine = PriorityEngine()


def test_safety_risk_is_always_critical():
    r = engine.evaluate("Sparking from switch board", "Exposed wire near the lab door")
    assert r.safety_risk is True
    assert r.priority == Priority.CRITICAL
    assert r.category == Category.ELECTRICAL
    assert r.sla_hours == SLA_HOURS[Priority.CRITICAL]


def test_fire_extinguisher_request_is_not_a_safety_alarm():
    r = engine.evaluate("Fire extinguisher refill needed", "Routine refill for the corridor")
    assert r.safety_risk is False
    assert r.priority != Priority.CRITICAL


def test_wide_impact_outage_is_high_or_above():
    r = engine.evaluate("No internet in whole building", "Wifi down, exam tomorrow", Category.NETWORKING)
    assert r.priority in (Priority.HIGH, Priority.CRITICAL)
    assert r.impact == Level.HIGH


def test_minor_cosmetic_issue_is_low():
    r = engine.evaluate("Minor cosmetic stain on notice board", "single spot", Category.GENERAL)
    assert r.priority == Priority.LOW


def test_category_inferred_when_missing():
    r = engine.evaluate("Toilet tap leaking", "Washroom on second floor has a leak")
    assert r.category == Category.SANITATION
    assert r.category_confidence > 0


def test_explicit_category_gets_full_confidence():
    r = engine.evaluate("Projector not working", category=Category.LABORATORY)
    assert r.category == Category.LABORATORY
    assert r.category_confidence == 1.0


def test_no_signal_goes_to_manual_review():
    r = engine.evaluate("Hello", "Please check")
    assert r.category == Category.GENERAL
    assert r.needs_manual_review is True
    assert r.matched_rules == []


def test_word_boundary_matching():
    # "lab" must not match inside "table"
    r = engine.evaluate("Table wobbling", "", Category.CIVIL)
    assert not any("lab" in m for m in r.matched_rules)


@pytest.mark.parametrize(
    "sev,imp,safe,expected",
    [
        (Level.LOW, Level.LOW, False, Priority.LOW),
        (Level.MEDIUM, Level.MEDIUM, False, Priority.MEDIUM),
        (Level.HIGH, Level.MEDIUM, False, Priority.HIGH),
        (Level.HIGH, Level.HIGH, False, Priority.CRITICAL),
        (Level.LOW, Level.LOW, True, Priority.CRITICAL),
    ],
)
def test_matrix_lookup(sev, imp, safe, expected):
    assert lookup_priority(sev, imp, safe) == expected


def test_default_matrix_covers_every_combination():
    assert len(build_default_matrix()) == 3 * 3 * 2


@pytest.mark.parametrize(
    "title,bad_keyword",
    [
        ("Download speed is slow", "down"),
        ("Label peeling off the door", "lab"),
        ("Upstairs corridor dusty", "ups"),
    ],
)
def test_no_partial_word_false_positives(title, bad_keyword):
    r = engine.evaluate(title, "")
    assert not any(f":{bad_keyword}(" in m for m in r.matched_rules)


def test_word_endings_still_match():
    r = engine.evaluate("Panel sparks and smoke seen", "")
    assert r.safety_risk is True
    assert engine.evaluate("Ceiling collapsed in room", "").priority == Priority.CRITICAL
    assert engine.evaluate("Electricity cut in lab", "").category == Category.ELECTRICAL
