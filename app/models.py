"""SQLModel tables: Job (also the LLM work-queue), Run, Setting."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def now() -> datetime:
    """Local naive timestamp (fine for a single-user personal dashboard)."""
    return datetime.now()


class Job(SQLModel, table=True):
    """One scraped job. `match_status` drives the matching work-queue."""

    # jobspy id, e.g. "in-abc123" / "li-456789" — stable + unique per posting.
    id: str = Field(primary_key=True)
    site: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    job_url: Optional[str] = None
    job_url_direct: Optional[str] = None
    description: Optional[str] = None
    date_posted: Optional[date] = None
    is_remote: Optional[bool] = None
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    currency: Optional[str] = None
    company_industry: Optional[str] = None
    company_logo: Optional[str] = None

    scraped_at: datetime = Field(default_factory=now)

    # Matching state: pending -> matched | rejected | error
    match_status: str = Field(default="pending", index=True)
    match_score: Optional[int] = None
    match_reason: Optional[str] = None
    match_error: Optional[str] = None
    matched_at: Optional[datetime] = None
    prompt_version: Optional[int] = None

    # User action in the dashboard: new | applied | dismissed
    user_state: str = Field(default="new", index=True)


class Run(SQLModel, table=True):
    """One pipeline run (scheduled or manual). Powers the live status strip."""

    id: Optional[int] = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=now)
    finished_at: Optional[datetime] = None
    status: str = "running"  # running | completed | failed
    trigger: str = "manual"  # manual | scheduled | cli
    scraped_count: int = 0
    new_count: int = 0
    matched_count: int = 0
    error_count: int = 0
    message: Optional[str] = None
    error: Optional[str] = None


class Setting(SQLModel, table=True):
    """Single-row (id=1) configuration, editable from the dashboard."""

    id: Optional[int] = Field(default=1, primary_key=True)
    match_prompt: str = ""
    openai_model: str = "gpt-4o-mini"
    search_terms: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    sites: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    location: str = "United Kingdom"
    country_indeed: str = "UK"
    hours_old: int = 48
    results_wanted: int = 50
    linkedin_fetch_description: bool = True
    schedule_enabled: bool = True
    schedule_hour: int = 7
    schedule_minute: int = 0
    prompt_version: int = 1
    updated_at: datetime = Field(default_factory=now)
