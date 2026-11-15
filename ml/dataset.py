"""Synthetic labelled complaint dataset generator.

No real complaint history exists yet, so this builds a starter dataset from
hand-written issue phrasings x scope phrases x urgency wording. Every row carries:

    category, severity (base), impact, safety_risk, urgent, priority (ground truth)

Leakage control: the train/test split is by *issue* and by *scope phrase*. A test
row uses an issue and a scope phrase that never appear in training, so the
reported scores measure generalisation to new wording, not memorisation.

Replace or extend data/complaints.csv with real college complaints as soon as
they are available, then re-run `python -m ml.train`.
"""
import csv
import random
from collections import defaultdict

from ml.common import DATASET_PATH, LEVELS, final_priority, has_urgency

# (category, base severity, safety_risk, [phrasings])
ISSUES = [
    # ---------------- electrical ----------------
    ("electrical", "high", True, ["sparking from the switch board", "sparks coming out of the socket", "short circuit with a burning smell from the panel"]),
    ("electrical", "high", True, ["exposed live wire hanging near the door", "open wiring with bare wires visible"]),
    ("electrical", "high", True, ["got an electric shock while touching the switch", "student received electric shock from the metal rod"]),
    ("electrical", "high", False, ["no power supply", "complete power cut since morning", "power outage and nothing is working"]),
    ("electrical", "medium", False, ["tube light not working", "ceiling fan not working", "light is not functioning"]),
    ("electrical", "low", False, ["bulb flickering", "fan making a slight noise", "tube light flickering at times"]),
    ("electrical", "medium", False, ["air conditioner not cooling", "AC not working properly"]),
    ("electrical", "medium", False, ["UPS beeping continuously and not working", "UPS battery is dead"]),
    ("electrical", "medium", False, ["socket is loose and not working", "switch board is broken"]),
    ("electrical", "high", False, ["generator failed to start during the power cut", "MCB keeps tripping again and again"]),
    ("electrical", "medium", False, ["power point for the projector is not working", "extension board is damaged"]),
    ("electrical", "low", False, ["switch cover is missing", "minor flicker in the corridor light"]),
    ("electrical", "medium", False, ["street light not working near the parking area", "corridor lights are off"]),
    ("electrical", "medium", False, ["voltage fluctuation damaging devices", "transformer making buzzing sound and power is unstable"]),
    # ---------------- civil ----------------
    ("civil", "high", True, ["ceiling plaster is falling down", "roof collapsed partially", "large cracks on the ceiling and it may collapse", "wall is about to collapse"]),
    ("civil", "high", True, ["staircase railing is broken and dangerous", "handrail is loose and students may fall"]),
    ("civil", "medium", False, ["cracks on the wall", "crack in the floor tiles", "window glass is broken"]),
    ("civil", "medium", False, ["door lock is broken", "door hinge damaged and door is not closing", "gate is damaged"]),
    ("civil", "low", False, ["paint is peeling off the wall", "wall needs repainting", "bench leg is wobbly"]),
    ("civil", "medium", False, ["benches are broken", "desk is damaged", "chair is broken"]),
    ("civil", "low", False, ["minor scratches on the door", "cosmetic damage to the notice board frame"]),
    ("civil", "medium", False, ["water seepage on the ceiling", "roof is leaking during rain"]),
    ("civil", "medium", False, ["floor tiles are broken and uneven", "broken floor causing students to trip"]),
    ("civil", "low", False, ["ramp needs repair", "loose floor tile"]),
    ("civil", "medium", False, ["window is not closing properly", "window latch is broken"]),
    ("civil", "high", True, ["balcony railing is missing", "large crack in the beam"]),
    ("civil", "low", False, ["whiteboard fixing is loose", "curtain rod needs refixing"]),
    # ---------------- networking ----------------
    ("networking", "high", False, ["no internet connectivity", "wifi is completely down", "network outage since morning"]),
    ("networking", "medium", False, ["wifi is very slow", "internet speed is very slow", "frequent wifi disconnections"]),
    ("networking", "medium", False, ["wifi is not connecting", "unable to connect to the college wifi"]),
    ("networking", "medium", False, ["LAN port is not working", "ethernet cable is damaged", "network switch port is dead"]),
    ("networking", "high", False, ["router is not working and systems are offline", "server is down", "firewall is blocking all websites"]),
    ("networking", "low", False, ["wifi password needs to be reset", "a new access point is needed for better coverage", "wifi signal is weak in the corner"]),
    ("networking", "medium", False, ["access point is not working", "wifi router is blinking red"]),
    ("networking", "low", False, ["one website is loading slowly", "slow loading of a single page"]),
    ("networking", "medium", False, ["student portal is not opening on the campus network", "VPN is not connecting"]),
    ("networking", "high", False, ["internet is down during the online exam", "network failure while submitting assignments"]),
    ("networking", "low", False, ["IP address conflict on one system", "network printer is not detected"]),
    ("networking", "medium", False, ["CCTV network is offline", "biometric attendance device is not connecting to the network"]),
    # ---------------- sanitation ----------------
    ("sanitation", "high", False, ["no water supply in the washroom", "water tank is empty and there is no water"]),
    ("sanitation", "high", False, ["drain is overflowing with sewage", "sewage overflow with bad smell"]),
    ("sanitation", "medium", False, ["toilet is blocked", "washroom is blocked and unusable", "flush is not working"]),
    ("sanitation", "medium", False, ["tap is leaking continuously", "pipe leak in the restroom"]),
    ("sanitation", "medium", False, ["garbage has not been collected for days", "dustbins are overflowing"]),
    ("sanitation", "low", False, ["washroom is dirty", "classroom is not cleaned", "floor needs mopping", "dust on the benches"]),
    ("sanitation", "low", False, ["soap dispenser is empty", "tissue paper is not available", "dustbin is missing"]),
    ("sanitation", "medium", False, ["bad smell from the drainage", "mosquito breeding due to stagnant water"]),
    ("sanitation", "medium", False, ["water cooler is not working", "drinking water is not available"]),
    ("sanitation", "high", True, ["burst pipe is flooding the corridor", "slippery flooded floor with risk of injury"]),
    ("sanitation", "medium", False, ["rats seen near the kitchen", "pest problem near the mess"]),
    # ---------------- laboratory ----------------
    ("laboratory", "medium", False, ["computer is not starting", "system is not booting"]),
    ("laboratory", "medium", False, ["projector is not working", "microscope lens is damaged"]),
    ("laboratory", "high", True, ["gas leak smell in the chemistry lab", "chemical spill with strong fumes", "fume hood is not working while experiments are running"]),
    ("laboratory", "high", True, ["smoke coming from the oscilloscope", "fire in the lab equipment"]),
    ("laboratory", "medium", False, ["oscilloscope is not working", "lab instruments are not calibrated", "multimeter is broken"]),
    ("laboratory", "low", False, ["lab stool is broken", "a few lab manuals are missing"]),
    ("laboratory", "low", False, ["mouse and keyboard not working on one workstation", "one PC is running slow"]),
    ("laboratory", "medium", False, ["lab software license has expired", "required software is not installed on the lab systems"]),
    ("laboratory", "high", False, ["all lab computers are not working", "lab equipment failed during the practical exam"]),
    ("laboratory", "medium", False, ["reagent cabinet lock is broken", "glassware shortage for experiments"]),
    ("laboratory", "low", False, ["lab needs cleaning", "extra extension boxes are needed in the lab"]),
    ("laboratory", "medium", False, ["3D printer is not working", "workstation monitor is damaged"]),
    ("laboratory", "high", True, ["electric shock from the lab equipment", "exposed wires on the lab bench"]),
    # ---------------- general ----------------
    ("general", "low", False, ["need more notice boards", "suggestion to add a water bottle refilling station"]),
    ("general", "low", False, ["request to change the classroom allocation", "parking space is insufficient"]),
    ("general", "medium", False, ["security guard is not available at the gate", "lost items are not being returned"]),
    ("general", "low", False, ["library books are not arranged", "request for more seating in the reading area"]),
    ("general", "medium", False, ["noise from construction is disturbing classes", "stray dogs are roaming around"]),
    ("general", "high", True, ["stray dog bite incident", "fire alarm is not working", "emergency exit is blocked"]),
    ("general", "low", False, ["signboard is missing near the block", "a directions board is needed"]),
    ("general", "medium", False, ["lift is not working", "elevator is out of service"]),
    ("general", "low", False, ["feedback about the canteen menu", "request for a cycle stand"]),
    ("general", "medium", False, ["college bus is not arriving on time", "transport is delayed every day"]),
    ("general", "medium", False, ["ID card printing machine is not working", "photocopier is not working in the office"]),
    ("general", "low", False, ["request to extend the library hours", "request for more charging points in the common area"]),
    # ---------------- extra vocabulary (v2): informal / varied wording ----------------
    ("electrical", "high", True, ["gets a shock when touching the plug point", "mild electric current felt on the metal body of the geyser", "earthing problem, the machine body gives a tingling shock"]),
    ("electrical", "high", True, ["burning smell from the distribution board", "smoke is coming from the battery bank", "swollen inverter battery near the racks", "cable is melting near the main panel"]),
    ("electrical", "medium", False, ["fan is rotating very slowly and making noise", "fan blades are loose and wobbling", "regulator is not working"]),
    ("electrical", "high", False, ["current has gone and there is no supply", "transformer tripped and all lights are off", "power failure and the backup did not start"]),
    ("electrical", "low", False, ["tubes are fused and need replacement", "bulb is fused in the passage", "lamp holder is loose"]),
    ("electrical", "medium", False, ["projector will not switch on", "smart board has no display", "display screen is blank"]),
    ("electrical", "high", True, ["ceiling fan came off its mount and fell", "light fitting is hanging by its wire"]),
    ("civil", "high", True, ["crack in the wall is growing day by day", "a big crack has opened up in the old building", "ceiling is about to come down", "concrete pieces are dropping from the slab"]),
    ("civil", "high", True, ["manhole or drain cover is missing and someone may fall", "compound wall has fallen", "railing is rusted and shaking"]),
    ("civil", "low", False, ["blackboard needs a fresh coat of paint", "wall needs whitewashing", "door handle has come off", "door will not shut properly"]),
    ("civil", "medium", False, ["potholes on the road near the gate", "water logging in the parking area after rain", "roof is dripping in the corridor", "glass panes are cracked"]),
    ("civil", "low", False, ["bench legs are broken", "desk top is loose", "cupboard door is hanging"]),
    ("networking", "high", False, ["internet is not working for anyone", "portal is not opening for any student during the exam", "college website is not accessible", "mail server is not working"]),
    ("networking", "medium", False, ["router keeps hanging and restarting", "net is very slow and keeps disconnecting", "system is not getting an IP address", "ethernet port gives no connection", "wifi dongle is not connecting"]),
    ("networking", "low", False, ["wifi password was changed and nobody was informed", "need a wifi access point installed in this room"]),
    ("networking", "high", False, ["switch failure has cut off the entire lab from the network", "fiber cable has been cut and the block has no net"]),
    ("sanitation", "high", False, ["no water is coming in the taps since morning", "water is not available in the hostel", "tap water is dirty and yellow", "drinking water is contaminated"]),
    ("sanitation", "high", False, ["sewage is flowing on the road", "pipe has burst and water is everywhere", "drain is choked and overflowing onto the corridor"]),
    ("sanitation", "medium", False, ["water purifier is not working", "RO plant has stopped", "urinals are choked", "wash basin is blocked", "tank is overflowing and wasting water"]),
    ("sanitation", "medium", False, ["garbage is piling up and not lifted for days", "dustbin is full and stinking", "cockroaches and insects in the kitchen", "mosquitoes and stagnant water behind the building"]),
    ("sanitation", "low", False, ["washroom has not been cleaned today", "no handwash in the restroom", "floor is wet and dirty"]),
    ("laboratory", "high", True, ["gas cylinder is leaking in the lab", "mercury has spilled on the floor", "acid bottle broke and fumes are spreading", "heater will not switch off and is overheating"]),
    ("laboratory", "medium", False, ["lab systems are slow and hanging", "computers keep freezing during practicals", "the printer in the mechanical lab is jammed", "centrifuge is making a loud noise", "weighing balance shows wrong readings", "pH meter is not calibrated", "software license is not valid"]),
    ("laboratory", "low", False, ["lab coat hooks are missing", "workbench drawers are broken", "microscope needs cleaning"]),
    ("general", "high", True, ["monkeys or snakes seen near the building and students are scared", "people are stuck inside the lift", "fire alarm panel is showing a fault"]),
    ("general", "medium", False, ["lift has stopped working", "cctv camera is not recording", "public address system has no sound", "microphone in the auditorium is not working", "bus did not arrive and students are late"]),
    ("general", "low", False, ["notice board glass is broken", "chairs in the auditorium are dirty", "student lockers need keys", "need more parking space", "food quality complaint in the mess"]),
]

