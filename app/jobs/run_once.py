"""Run both background jobs once (for cron / Windows Task Scheduler / manual checks).

    python -m app.jobs.run_once                 # real time
    python -m app.jobs.run_once --hours-ahead 6 # pretend 6 hours have passed (to see escalations)
"""
import argparse
from datetime import timedelta

from app.core.timeutil import utcnow
from app.jobs.scheduler import dispatch_job, sla_check_job


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours-ahead", type=float, default=0.0)
    args = parser.parse_args()
    now = utcnow() + timedelta(hours=args.hours_ahead)
    print("SLA check :", sla_check_job(now=now))
    print("Dispatch  :", dispatch_job(now=now))


if __name__ == "__main__":
    main()
