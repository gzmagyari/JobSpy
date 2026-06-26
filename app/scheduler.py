"""APScheduler wiring: a daily cron job + on-demand manual runs.

Everything runs in-process (BackgroundScheduler thread pool). The pipeline's
own lock prevents overlap between a scheduled run and a manual one.
"""
from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session

from app.db import engine
from app.models import Setting
from app.pipeline import AlreadyRunningError, run_pipeline

log = logging.getLogger("jobhunter.scheduler")

scheduler = BackgroundScheduler(timezone="Europe/London")
DAILY_JOB_ID = "daily_pipeline"
MANUAL_JOB_ID = "manual_pipeline"


def _run(trigger: str, do_scrape: bool = True) -> None:
    try:
        run_pipeline(trigger=trigger, do_scrape=do_scrape)
    except AlreadyRunningError:
        log.info("%s run skipped — a run is already in progress", trigger)
    except Exception:
        log.exception("%s run crashed", trigger)


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.start()
    apply_schedule()


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


def apply_schedule() -> None:
    """Create/replace/remove the daily job to match the current settings."""
    with Session(engine) as session:
        cfg = session.get(Setting, 1)
    if cfg is None:
        return
    if cfg.schedule_enabled:
        scheduler.add_job(
            _run,
            trigger=CronTrigger(hour=cfg.schedule_hour, minute=cfg.schedule_minute),
            id=DAILY_JOB_ID,
            replace_existing=True,
            args=["scheduled"],
            coalesce=True,
            max_instances=1,
        )
        log.info("daily run scheduled at %02d:%02d", cfg.schedule_hour, cfg.schedule_minute)
    elif scheduler.get_job(DAILY_JOB_ID):
        scheduler.remove_job(DAILY_JOB_ID)
        log.info("daily run disabled")


def trigger_manual_run(do_scrape: bool = True) -> None:
    """Kick off a one-off run now. Raises AlreadyRunningError if one is active.

    do_scrape=False re-matches already-stored jobs without scraping again.
    """
    from app.pipeline import is_running

    if is_running():
        raise AlreadyRunningError("A run is already in progress")
    scheduler.add_job(
        _run, id=MANUAL_JOB_ID, replace_existing=True,
        args=["manual" if do_scrape else "rematch", do_scrape],
        misfire_grace_time=60,
    )


def next_run_time() -> Optional[object]:
    job = scheduler.get_job(DAILY_JOB_ID)
    return job.next_run_time if job else None
