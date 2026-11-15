from ml import typos
from ml.priority_detector import PriorityDetector


def test_misspelled_domain_words_are_fixed():
    assert typos.correct("Lisght is not working") == "Light is not working"
    assert typos.correct("Sparks from swich board") == "Sparks from switch board"


def test_real_words_and_plurals_are_left_alone():
    t = "Lift is stuck between floors with students inside"
    assert typos.correct(t) == t
    assert typos.correct("Room 1204 block 2") == "Room 1204 block 2"


def test_detector_understands_a_typo():
    r = PriorityDetector.load().predict("Tube lihgt is flickering in classroom")
    assert r.category.value == "electrical"