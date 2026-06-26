"""FastAPI router exposing /api endpoints for the dashboard."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, or_
from sqlmodel import Session, select

from app.chat import run_chat
from app.db import get_session
from app.matcher import suggest_search_terms
from app.models import Job, Run, Setting, now
from app.pipeline import AlreadyRunningError, is_running
from app.schemas import (
    ActionResult, ChatIn, ChatOut, ConfigIn, ConfigOut, JobOut, JobsPage, JobStateIn,
    RunStatus, Stats, SuggestTermsIn, SuggestTermsOut,
)
from app.scheduler import apply_schedule, next_run_time, trigger_manual_run

log = logging.getLogger("jobhunter.api")
router = APIRouter(prefix="/api")


# ---- Config ----------------------------------------------------------------
@router.get("/config", response_model=ConfigOut)
def get_config(session: Session = Depends(get_session)):
    cfg = session.get(Setting, 1)
    if cfg is None:
        raise HTTPException(500, "settings not initialised")
    return cfg


@router.put("/config", response_model=ConfigOut)
def update_config(payload: ConfigIn, session: Session = Depends(get_session)):
    cfg = session.get(Setting, 1)
    if cfg is None:
        raise HTTPException(500, "settings not initialised")
    prompt_changed = payload.match_prompt.strip() != (cfg.match_prompt or "").strip()
    for key, value in payload.model_dump().items():
        setattr(cfg, key, value)
    if prompt_changed:
        cfg.prompt_version = (cfg.prompt_version or 1) + 1
    cfg.updated_at = now()
    session.add(cfg)
    session.commit()
    session.refresh(cfg)
    apply_schedule()  # pick up any schedule changes
    return cfg


@router.post("/config/suggest-terms", response_model=SuggestTermsOut)
def suggest_terms(payload: SuggestTermsIn, session: Session = Depends(get_session)):
    """Expand the matching prompt into broad search queries via the LLM."""
    cfg = session.get(Setting, 1)
    prompt = (payload.prompt or "").strip() or (cfg.match_prompt if cfg else "")
    model = (payload.model or "").strip() or (cfg.openai_model if cfg else "gpt-4o-mini")
    if not prompt:
        raise HTTPException(400, "Write a matching prompt first.")
    try:
        terms = suggest_search_terms(model=model, prompt=prompt)
    except Exception as e:
        raise HTTPException(502, f"Could not suggest terms: {e}")
    return SuggestTermsOut(terms=terms)


# ---- Jobs ------------------------------------------------------------------
@router.get("/jobs", response_model=JobsPage)
def list_jobs(
    session: Session = Depends(get_session),
    status: str = Query("matched"),
    site: str | None = None,
    q: str | None = None,
    include_dismissed: bool = False,
    sort: str = Query("date", pattern="^(date|score)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    filters = []
    if status != "all":
        filters.append(Job.match_status == status)
    if site:
        filters.append(Job.site == site)
    if not include_dismissed:
        filters.append(Job.user_state != "dismissed")
    if q:
        like = f"%{q}%"
        filters.append(or_(Job.title.ilike(like), Job.company.ilike(like)))  # type: ignore[attr-defined]

    total = session.exec(select(func.count()).select_from(Job).where(*filters)).one()

    if sort == "score":
        order = (Job.match_score.desc(), Job.date_posted.desc())  # type: ignore[union-attr]
    else:
        order = (Job.date_posted.desc(), Job.scraped_at.desc())  # type: ignore[union-attr]

    rows = session.exec(
        select(Job).where(*filters).order_by(*order)
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return JobsPage(
        items=[JobOut.model_validate(r) for r in rows],
        total=total, page=page, page_size=page_size,
    )


@router.post("/jobs/{job_id}/state", response_model=JobOut)
def set_job_state(job_id: str, payload: JobStateIn, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    job.user_state = payload.user_state
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.post("/jobs/rematch", response_model=ActionResult)
def rematch(
    session: Session = Depends(get_session),
    scope: str = Query("all", pattern="^(all|evaluated)$"),
):
    """Reset jobs to 'pending' and kick off a match-only run (no scraping)."""
    stmt = select(Job)
    if scope == "evaluated":
        stmt = stmt.where(Job.match_status.in_(["matched", "rejected", "error"]))  # type: ignore[attr-defined]
    jobs = session.exec(stmt).all()
    for job in jobs:
        job.match_status = "pending"
        job.match_score = None
        job.match_reason = None
        job.match_error = None
        job.matched_at = None
        session.add(job)
    session.commit()
    try:
        trigger_manual_run(do_scrape=False)
    except AlreadyRunningError:
        raise HTTPException(409, "a run is already in progress")
    return ActionResult(detail=f"Reset {len(jobs)} jobs; re-matching started.")


@router.post("/jobs/clear", response_model=ActionResult)
def clear_jobs(session: Session = Depends(get_session)):
    """Delete all stored jobs and run history (settings are kept)."""
    if is_running():
        raise HTTPException(409, "A run is in progress — try again once it finishes.")
    total = session.exec(select(func.count()).select_from(Job)).one()
    session.execute(delete(Job))
    session.execute(delete(Run))
    session.commit()
    return ActionResult(detail=f"Cleared {total} jobs and run history.")


# ---- Runs / stats ----------------------------------------------------------
@router.post("/run", response_model=ActionResult, status_code=202)
def start_run():
    try:
        trigger_manual_run(do_scrape=True)
    except AlreadyRunningError:
        raise HTTPException(409, "a run is already in progress")
    return ActionResult(detail="Run started.")


@router.get("/run/status", response_model=RunStatus)
def run_status(session: Session = Depends(get_session)):
    run = session.exec(select(Run).order_by(Run.id.desc())).first()  # type: ignore[union-attr]
    nrt = next_run_time()
    if run is None:
        return RunStatus(is_running=is_running(), next_run_at=nrt)
    return RunStatus(
        is_running=is_running(),
        run_id=run.id, status=run.status, trigger=run.trigger, message=run.message,
        started_at=run.started_at, finished_at=run.finished_at,
        scraped_count=run.scraped_count, new_count=run.new_count,
        matched_count=run.matched_count, error_count=run.error_count,
        next_run_at=nrt,
    )


@router.get("/stats", response_model=Stats)
def stats(session: Session = Depends(get_session)):
    def count(**where) -> int:
        col = list(where.keys())[0]
        val = list(where.values())[0]
        column = getattr(Job, col)
        return session.exec(select(func.count()).select_from(Job).where(column == val)).one()

    return Stats(
        total=session.exec(select(func.count()).select_from(Job)).one(),
        matched=count(match_status="matched"),
        rejected=count(match_status="rejected"),
        pending=count(match_status="pending"),
        error=count(match_status="error"),
        applied=count(user_state="applied"),
        dismissed=count(user_state="dismissed"),
    )


# ---- Chat ------------------------------------------------------------------
@router.post("/chat", response_model=ChatOut)
def chat(payload: ChatIn, session: Session = Depends(get_session)):
    try:
        result = run_chat([m.model_dump() for m in payload.messages], model=payload.model)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("chat failed")
        raise HTTPException(502, f"chat error: {e}")

    jobs: list[JobOut] = []
    for jid in result.get("job_ids", []):
        job = session.get(Job, jid)
        if job is not None:
            jobs.append(JobOut.model_validate(job))
    return ChatOut(reply=result.get("reply", ""), jobs=jobs)