# Scope phrases decide the impact level. The TEST_SCOPES are held out of training: they are paraphrases
# that share cue words ("single", "few", "entire", "all") with training phrases but are worded differently.
SCOPES = {
    "low": ["in room 204", "for one student", "at my desk", "in cabin 3", "near the back bench", "in the staff room", "in one cubicle", "in my seat area", "only on one bench", "for a single student", "in one room"],
    "medium": ["in the classroom", "in the CSE department", "on the second floor corridor", "in the seminar hall", "in the library reading area", "in the canteen", "in hostel wing A", "in a few rooms", "in two classrooms", "in the first floor corridor", "in a few labs"],
    "high": ["in the whole building", "across the entire block", "in all classrooms", "in the server room", "in the exam hall during exams", "affecting all students", "across the campus", "in the main auditorium during the event", "in many labs", "in the entire hostel", "across the entire college", "in all the labs", "affecting the whole college"],
}
TEST_SCOPES = {
    "low": {"for a single student", "in one room"},
    "medium": {"in two classrooms", "in the first floor corridor"},
    "high": {"across the entire college", "in all the labs", "affecting the whole college"},
}


def _split_scopes():
    out = {"train": {}, "test": {}}
    for lvl, phrases in SCOPES.items():
        out["train"][lvl] = [p for p in phrases if p not in TEST_SCOPES[lvl]]
        out["test"][lvl] = [p for p in phrases if p in TEST_SCOPES[lvl]]
    return out


