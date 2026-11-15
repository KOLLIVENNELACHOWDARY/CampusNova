# Operating guide

## 1. Run locally
See `README.md` → Quick start. Health: `GET /health` (process) and `GET /health/db` (database reachable).

## 2. Deploy on Vercel + MySQL
**A. Database.** Create a hosted MySQL 8 (Aiven, TiDB Cloud, Railway or any). Note host, port, user, password, db name. Hosted MySQL needs TLS.
**B. Create schema + first data (from your own computer, once):**
```bash
export DATABASE_URL="mysql+pymysql://USER:PASS@HOST:PORT/DB" DB_SSL=true SECRET_KEY=<32+ random chars> ENVIRONMENT=production
alembic upgrade head
python -m app.db.seed            # departments + routing rules only (no demo users)
python - <<'PY'                  # first admin
from app.db.session import SessionLocal
from app.services.auth import create_user
from app.core.enums import UserRole
with SessionLocal() as db:
    create_user(db, full_name="Admin", email="admin@yourcollege.edu", staff_id="ADM001", role=UserRole.ADMIN, password="ChangeMe123")
PY
```
(`python -m app.db.seed --demo` is for demos only: published password.)
**C. Backend project.** Vercel → Add New Project → import the GitHub repo → Root Directory = repo root → framework "Other". Environment variables:
`DATABASE_URL`, `DB_SSL=true`, `SECRET_KEY`, `ENVIRONMENT=production`, `CORS_ORIGINS=https://<your-frontend>.vercel.app`, `CRON_SECRET`, `CAMPUSNOVA_AUTO_ASSIGN=1`, `CAMPUSNOVA_NOTIFY_MODE=live` (after SMTP is ready), `SMTP_HOST/PORT/USER/PASSWORD/FROM`, optional `FIREBASE_PROJECT_ID`, `FIREBASE_CREDENTIALS_JSON`. Deploy, then open `/health` and `/health/db`.
**D. Frontend project.** Add another project from the same repo, Root Directory = `frontend`. Env: `VITE_API_URL=https://<backend>.vercel.app` (+ `VITE_FIREBASE_*` for Google sign-in/push). Add the frontend URL to the backend `CORS_ORIGINS` and redeploy the backend.
**E. Scheduler.** GitHub repo → Settings → Secrets → Actions: `API_URL` (backend URL) and `CRON_SECRET` (same as Vercel). `.github/workflows/jobs.yml` then runs SLA checks, auto-assign sweep and notification dispatch every 5 minutes. (Vercel's own cron in `vercel.json` runs once a day as a backup.) Manual test: `curl -H "Authorization: Bearer $CRON_SECRET" https://<backend>/cron/all`.

## 3. Daily use
* Reporters: **Report a problem** → describe it, add photos. The AI sets category/priority; you see the deadline.
* Admin: **Dashboard** (emergencies first), **AI review** (confirm/override flagged ones), **All complaints** (assign by hand if you wish), **Users** (add workers, disable leavers), **Routing rules** screen (category → department).
* Workers: **Open jobs** → *Take this job*; **My work** → *Start work* → write what you did → *Mark resolved*.
* Reporter then confirms (**Confirm fixed & close**) or reopens.

## 4. Background jobs (Vercel: `/cron/all` from GitHub Actions; on a normal server `CAMPUSNOVA_SCHEDULER=1`, single worker)
| Job | Every | Does |
|---|---|---|
| SLA check | 5 min | warning at 75% of window, escalation levels 1–3 after the deadline |
| Auto-assign sweep | 5 min | assigns unassigned jobs older than 10 min |
| Notification dispatch | 1 min | sends pending notifications, retries failures (max 3) |
Cron endpoints: `/cron/sla-check`, `/cron/auto-assign`, `/cron/dispatch`, `/cron/all` (Bearer `CRON_SECRET`). Run any job on demand as admin: `POST /admin/jobs/sla-check | auto-assign | dispatch`.
Running several API workers would run each job several times (de-duplication keys prevent duplicate messages, but use one worker or an external scheduler).

## 5. Configuration (`.env.example`)
`DATABASE_URL`, `SECRET_KEY` (production refuses the default), token lifetimes, lockout (5 failures → 15 min), `CORS_ORIGINS`, `DB_SSL`, `CRON_SECRET`, upload limits (4 MB, 5 photos), `FIREBASE_*`, `CAMPUSNOVA_AUTO_ASSIGN`, `CAMPUSNOVA_SCHEDULER`, `CAMPUSNOVA_NOTIFY_MODE` (`log`/`live`), SMTP_*, FCM.

## 6. Backups & upgrades
Back up the MySQL database (it also holds the photos). Upgrade: pull code → `alembic upgrade head` → restart. Never edit applied migrations; add a new one (`alembic revision --autogenerate -m "..."`, then review it).

## 7. Troubleshooting
| Symptom | Check |
|---|---|
| 401 on everything | token expired → sign in again; clock skew between server and client |
| 423 on login | account locked after 5 bad passwords; wait 15 min or admin resets the password |
| 503 `unavailable` | database unreachable (`/health/db`) |
| Nothing gets assigned | no active maintenance users, or complaint flagged for AI review, or `CAMPUSNOVA_AUTO_ASSIGN=0` |
| Browser CORS error | add the UI origin to `CORS_ORIGINS` |
| No e-mail/push arrives | `CAMPUSNOVA_NOTIFY_MODE` is `log` (simulation) or SMTP/FCM credentials missing; see failed rows in `notifications` |

## 8. API reference
Interactive: `/docs`. Postman: import `postman/CampusNova.postman_collection.json`, run a *Login* request first (token is stored automatically). All errors: `{"error": {"code", "message", "details?"}}` with codes `unauthorized, forbidden, not_found, validation_error, conflict, account_locked, unavailable, internal_error`.
