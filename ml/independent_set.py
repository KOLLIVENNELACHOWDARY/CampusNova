"""Independent, hand-written and hand-labelled complaints (120), written in different styles from the
synthetic generator: informal wording, typos, short messages, long explanations.

Two halves, to keep the evaluation honest:
  * SET_A ("tuning half", 60 rows): may be used for error analysis while improving the rules.
  * SET_B ("sealed half", 60 rows): evaluated blind, once per release. Never read for tuning.
Never used for training. Priority is derived with the project's matrix (severity x impact + safety + urgency).
Columns: text, category, severity, impact, safety_risk.
"""
from ml.common import final_priority, has_urgency

SET_A = [
    ("fan in room 12 making loud noise and not rotating properly", "electrical", "medium", "low", False),
    ("projector in seminar hall 2 is not turning on, we have a guest lecture at 2pm today", "electrical", "medium", "high", False),
    ("light is not working in the ladies washroom near library", "electrical", "medium", "low", False),
    ("socket near my desk is giving shock when i plug the charger", "electrical", "high", "low", True),
    ("current went in the entire girls hostel since last night", "electrical", "high", "high", False),
    ("generator did not start during power cut, labs are in dark", "electrical", "high", "high", False),
    ("tubelights in corridor are fused, kindly replace", "electrical", "low", "low", False),
    ("burning smell coming from the main panel board near the canteen", "electrical", "high", "medium", True),
    ("wifi is not connecting in CSE block 3rd floor", "networking", "medium", "medium", False),
    ("internet down in whole campus, no one can access anything", "networking", "high", "high", False),
    ("network cable cut near the admin block", "networking", "medium", "medium", False),
    ("router in the hostel is hanging again and again", "networking", "medium", "medium", False),
    ("online exam portal not loading for any student", "networking", "high", "high", False),
    ("my system in the staff room can't get IP address", "networking", "low", "low", False),
    ("projector wifi dongle not pairing in room 301", "networking", "low", "low", False),
    ("bathroom tap broken and water is wasting continuously", "sanitation", "medium", "low", False),
    ("toilets are stinking badly in the first floor", "sanitation", "medium", "medium", False),
    ("no water supply in the boys hostel since morning", "sanitation", "high", "high", False),
    ("sewage water is flowing on the road in front of the mess", "sanitation", "high", "medium", False),
    ("garbage not collected for 3 days near the ground", "sanitation", "medium", "medium", False),
    ("drinking water purifier near the office is not working", "sanitation", "medium", "medium", False),
    ("flush is not working in staff toilet", "sanitation", "low", "low", False),
    ("wall plaster coming off in classroom 7", "civil", "medium", "low", False),
    ("big crack in the wall of the old block and it is increasing", "civil", "high", "medium", True),
    ("ceiling fan fell down in the class, luckily nobody was hurt", "electrical", "high", "medium", True),
    ("door of the lab is stuck and cannot be closed", "civil", "low", "low", False),
    ("staircase railing is loose near the main entrance", "civil", "high", "high", True),
    ("water leaking from roof in the library after rain, books getting wet", "civil", "medium", "medium", False),
    ("bench legs are broken in the seminar hall", "civil", "low", "low", False),
    ("floor tiles are broken in the corridor, people may trip", "civil", "medium", "medium", False),
    ("chemicals spilled in the chemistry lab and fumes are spreading", "laboratory", "high", "medium", True),
    ("the fume hood is not working in the organic chemistry lab", "laboratory", "high", "medium", True),
    ("the lab computers are very slow and hanging during practicals", "laboratory", "medium", "medium", False),
    ("balance in the physics lab shows wrong weight", "laboratory", "low", "low", False),
    ("gas cylinder in the lab is leaking", "laboratory", "high", "medium", True),
    ("biology lab microscopes need cleaning and lens replacement", "laboratory", "low", "low", False),
    ("3D printer in the mech lab is jammed and our project submission is tomorrow", "laboratory", "medium", "high", False),
    ("lab coat hooks are missing in the chemistry lab", "laboratory", "low", "low", False),
    ("lift is not working", "general", "medium", "medium", False),
    ("auditorium chairs are dirty and some are broken", "general", "low", "medium", False),
    ("bus no 5 is not coming on time every day", "general", "low", "medium", False),
    ("fire extinguisher in the corridor is expired", "general", "high", "medium", True),
    ("monkeys entered the canteen and are attacking students", "general", "high", "medium", True),
    ("cctv camera near the gate is not working", "general", "medium", "medium", False),
    ("notice board glass is broken", "general", "low", "low", False),
    ("PA system in the auditorium has no sound", "general", "medium", "medium", False),
    ("there are sparks in the extension board of the computer lab", "electrical", "high", "medium", True),
    ("AC in the principal's room is leaking water on the floor", "electrical", "medium", "low", False),
    ("inverter battery is bulging in the server room", "electrical", "high", "high", True),
    ("hostel room geyser gives shock", "electrical", "high", "low", True),
    ("ethernet port in lab 4 is not working", "networking", "medium", "low", False),
    ("wifi password changed and nobody informed students", "networking", "low", "medium", False),
    ("washbasin in the lab is blocked", "sanitation", "medium", "low", False),
    ("cockroaches in the canteen kitchen", "sanitation", "medium", "medium", False),
    ("window in the classroom doesn't close properly", "civil", "low", "low", False),
    ("ceiling is about to collapse in the hostel corridor", "civil", "high", "high", True),
    ("water tank is overflowing on the terrace", "sanitation", "medium", "low", False),
    ("projector is blurry in room 9", "electrical", "low", "low", False),
    ("pH meter not calibrated in the water testing lab", "laboratory", "low", "low", False),
    ("class room blackboard needs repainting", "civil", "low", "low", False),
]

