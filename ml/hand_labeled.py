"""Small hand-written, hand-labelled set of realistic complaints.

Used ONLY as an extra sanity check (never for training or model selection), because the
synthetic test split shares its sentence style with the training data.
Columns: text, category, severity (base), impact, safety_risk.
Priority is derived with the same matrix + urgency rule as the rest of the project.
"""
from ml.common import final_priority, has_urgency

_RAW = [
    ("Sparks are coming from the switch board in the physics lab, students are scared", "electrical", "high", "medium", True),
    ("The wifi has been down in the entire CSE block since morning and online classes are affected", "networking", "high", "high", False),
    ("Tube light in room 204 is flickering", "electrical", "low", "low", False),
    ("Ceiling fan is not working in the staff room", "electrical", "medium", "low", False),
    ("Washrooms on the second floor have no water since yesterday", "sanitation", "high", "medium", False),
    ("Drainage is overflowing near the canteen and there is a bad smell", "sanitation", "high", "medium", False),
    ("Computers in the CSE lab are not booting and the practical exam is tomorrow", "laboratory", "medium", "high", False),
    ("Two benches are broken in classroom 105", "civil", "medium", "low", False),
    ("Large cracks have appeared on the ceiling of the library and plaster is falling", "civil", "high", "medium", True),
    ("Please repaint the wall outside the principal office, the paint is peeling", "civil", "low", "low", False),
    ("Gas leak smell in the chemistry lab, please send someone immediately", "laboratory", "high", "medium", True),
    ("Internet is very slow in the hostel in the evenings", "networking", "medium", "medium", False),
    ("Water cooler near the library is not giving water", "sanitation", "medium", "medium", False),
    ("Lift is stuck between floors with students inside", "general", "high", "medium", True),
    ("Stray dogs are roaming around the main gate", "general", "medium", "medium", False),
    ("Dustbins are overflowing near the canteen", "sanitation", "medium", "medium", False),
    ("Switch board in the corridor is loose and wires are exposed", "electrical", "high", "medium", True),
    ("AC is not cooling in the seminar hall", "electrical", "medium", "medium", False),
    ("Unable to connect to wifi in the library", "networking", "medium", "medium", False),
    ("Window glass is broken in room 310", "civil", "medium", "low", False),
    ("Soap dispenser is empty in the boys washroom", "sanitation", "low", "low", False),
    ("Power cut in the whole hostel block since evening", "electrical", "high", "high", False),
    ("The microscope lens is cracked in the biology lab", "laboratory", "medium", "low", False),
    ("UPS in the server room is beeping and not working", "electrical", "medium", "high", False),
    ("Request for more seating arrangement in the library", "general", "low", "medium", False),
    ("Fire alarm is not working in the main building", "general", "high", "high", True),
    ("Roof is leaking in the classroom during rain", "civil", "medium", "medium", False),
    ("LAN port is dead on my table in the staff room", "networking", "medium", "low", False),
    ("Washroom floor is dirty and has not been cleaned for days", "sanitation", "low", "medium", False),
    ("Oscilloscope in the electronics lab is giving wrong readings", "laboratory", "medium", "medium", False),
    ("Parking area light is not working and it is very dark at night", "electrical", "medium", "medium", False),
    ("Door lock is broken in the examination hall, needs urgent repair", "civil", "medium", "high", False),
    ("ID card printer in the office is not working", "general", "medium", "low", False),
    ("Server is down and students cannot access the portal during the online exam", "networking", "high", "high", False),
    ("Tap is leaking continuously in the lab", "sanitation", "medium", "medium", False),
    ("Please fix the loose floor tile near the staircase", "civil", "low", "low", False),
]


def hand_labeled_rows() -> list[dict]:
    rows = []
    for text, cat, sev, imp, safety in _RAW:
        urgent = has_urgency(text)
        rows.append(
            {
                "text": text,
                "category": cat,
                "severity": sev,
                "impact": imp,
                "safety_risk": int(safety),
                "urgent": int(urgent),
                "priority": final_priority(sev, imp, safety, urgent),
            }
        )
    return rows
