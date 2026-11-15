# CampusNova — AI-powered campus complaint & maintenance management

Floor in-charges, faculty and staff report problems; an AI classifies each report (category + priority + deadline);
the system routes it to the responsible department, **assigns a maintenance worker automatically** (or workers take jobs
themselves), tracks it through a status workflow, warns and escalates when deadlines are missed, and gives admins a live
dashboard. Backend: FastAPI + SQLAlchemy + Alembic + MySQL. Frontend: React (Vite).

## Quick start (local, SQLite — or MySQL, see below)

```bash
python -m venv .venv && . .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
export DATABASE_URL=sqlite:///campusnova.db SECRET_KEY=any-long-random-string-32-chars-min
alembic upgrade head
python -m app.db.seed --demo                             # departments, routing rules, demo accounts
uvicorn app.main:app --reload                            # API on :8000, docs on :8000/docs

cd frontend && npm install && npm run dev                # UI on :5173
```
Windows PowerShell: `$env:DATABASE_URL="sqlite:///campusnova.db"; $env:SECRET_KEY="..."`.

Demo accounts (password `Campus@123`; **demo seed only — never in production**):

| Role | Login |
|---|---|
| Admin | admin@campusnova.edu |
| Floor in-charge | incharge.cse@campusnova.edu |
| Faculty | faculty.cse@campusnova.edu |
| Staff | staff.it@campusnova.edu |
| Maintenance | electrician@campusnova.edu · electrician2@ · civil@ · network@ · plumber@ (all @campusnova.edu) |

MySQL: put `mysql+pymysql://user:pass@host:3306/db` in `DATABASE_URL`, run `alembic upgrade head`. Deployment is on **Vercel**
(backend + frontend as two projects) with a hosted MySQL; steps in `docs/OPERATING_GUIDE.md`. Exam/review preparation: `docs/REVIEW_GUIDE.md`.

## What each role sees
* **Reporters** (floor in-charge / faculty / staff): report a problem (+ up to 5 photos), watch their complaints and the timeline, confirm a fix (sign-off) or reopen it.
* **Maintenance**: *My work* (assigned jobs, soonest deadline first), *Open jobs* (take a job themselves), start / finish with a note, hand a job back.
* **Admin**: dashboard (counts, charts, emergency list, AI performance), all complaints with filters, manual assignment, AI review queue (confirm / override), users, routing rules.

## How the AI part works
1. **Rule engine** (weighted keywords, severity × impact matrix, safety-risk detection) and a **multi-factor ML detector** (TF-IDF + linear models) predict category, priority and confidence. Priority sets the deadline: critical 4 h, high 24 h, medium 72 h, low 168 h.
2. Low-confidence or ambiguous predictions are **flagged for admin review**; nothing flagged is auto-assigned unless it is a safety risk.
3. **Routing** (`routing_rules`, editable by admin) maps the category to a responsible department (electrical → EEE, civil → Civil, networking → IT, sanitation → Mechanical (no plumbing department exists — change it if you add one), laboratory/general → the reporter's own department).
4. **Auto-assignment** picks the least-loaded active worker of that department (critical job = load 4, high 3, medium 2, low 1); if the department has nobody it falls back to the least-busy worker. Jobs nobody takes are swept up by a scheduler after a grace period.
5. **SLA**: warning at 75% of the window, then 3 escalation levels after the deadline; every step is a notification (in-app, email, push) with retries and de-duplication.

### Accuracy — honest numbers (synthetic training data; no real complaints yet)
| Test | Category | Priority | Meaning |
|---|---|---|---|
| Random 80/20 split | ~98% | ~97% | **Optimistic** — same wording families in train and test |
| Strict hold-out (unseen issue types/phrases) | ~76-78% | ~70% | Better estimate; safety recall ~99% |
| **Blind set C (41 fresh hand-written complaints)** | **73%** | **61%** (90% within one level) | **The honest figure** (rules alone: 56% / 49%) |

**We are not at 90%.** To get there the model must be trained on a few hundred real, labelled college complaints
(replace `ml/data/complaints.csv`, run `python -m ml.train`). Until then the admin AI-review queue catches uncertain
cases and safety keywords force high priority. Details: `ml/reports/INDEPENDENT.md`, `REPORT.md`, `RANDOM_SPLIT.md`.

## Tests
```bash
pytest                    # backend tests, ~3 min (SQLite in memory). TEST_DATABASE_URL=mysql+pymysql://... runs them on MySQL
cd frontend && npm test   # 21 frontend tests (every screen);  npm run build
```

## Layout
```
app/api        HTTP endpoints            app/services   business logic (workflow, complaints, assignment, AI, auth, images, notifications, escalation)
app/models     SQLAlchemy tables         app/core       config, security (JWT/scrypt), permissions (RBAC), errors, middleware
app/jobs       scheduler                 app/db         session, seed
migrations     Alembic (0003 integrates the AI/auth/routing tables on top of the team's first schema)
ml             training, data, reports   frontend       React app          postman   API collection        docs, team   guides & per-person notes
```

## Not verified / known limits (read before demo or deploy)
* **MySQL**: migrations and the whole test-suite were run against a real **MariaDB 10.11** (MySQL-compatible), including downgrade/upgrade with data. Your hosted MySQL 8 was not available — do `alembic upgrade head` once against it and check.
* **Vercel**: the configuration (`vercel.json`, `api/index.py`, NullPool, TLS, DB-stored photos, cron endpoints) is written to Vercel's rules but a real Vercel deploy was **not** run from here. Function size was measured at ~375 MB (limit 500 MB).
* **Email**: the SMTP sender was verified against a local fake SMTP server over the real protocol, not a real mail provider. **Firebase/FCM**: code is complete (token verification, FCM HTTP v1, web push) and tested with fakes; it needs your Firebase project credentials to run for real.
* **Cron**: Vercel Hobby allows one cron run per day, so a GitHub Actions workflow (`.github/workflows/jobs.yml`) hits `/cron/all` every 5 minutes (needs secrets `API_URL`, `CRON_SECRET`).
* **Photos** are stored inside the database (Vercel has no persistent disk); max 4 MB each (the web app shrinks them first because Vercel rejects bodies over 4.5 MB).
* **AI accuracy** is below 90% on fresh wording (see above).
* Login throttling is per account (lockout), not per IP.