SET_B = [
    ("tube light flickering in lab 2", "electrical", "low", "low", False),
    ("whole of A block power off since 10 am, exams are going on", "electrical", "high", "high", False),
    ("mcb keeps tripping in the staff room", "electrical", "medium", "low", False),
    ("exposed wires hanging from the ceiling in corridor", "electrical", "high", "medium", True),
    ("cooler motor smoking in the hostel mess", "electrical", "high", "medium", True),
    ("street light near the hostel gate is not glowing", "electrical", "medium", "medium", False),
    ("smart board is not switching on in room 403", "electrical", "medium", "low", False),
    ("internet is very slow in the library", "networking", "medium", "medium", False),
    ("wifi not available in the new block at all", "networking", "medium", "high", False),
    ("college website is down and admissions are going on", "networking", "high", "high", False),
    ("switch in lab 5 is not working so 20 systems have no network", "networking", "high", "medium", False),
    ("mail server not sending mails to students", "networking", "medium", "medium", False),
    ("VPN not connecting from hostel", "networking", "low", "low", False),
    ("urinals in the ground floor are blocked", "sanitation", "medium", "medium", False),
    ("water is dirty and yellow coming from the tap in hostel", "sanitation", "high", "high", False),
    ("dustbin is full near the cafeteria", "sanitation", "low", "low", False),
    ("pipe burst near the lab and water is everywhere", "sanitation", "high", "medium", False),
    ("no soap in washrooms", "sanitation", "low", "low", False),
    ("mosquitoes everywhere near the water logging behind the hostel", "sanitation", "medium", "medium", False),
    ("RO plant not working for a week", "sanitation", "medium", "high", False),
    ("cracks in the lab roof and cement is falling on tables", "civil", "high", "medium", True),
    ("balcony railing is rusted and shaking", "civil", "high", "medium", True),
    ("potholes in front of the main gate", "civil", "medium", "medium", False),
    ("the compound wall near the playground has collapsed", "civil", "high", "medium", True),
    ("paint is peeling in the corridor", "civil", "low", "low", False),
    ("door handle is broken in room 22", "civil", "low", "low", False),
    ("drain cover is missing near the hostel, someone can fall", "civil", "high", "medium", True),
    ("gas leak smell in the chemistry lab store room", "laboratory", "high", "medium", True),
    ("acid bottle broke in lab and students are coughing", "laboratory", "high", "medium", True),
    ("oscilloscope not displaying signals", "laboratory", "medium", "low", False),
    ("lab systems are not starting during the university practical exam", "laboratory", "medium", "high", False),
    ("software license expired in the CAD lab", "laboratory", "medium", "high", False),
    ("workbench drawers are broken in the workshop", "laboratory", "low", "low", False),
    ("centrifuge is making a very loud noise", "laboratory", "medium", "low", False),
    ("lift stopped and two persons are inside", "general", "high", "medium", True),
    ("water cooler near the canteen is not cooling", "general", "low", "medium", False),
    ("stray dogs near the hostel are chasing students", "general", "medium", "medium", False),
    ("library AC not working in summer", "electrical", "medium", "medium", False),
    ("fire alarm keeps ringing without any reason", "general", "medium", "medium", False),
    ("need more parking space for staff vehicles", "general", "low", "low", False),
    ("shuttle bus broke down in the morning, many students are late", "general", "medium", "medium", False),
    ("a snake was seen near the garden", "general", "high", "medium", True),
    ("hostel mess food has insects", "general", "medium", "medium", False),
    ("sparking from the plug point in room 14 with a burning smell", "electrical", "high", "medium", True),
    ("new block wifi is dead across the entire college since morning", "networking", "high", "high", False),
    ("ups not working in the server room and servers are shutting down", "electrical", "high", "high", False),
    ("fan regulator is not working in the hostel room", "electrical", "low", "low", False),
    ("the toilet door lock is broken in girls washroom", "civil", "medium", "medium", False),
    ("drinking water pipeline is leaking near the mess", "sanitation", "medium", "medium", False),
    ("ceiling leaking in lab, near the electrical equipment", "civil", "high", "medium", True),
    ("projector remote lost in room 6", "electrical", "low", "low", False),
    ("heavy water logging in the parking after rain", "civil", "medium", "medium", False),
    ("computers in the library are not connecting to internet", "networking", "medium", "medium", False),
    ("spillage of mercury in the physics lab", "laboratory", "high", "medium", True),
    ("restroom cleaning not done today", "sanitation", "low", "medium", False),
    ("window panes are broken in the library, glass pieces on the floor", "civil", "medium", "medium", True),
    ("lights out in the whole library", "electrical", "medium", "high", False),
    ("auditorium mic crackling", "general", "low", "low", False),
    ("heater in the lab is not switching off", "laboratory", "high", "medium", True),
    ("student lockers keys are missing", "general", "low", "low", False),
]


