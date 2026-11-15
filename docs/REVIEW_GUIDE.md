# CampusNova — Review Preparation Guide

Everything you need to explain the project end to end and to answer questions. Read §1–§3 once, then your own section in §5.
Be honest about limits (§7): reviewers trust a team that knows its own gaps.

---

## 1. The project in one minute
**Problem.** In a college, faults (a dead fan, sparks from a switchboard, no wifi, no water) are reported on paper or WhatsApp, nobody knows who owns them, urgent ones wait, and management has no overview.

**Solution — CampusNova.** A web app where a floor in-charge / faculty / staff member reports a problem. Then, automatically:
1. **AI classifies** it: category (electrical, civil, networking, sanitation, laboratory, general), priority (low/medium/high/critical), safety risk, confidence.
2. Priority gives a **deadline (SLA)**: critical 4 h, high 24 h, medium 72 h, low 168 h.
3. **Routing rules** map category → responsible department; the **auto-assigner** gives the job to the least-loaded active worker of that department. Workers can also **take open jobs themselves**, so nobody has to assign manually.
4. The job moves through a **workflow**: registered → assigned → in progress → resolved → closed. Reporter confirms the fix (or reopens).
5. If the deadline nears or passes: **warning at 75 %**, then **3 escalation levels**, each sending notifications (in-app, e-mail, push).
6. **Admin dashboard**: totals, emergencies, overdue, AI accuracy, plus AI-review queue where uncertain AI results are confirmed/overridden by a human.

**Roles:** Admin · Reporter (floor in-charge, faculty, staff) · Maintenance worker (electrician, plumber, civil, network). Each role gets its own screens.

## 2. Architecture (end to end)
```
Browser (React + Vite, Vercel project 2)
   │  HTTPS, JSON, JWT access token (+ refresh token)
   ▼
FastAPI on Vercel (one serverless function: api/index.py)
   ├─ app/api        routers: auth, users, complaints, workflow, ai, dashboard, notifications, cron
   ├─ app/services   business rules (workflow, assignment, escalation, notifications, images, AI)
   ├─ app/core       config, security (scrypt, JWT), permissions (RBAC), errors, middleware
   ├─ ml/            trained models (loaded from ml/artifacts)
   └─ SQLAlchemy → hosted MySQL (Alembic migrations)
GitHub Actions (every 5 min) → /cron/all → SLA check, auto-assign sweep, notification dispatch
Firebase (optional): Google sign-in + web push (FCM)
```
**Life of one complaint:** form → `POST /complaints` → validate → AI predicts → save complaint + history row + audit event → set deadline → find department (routing rule) → auto-assign worker → notifications created (pending rows) → dispatcher sends them (in-app/e-mail/push, up to 3 retries) → worker starts/resolves with a note → reporter signs off → closed. Every step writes `complaint_history` (timeline) and a notification.

**Database tables:** departments, users, complaints, assignments, complaint_history, complaint_images (photo bytes live here), notifications, plus AI predictions, routing rules, refresh tokens, audit events. Migration chain: team's first schema → 0003 (integration: AI/auth/routing, additive and non-destructive, tested with existing data) → 0004 (photos in DB).

## 3. Key design decisions — and why
| Decision | Why |
|---|---|
| One FastAPI backend, one React frontend, one repo | Five people's modules must work together; a single API contract and shared tests prove it. |
| Unified SQLAlchemy `Base` and enums | The team's models and ours had to agree; enums stored as VARCHAR so MySQL and SQLite behave the same and new values need no ALTER. |
| Additive migration 0003 | Never rewrite the team's applied migration; extend it. Downgrade tested on MySQL. |
| Department-based assignment + routing rules table | Real colleges route by department; rules are data, so admins change them without code (Routing screen). |
| Workload weights (critical 4, high 3, medium 2, low 1) | A worker with one critical job is as busy as one with four low jobs. |
| Auto-assign sweep with 10-minute grace | Gives a human/AI-review a chance first; nothing stays unassigned. |
| AI review queue + confidence threshold | The model is imperfect; uncertain cases go to a human, safety hazards are never left waiting. |
| Safety keywords force high/critical | Cost of missing a spark/gas leak is far higher than a false alarm. |
| Rules + ML (hybrid) | Rules are explainable and safe; ML generalises to new wording; if ML is unsure the rules decide. |
| scrypt password hashing | Memory-hard, in Python's standard library, resists GPU cracking. |
| JWT access (30 min) + refresh rotation with reuse detection | Short-lived access tokens; if a stolen refresh token is replayed the whole token family is revoked. |
| Lockout 5 fails / 15 min | Stops password guessing per account. |
| RBAC table (`permissions.py`) | One place lists who can do what; every endpoint calls `require_permission`. |
| Photos in the database, shrunk in the browser | Vercel has no persistent disk and rejects bodies over 4.5 MB. Server re-encodes images (strips EXIF/GPS, blocks disguised files). |
| NullPool + TLS for MySQL on Vercel | Serverless functions must not hold connection pools; hosted MySQL needs TLS. |
| Cron endpoints + GitHub Actions | Serverless has no background threads; Vercel Hobby cron is once a day, Actions gives 5-minute runs free. |
| Notification rows + dedupe keys | Sending is decoupled from the request; retries and "send once" are guaranteed by data, not luck. |
| Standard error format `{"error":{code,message,details}}` | The frontend shows the same readable message for every failure. |