PREFIXES = ["", "", "", "Sir, ", "Hello, ", "Complaint: ", "Kindly note that "]
URGENT_SUFFIX = ["Needs urgent attention.", "Please fix this immediately.", "This is an emergency."]
NEUTRAL_SUFFIX = ["Please look into it.", "Kindly resolve this.", "It has been like this for two days.", "Reported earlier also."]
TEMPLATES = ["{i} {s}.", "{S}, {i}.", "Reporting that {i} {s}.", "{p}{i} {s}."]


def _typo(text: str, rng: random.Random) -> str:
    words = text.split(" ")
    idx = [k for k, w in enumerate(words) if len(w) > 5 and w.isalpha()]
    if not idx:
        return text
    k = rng.choice(idx)
    w = words[k]
    j = rng.randrange(1, len(w) - 2)
    words[k] = w[:j] + w[j + 1] + w[j] + w[j + 2:]
    return " ".join(words)


def _compose(issue: str, scope: str, rng: random.Random) -> str:
    tpl = rng.choice(TEMPLATES)
    text = tpl.format(i=issue, s=scope, S=scope[0].upper() + scope[1:], p=rng.choice(PREFIXES))
    r = rng.random()
    if r < 0.20:
        text += " " + rng.choice(URGENT_SUFFIX)
    elif r < 0.70:
        text += " " + rng.choice(NEUTRAL_SUFFIX)
    text = text[0].upper() + text[1:]
    if rng.random() < 0.15:
        text = text.lower()
    if rng.random() < 0.12:
        text = _typo(text, rng)
    return text


