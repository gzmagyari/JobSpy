"""Pipeline orchestration: scrape -> dedup/store -> match pending -> finalise.

A module-level lock guarantees a single concurrent run within the process
(the scheduler and the manual-run endpoint both call run_pipeline).
"""
from __future__ import annotations

import logging
import threading

from sqlmodel import Session, select

from app.db import engine, init_db
from app.matcher import Matcher
from app.models import Job, Run, Setting, now
from app.scraper import scrape_all

log = logging.getLogger("jobhunter.pipeline")

_run_lock = threading.Lock()

# Persist a progress update to the Run row every N matched jobs.
_PROGRESS_EVERY = 3


class AlreadyRunningError(RuntimeError):
    """Raised when a run is requested while one is already in progress."""


def is_running() -> bool:
    return _run_lock.locked()


def _set_status(run_id: int, **fields) -> None:
    with Session(engine) as session:
        run = session.get(Run, run_id)
        if run is None:
            return
        for key, value in fields.items():
            setattr(run, key, value)
        session.add(run)
        session.commit()


def run_pipeline(trigger: str = "manual", do_scrape: bool = True) -> dict:
    """Run one cycle. With do_scrape=False, only (re)matches pending jobs."""
    if not _run_lock.acquire(blocking=False):
        raise AlreadyRunningError("A run is already in progress")

    run_id: int | None = None
    try:
        with Session(engine) as session:
            settings = session.get(Setting, 1)
            if settings is None:
                raise RuntimeError("settings row missing; call init_db() first")
            # Detach a plain copy of the fields we need after the session closes.
            settings = Setting.model_validate(settings, from_attributes=True)
            first_msg = "Scraping job boards…" if do_scrape else "Re-matching jobs…"
            run = Run(status="running", trigger=trigger, message=first_msg)
            session.add(run)
            session.commit()
            session.refresh(run)
            run_id = run.id

        log.info("run %s started (trigger=%s, scrape=%s)", run_id, trigger, do_scrape)

        # 1) Scrape (no DB session held during network I/O).
        scraped = scrape_all(settings) if do_scrape else []

        # 2) Store new jobs as pending (dedup by id).
        new_count = 0
        if scraped:
            with Session(engine) as session:
                for jd in scraped:
                    if session.get(Job, jd["id"]) is not None:
                        continue
                    session.add(Job(**jd))  # match_status defaults to "pending"
                    new_count += 1
                session.commit()
        _set_status(
            run_id, scraped_count=len(scraped), new_count=new_count,
            message=(
                f"Scraped {len(scraped)} ({new_count} new). Matching…"
                if do_scrape else "Matching pending jobs…"
            ),
        )

        # 3) Match every pending job (resumes any left over from prior runs).
        with Session(engine) as session:
            pending_ids = list(
                session.exec(select(Job.id).where(Job.match_status == "pending")).all()
            )

        matched_count = error_count = 0
        if pending_ids:
            matcher = Matcher(model=settings.openai_model, prompt=settings.match_prompt)
            total = len(pending_ids)
            for i, job_id in enumerate(pending_ids, start=1):
                with Session(engine) as session:
                    job = session.get(Job, job_id)
                    if job is None:
                        continue
                    try:
                        result = matcher.match(job)
                        job.match_status = "matched" if result.is_match else "rejected"
                        job.match_score = result.score
                        job.match_reason = result.reason
                        job.match_error = None
                        job.matched_at = now()
                        job.prompt_version = settings.prompt_version
                        if result.is_match:
                            matched_count += 1
                    except Exception as exc:  # noqa: BLE001 — record + continue
                        log.exception("match failed for %s", job_id)
                        job.match_status = "error"
                        job.match_error = str(exc)[:500]
                        error_count += 1
                    session.add(job)
                    session.commit()

                if i % _PROGRESS_EVERY == 0 or i == total:
                    _set_status(
                        run_id, matched_count=matched_count, error_count=error_count,
                        message=f"Matching {i}/{total} (matched {matched_count})",
                    )

        # Update the chat search index (embed any new jobs). Non-fatal.
        _set_status(run_id, message="Updating search index…")
        try:
            from app.embeddings import embed_missing

            embed_missing()
        except Exception:
            log.exception("embedding step failed (non-fatal)")

        summary = dict(
            run_id=run_id, scraped=len(scraped), new=new_count,
            matched=matched_count, errors=error_count,
        )
        _set_status(
            run_id, status="completed", finished_at=now(),
            matched_count=matched_count, error_count=error_count,
            message=(
                f"Done. Scraped {len(scraped)}, {new_count} new, "
                f"{matched_count} matched, {error_count} errors."
            ),
        )
        log.info("run %s completed: %s", run_id, summary)
        return summary

    except Exception as exc:
        log.exception("run %s failed", run_id)
        if run_id is not None:
            _set_status(run_id, status="failed", finished_at=now(), error=str(exc)[:1000])
        raise
    finally:
        _run_lock.release()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )
    init_db()
    print(run_pipeline(trigger="cli"))