def _rows(raw):
    out = []
    for text, cat, sev, imp, safety in raw:
        urgent = has_urgency(text)
        out.append({"text": text, "category": cat, "severity": sev, "impact": imp, "safety_risk": int(safety),
                    "urgent": int(urgent), "priority": final_priority(sev, imp, safety, urgent)})
    return out


def set_a():
    return _rows(SET_A)


def set_b():
    return _rows(SET_B)


# SET_C: written AFTER the v2 retrain, never used for tuning. The only fully blind set.
SET_C = [
    ("the exhaust fan in the kitchen of the mess is jammed", "electrical", "medium", "medium", False),
    ("lights in the entire PG block are going on and off every few minutes", "electrical", "medium", "high", False),
    ("wire is hanging loose from the pole near the cycle stand", "electrical", "high", "medium", True),
    ("table lamp in the reading room is not working", "electrical", "low", "low", False),
    ("hostel wifi is not working since last two days", "networking", "medium", "high", False),
    ("can't login to the lms from college network", "networking", "medium", "medium", False),
    ("network printer in the exam cell is offline and hall tickets are to be printed today", "networking", "medium", "high", False),
    ("wifi signal is weak in my room", "networking", "low", "low", False),
    ("toilet seat is broken in the staff washroom", "sanitation", "low", "low", False),
    ("rainwater has entered the ground floor corridor and the floor is slippery", "civil", "high", "medium", True),
    ("water is not coming to the third floor taps", "sanitation", "medium", "medium", False),
    ("sewage smell is coming from the lab drain", "sanitation", "medium", "medium", False),
    ("hostel bathroom drain is blocked and water is standing", "sanitation", "medium", "medium", False),
    ("steps outside the library are broken and uneven", "civil", "medium", "medium", False),
    ("a part of the false ceiling has come down in room 18", "civil", "high", "medium", True),
    ("wooden door of the staff room has termite damage", "civil", "low", "low", False),
    ("walls in the new block have started showing dampness", "civil", "medium", "medium", False),
    ("the beam above the hostel entrance has a deep crack", "civil", "high", "medium", True),
    ("vacuum pump in the chemistry lab is not working", "laboratory", "medium", "medium", False),
    ("students received a minor shock from the lab bench", "laboratory", "high", "medium", True),
    ("all computers in lab 3 are dead during the lab exam", "laboratory", "high", "high", False),
    ("spectrometer needs servicing", "laboratory", "low", "low", False),
    ("burner is leaking gas in the chemistry store", "laboratory", "high", "medium", True),
    ("test tubes are not available for the practical", "laboratory", "low", "medium", False),
    ("emergency exit door of the auditorium is locked", "general", "high", "medium", True),
    ("canteen is charging extra for food", "general", "low", "low", False),
    ("college bus ac is not working", "general", "low", "medium", False),
    ("water dispenser is empty in the admin office", "general", "low", "low", False),
    ("library issue desk computer is down so no one can borrow books", "laboratory", "medium", "medium", False),
    ("fire hydrant pipe is leaking near block B", "general", "medium", "medium", False),
    ("a stray cow is blocking the main gate every morning", "general", "low", "medium", False),
    ("sports room needs new nets", "general", "low", "low", False),
    ("CCTV monitors in the security cabin are blank", "networking", "medium", "medium", False),
    ("projector in room 5 shows green colour", "electrical", "low", "low", False),
    ("there was a loud bang and smoke from the transformer behind the canteen", "electrical", "high", "high", True),
    ("urgent: no electricity in the girls hostel and it is night", "electrical", "high", "high", False),
    ("ceiling water leakage is dripping onto the switch board", "civil", "high", "medium", True),
    ("floor of the washroom is very slippery and a student fell", "sanitation", "high", "medium", True),
    ("our internet is very slow", "networking", "medium", "medium", False),
    ("paint fumes in the classroom are giving headaches", "general", "medium", "medium", False),
    ("please clean the classroom board", "sanitation", "low", "low", False),
]


def set_c():
    return _rows(SET_C)
