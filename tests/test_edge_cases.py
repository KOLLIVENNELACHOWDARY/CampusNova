import pytest

from app.core.enums import Category, Priority
from ml.common import has_urgency
from ml.validation import validate_complaint

ORDER = ["low", "medium", "high", "critical"]


# ---------- input validation ----------
@pytest.mark.parametrize(
    "title,desc",
    [
        ("", ""), ("   ", "  "), ("help", ""), ("12345", ""), ("!!!! ????", ""), ("aaaaaaaaaaaa", ""),
        ("x" * 2001, ""), ("fan", ""),
    ],
)
def test_validation_rejects_bad_input(title, desc):
    assert validate_complaint(title, desc) is not None


@pytest.mark.parametrize(
    "title,desc",
    [
        ("Fan broken", ""), ("Wifi down", "in the CSE block"), ("Tube light flickering", ""),
        ("नल से पानी टपक रहा है", ""), ("wifi nahi chal raha", ""),
    ],
)
def test_validation_accepts_real_complaints(title, desc):
    assert validate_complaint(title, desc) is None


# ---------- negation ----------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("needs urgent attention", True), ("Please fix immediately", True), ("This is an emergency", True),
        ("This is not urgent", False), ("no need to fix it immediately", False), ("not an emergency", False),
        ("no rush, whenever possible", False), ("tube light flickering", False),
    ],
)
def test_urgency_and_negation(text, expected):
    assert has_urgency(text) is expected


def test_negated_safety_words_do_not_escalate(detector):
    r = detector.predict("There is no fire or smoke, just a dirty floor")
    assert not r.safety_risk and r.priority != Priority.CRITICAL
    assert not detector.predict("No sparks, only a loose switch cover").safety_risk


# ---------- hazards that must always be critical ----------
@pytest.mark.parametrize(
    "text",
    [
        "Sparks coming from the socket in room 12",
        "Exposed live wire hanging near the door",
        "Water dripping from the AC onto the electrical socket",
        "Student fell down the stairs because the step is broken",
        "Snake seen near the hostel entrance",
        "Gas leak smell in the chemistry lab",
        "Ceiling plaster is falling down in the library",
        "Lift is stuck between floors with students inside",
        "SPARKS FROM SWITCH BOARD!!!",
    ],
)
def test_hazards_are_critical(detector, text):
    r = detector.predict(text)
    assert r.safety_risk and r.priority == Priority.CRITICAL and r.sla_hours == 4


# ---------- things that are not safety hazards ----------
@pytest.mark.parametrize(
    "text",
    ["Fire extinguisher refill needed in corridor", "Fire drill scheduled tomorrow, please arrange chairs", "Download speed is slow"],
)
def test_routine_text_is_not_critical(detector, text):
    assert detector.predict(text).priority != Priority.CRITICAL


# ---------- unclear input goes to a human, never silently low ----------
@pytest.mark.parametrize("text", ["asdfgh qwerty", "12345", "hello", "a", "help"])
def test_unrecognisable_input_goes_to_manual_review(detector, text):
    r = detector.predict(text)
    assert r.needs_manual_review and r.priority == Priority.MEDIUM and r.source == "rule_based_fallback"


@pytest.mark.parametrize(
    "text",
    ["thank you for fixing the wifi earlier", "I want to know the exam schedule", "Can I get a new projector for the seminar hall?"],
)
def test_non_complaints_are_flagged(detector, text):
    assert detector.predict(text).needs_manual_review


def test_empty_text_raises(detector):
    with pytest.raises(ValueError):
        detector.predict("   ")


# ---------- robustness ----------
def test_urgent_wording_never_lowers_priority(detector):
    base = detector.predict("Ceiling fan is not working in the staff room")
    urgent = detector.predict("Ceiling fan is not working in the staff room, needs urgent attention")
    assert ORDER.index(urgent.priority.value) >= ORDER.index(base.priority.value)


def test_not_urgent_does_not_bump(detector):
    r = detector.predict("This is not urgent but the tube light is flickering in my cabin")
    assert not any(m.startswith("urgency:") for m in r.matched_rules)


def test_case_punctuation_and_typos_are_tolerated(detector):
    a = detector.predict("wifi is down in the entire cse block")
    b = detector.predict("WIFI IS DOWN IN THE ENTIRE CSE BLOCK!!!")
    c = detector.predict("wifi is dwon in the entrie cse blcok")
    assert a.category == b.category == Category.NETWORKING
    assert c.category == Category.NETWORKING


def test_hinglish_is_understood(detector):
    r = detector.predict("wifi nahi chal raha hai poore block me")
    assert r.category == Category.NETWORKING and r.priority != Priority.LOW


def test_long_text_and_unicode_do_not_crash(detector):
    long_text = "The tube light in the corridor is not working. " * 40
    assert detector.predict(long_text[:1900]).category == Category.ELECTRICAL
    detector.predict("Lights off 💡😡 in room 5")
    detector.predict("नल से पानी टपक रहा है")


def test_multi_issue_takes_the_worst(detector):
    r = detector.predict("Fan is not working and there are sparks from the wire")
    assert r.priority == Priority.CRITICAL


def test_explicit_category_is_respected(detector):
    assert detector.predict("Something is broken in the building", category=Category.CIVIL).category == Category.CIVIL


def test_result_always_has_sla_and_reasons(detector):
    for text in ["Tube light flickering", "asdfgh qwerty", "Sparks from socket"]:
        r = detector.predict(text)
        assert r.sla_hours in (4, 24, 72, 168) and r.matched_rules