## 4. How the AI works (Vennela's area, but everyone should know this)
* **Rule engine**: weighted keyword signals (severity, impact, safety) → matrix (severity × impact, safety override) → priority.
* **ML**: TF-IDF text features + domain features → Logistic Regression / LinearSVC (calibrated) / Naive Bayes; best picked by grouped cross-validation. Separate models for category, severity, impact, safety.
* **Combination**: ML predicts; if confidence is low → rule fallback + manual review flag; safety = ML probability OR rule keyword; negated phrases ("no sparks") are stripped.
* **Training data**: synthetic (hand-written issue phrases × scope phrases × urgency wording), ~1,800 rows. There is no real history yet.
* **Accuracy (be exact):**

| Test | Category | Priority | Say it like this |
|---|---|---|---|
| Random 80/20 | ~98% | ~97% | "optimistic: same templates in train and test" |
| Strict hold-out | ~76–78% | ~70% | "unseen issue types" |
| Blind set C (41 fresh complaints) | 73% | 61% (90% within one level) | "our honest estimate on new wording" |

* **If asked "why not 90%?"** — trained on synthetic data; real complaints use different words; the fix is training on a few hundred real labelled complaints (retrain with one command); meanwhile the review queue and safety rules protect users. We measured it on an independent set instead of reporting only the flattering number.

## 5. Per person: what you did, how to explain it, likely questions

### Nakshatra — integration, delivery, quality
**Built:** unified error format, app wiring (routers, CORS, middleware, health), migration 0003/0004, end-to-end and migration tests, Vercel config (`vercel.json`, `api/index.py`), GitHub Actions (tests + 5-minute jobs), Postman collection, operating guide, README.
**Demo:** `/health`, `/health/db`; run `pytest tests/test_e2e.py`; show a migration upgrade/downgrade.
**Q&A**
* *Why Alembic?* Versioned, repeatable schema changes; can upgrade/downgrade; never edit applied migrations.
* *How do you know migrations work on existing data?* A test creates the team's original schema with rows, runs 0003/0004, checks rows survive; also run on MariaDB with downgrade.
* *How is it deployed?* Two Vercel projects (API root = repo, frontend root = `frontend/`), hosted MySQL, env vars for secrets, GitHub Actions for schedules.
* *Why a cron endpoint?* Serverless functions don't run in the background; `/cron/all` is protected with a bearer secret.
* *Why `NullPool`?* Each invocation is short-lived; pooled connections would be leaked/exhausted.
* *What isn't verified?* A live Vercel deploy and your hosted MySQL 8 (we ran MariaDB 10.11).

### Chethana — authentication & security
**Built:** login, scrypt hashing, JWT access/refresh with rotation and reuse detection, lockout, logout, change password, user management, RBAC, security headers, CORS allow-list, Firebase Google sign-in (code), React login + route guards + token-refresh interceptor. 93 auth/security tests.
**Demo:** log in as each role; show a 403 for a forbidden action; 5 wrong passwords → locked; Swagger `/docs`.
**Q&A**
* *Why scrypt, not SHA-256?* Fast hashes are brute-forceable; scrypt is deliberately slow and memory-hard, with per-user salt.
* *What is refresh-token rotation?* Each refresh issues a new refresh token and invalidates the old one; if an old one is reused, we assume theft and revoke the whole family.
* *Where is access control enforced?* On the server (`require_permission`), never only in the UI. The UI just hides buttons.
* *How do you stop SQL injection?* SQLAlchemy parameterised queries; pydantic validates inputs.
* *XSS?* React escapes output; security headers (nosniff, frame deny) set by middleware; no HTML is rendered from user text.
* *What about Firebase?* Server verifies Google ID tokens against Google certs and maps the e-mail to an existing user; needs your Firebase project id; tested with fakes.
* *Gaps:* no per-IP throttling (per-account lockout only).

