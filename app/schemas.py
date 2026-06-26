"""Pydantic schemas for API request/response bodies."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

ALLOWED_SITES = {"indeed", "linkedin", "glassdoor", "google", "zip_recruiter", "bayt", "naukri", "bdjobs"}


class JobOut(BaseModel):
    id: str
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
    match_status: str
    match_score: Optional[int] = None
    match_reason: Optional[str] = None
    matched_at: Optional[datetime] = None
    user_state: str

    model_config = {"from_attributes": True}


class JobsPage(BaseModel):
    items: list[JobOut]
    total: int
    page: int
    page_size: int


class ConfigOut(BaseModel):
    match_prompt: str
    openai_model: str
    search_terms: list[str]
    sites: list[str]
    location: str
    country_indeed: str
    hours_old: int
    results_wanted: int
    linkedin_fetch_description: bool
    schedule_enabled: bool
    schedule_hour: int
    schedule_minute: int
    prompt_version: int

    model_config = {"from_attributes": True}


class ConfigIn(BaseModel):
    match_prompt: str = Field(min_length=1)
    openai_model: str = Field(min_length=1)
    search_terms: list[str]
    sites: list[str]
    location: str = ""
    country_indeed: str = "UK"
    hours_old: int = Field(ge=1, le=2400)
    results_wanted: int = Field(ge=1, le=1000)
    linkedin_fetch_description: bool = True
    schedule_enabled: bool = True
    schedule_hour: int = Field(ge=0, le=23)
    schedule_minute: int = Field(ge=0, le=59)

    @field_validator("search_terms")
    @classmethod
    def _clean_terms(cls, v: list[str]) -> list[str]:
        terms = [t.strip() for t in v if t and t.strip()]
        if not terms:
            raise ValueError("at least one search term is required")
        return terms

    @field_validator("sites")
    @classmethod
    def _clean_sites(cls, v: list[str]) -> list[str]:
        sites = [s.strip().lower() for s in v if s and s.strip()]
        bad = [s for s in sites if s not in ALLOWED_SITES]
        if bad:
            raise ValueError(f"unsupported sites: {bad}")
        if not sites:
            raise ValueError("at least one site is required")
        return sites


class RunStatus(BaseModel):
    is_running: bool
    run_id: Optional[int] = None
    status: Optional[str] = None
    trigger: Optional[str] = None
    message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    scraped_count: int = 0
    new_count: int = 0
    matched_count: int = 0
    error_count: int = 0
    next_run_at: Optional[datetime] = None


class Stats(BaseModel):
    total: int = 0
    matched: int = 0
    rejected: int = 0
    pending: int = 0
    error: int = 0
    applied: int = 0
    dismissed: int = 0


class JobStateIn(BaseModel):
    user_state: str

    @field_validator("user_state")
    @classmethod
    def _valid(cls, v: str) -> str:
        if v not in {"new", "applied", "dismissed"}:
            raise ValueError("user_state must be new, applied, or dismissed")
        return v


class ActionResult(BaseModel):
    ok: bool = True
    detail: Optional[str] = None


class SuggestTermsIn(BaseModel):
    # Optional so the UI can send the (possibly unsaved) prompt currently in the textarea.
    prompt: Optional[str] = None
    model: Optional[str] = None


class SuggestTermsOut(BaseModel):
    terms: list[str]