def generate(seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    scopes = _split_scopes()
    seen_in_cat = defaultdict(int)
    rows, seen_text = [], set()
    for issue_id, (cat, severity, safety, variants) in enumerate(ISSUES):
        split = "test" if seen_in_cat[cat] % 4 == 3 else "train"
        seen_in_cat[cat] += 1
        reps = 3 if split == "test" else 2
        for variant in variants:
            for lvl in LEVELS:
                for _ in range(reps):
                    scope = rng.choice(scopes[split][lvl])
                    text = _compose(variant, scope, rng)
                    if text in seen_text:
                        continue
                    seen_text.add(text)
                    urgent = has_urgency(text)
                    rows.append(
                        {
                            "text": text,
                            "category": cat,
                            "severity": severity,
                            "impact": lvl,
                            "safety_risk": int(safety),
                            "urgent": int(urgent),
                            "priority": final_priority(severity, lvl, safety, urgent),
                            "issue_id": issue_id,
                            "split": split,
                        }
                    )
    rng.shuffle(rows)
    return rows


FIELDS = ["text", "category", "severity", "impact", "safety_risk", "urgent", "priority", "issue_id", "split"]


def write_csv(rows: list[dict], path=DATASET_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def read_csv(path=DATASET_PATH) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["safety_risk"] = int(r["safety_risk"])
        r["urgent"] = int(r["urgent"])
        r["issue_id"] = int(r["issue_id"])
    return rows


if __name__ == "__main__":
    data = generate()
    write_csv(data)
    n_test = sum(r["split"] == "test" for r in data)
    print(f"wrote {len(data)} rows ({len(data) - n_test} train / {n_test} test) -> {DATASET_PATH}")