### Jahnavi — complaints module & images
**Built:** complaint create/list/detail with filters, search, sort, pagination; validation; photo pipeline (magic-byte check, decode validation, pixel cap, re-encode to strip EXIF/payloads, 1600 px resize, 320 px thumbnail, sha256 de-dup, max 5 photos); React complaint form, list, detail modal; browser-side image shrink.
**Demo:** report a complaint with two photos; open the detail; try uploading a `.exe` renamed `.jpg` → rejected.
**Q&A**
* *Why not trust the file extension?* Attackers rename files; we read the real bytes (magic numbers) and re-encode the image so nothing hidden survives.
* *Why store photos in the DB?* Vercel has no persistent disk; MEDIUMBLOB column, loaded lazily (`deferred`) so list queries stay fast.
* *Why 4 MB limit?* Vercel rejects request bodies over 4.5 MB; the browser shrinks photos first.
* *How is the list scoped?* Reporters see their own complaints, workers theirs, admins all.
* *Why is the description validated?* Too-vague text ("fix it") gives the AI nothing to classify; the API returns field-level errors.

### Sadhvika — workflow, routing rules, worker actions
**Built:** status state machine, who may do which transition, resolve-needs-a-note, assignment (manual/auto/claim), release, remarks, sign-off/reopen, timeline, routing rules API and Routing screen, My work / Open jobs screens. 45 tests including the full 5×5 transition matrix.
**Demo:** report → worker takes from pool → start → resolve with note → reporter confirms → show timeline; change a routing rule.
**Q&A**
* *What is a state machine and why?* A fixed table of allowed moves (`ALLOWED`); impossible jumps (registered → closed) are rejected, so data can't get inconsistent.
* *Who can close?* Only the person who reported it (sign-off) or an admin; the worker cannot close their own job. Reopen is by the reporter or admin.
* *Why must "resolved" have a note?* Auditability: the reporter sees what was done.
* *How does claim avoid two workers taking one job?* The claim checks that the job is still unassigned and claimable; the second worker gets "already taken by X". (Honest limit: there is no row lock, so two truly simultaneous clicks could race; a `SELECT ... FOR UPDATE` would close that.)
* *What if no worker exists in the department?* Falls back to the least-busy worker overall.

### Vennela — AI, SLA, notifications, dashboards, auto-assignment
**Built:** everything in §4; auto-assignment and worker pool; SLA check and escalation levels; notification service (in-app, SMTP, FCM), retries, dedupe, user preferences; dashboards and AI-review screens; scheduler/cron jobs.
**Demo:** report "sparks from switchboard" → critical, 4 h, urgent alert; report "tube light flickering" → low; open the Admin dashboard and AI review; show `ml/reports/INDEPENDENT.md`.
**Q&A**
* *Why two models (rules + ML)?* Rules are explainable and catch hazards; ML handles new wording; together safer than either.
* *Why not deep learning?* Little data; TF-IDF + linear models train in seconds and are explainable.
* *How do you evaluate?* Grouped cross-validation, strict hold-out by unseen issues, random split (reported as optimistic), and an independent hand-written set — accuracy 73% / 61% on truly new wording; we state it plainly.
* *How do you avoid missing emergencies?* Safety keywords/ML probability force critical; the threshold is deliberately low (safety first); critical recall is monitored.
* *How does SLA escalation work?* Warning at 75% of the window; level 1 = deadline passed (assignee + admins), level 2 = overdue by 50% of the window, level 3 = overdue by 100% (admins, and the reporter is told); dedupe keys prevent repeats; resolved complaints never escalate.
* *How do notifications survive failures?* They are rows: pending → sent/failed, up to 3 retries, permanent errors (no e-mail address, bad push token) are not retried.
* *What would you do next?* Collect real complaints, retrain, add photo analysis.

## 6. Demo script (7 minutes)
1. Admin login → dashboard (numbers, emergencies, AI performance).
2. Faculty login → *Report a problem*: "Sparks from the switch board in physics lab" + photo → result: critical, 4 h, assigned.
3. Electrician login → *My work* shows the job → open → Start → Resolve with a note.
4. Faculty → complaint timeline → *Confirm fixed*.
5. Admin → *AI review* (confirm/override), *Routing rules*, *Users*.
6. Show notifications + preferences; `/docs` Swagger; run `pytest` (green).

## 7. Honest limitations (say these before they are asked)
* AI trained on synthetic data: 73% category / 61% priority on fresh wording; not 90%.
* Not yet run on a live Vercel deployment or your hosted MySQL 8 (verified on MariaDB 10.11, SQLite, and in a browser against the live API).
* E-mail verified only against a local fake SMTP server; Firebase/FCM verified with fakes, no real credentials.
* Vercel Hobby cron is daily; the 5-minute schedule comes from GitHub Actions.
* No per-IP login throttling; no real-time websockets (screens refresh on action / reload).

## 8. Quick facts to remember
Stack: FastAPI, SQLAlchemy 2, Alembic, MySQL (PyMySQL), React 18 + Vite, JWT, scrypt, scikit-learn, Pillow, Vercel, GitHub Actions, Firebase (optional).
SLA: critical 4 h · high 24 h · medium 72 h · low 168 h. Lockout: 5 fails / 15 min. Tokens: access 30 min, refresh 7 days. Photos: ≤5 per complaint, ≤4 MB each.
