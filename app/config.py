"""Application configuration: paths, secrets, and default settings."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# JobSpy/  (repo root)
BASE_DIR = Path(__file__).resolve().parent.parent
# JobSpy/app/
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "jobs.db"
FRONTEND_DIST = APP_DIR / "frontend" / "dist"

# Load secrets from the gitignored .env at the repo root.
load_dotenv(BASE_DIR / ".env")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Truncate very long descriptions before sending to the LLM (cost control).
DESCRIPTION_CHAR_LIMIT = 6000

# Default matching prompt — the user edits this from the dashboard Config page.
DEFAULT_PROMPT = (
    "I am looking for a new software engineering job in the UK.\n"
    "\n"
    "I am interested in:\n"
    "- Backend or full-stack roles using Python\n"
    "- Remote or hybrid positions\n"
    "- Mid to senior level\n"
    "\n"
    "I am NOT interested in:\n"
    "- Roles requiring security clearance\n"
    "- Purely frontend roles\n"
    "- Unpaid or commission-only roles\n"
    "\n"
    "Mark a job as a match only if it genuinely fits these preferences."
)

# Defaults used to seed the single settings row on first run.
DEFAULT_SETTINGS = dict(
    match_prompt=DEFAULT_PROMPT,
    openai_model="gpt-4o-mini",
    search_terms=["python developer"],
    sites=["indeed", "linkedin"],
    location="United Kingdom",
    country_indeed="UK",
    hours_old=48,
    results_wanted=50,
    linkedin_fetch_description=True,
    schedule_enabled=True,
    schedule_hour=7,
    schedule_minute=0,
)
