"""Thin wrapper around jobspy.scrape_jobs that yields clean job dicts."""
from __future__ import annotations

import logging

import pandas as pd

from jobspy import scrape_jobs

log = logging.getLogger("jobhunter.scraper")

# DataFrame columns we persist (date_posted handled separately).
_DF_FIELDS = [
    "id", "site", "title", "company", "location", "job_url", "job_url_direct",
    "description", "is_remote", "min_amount", "max_amount", "currency",
    "company_industry", "company_logo",
]
_STR_FIELDS = {
    "site", "title", "company", "location", "job_url", "job_url_direct",
    "description", "currency", "company_industry", "company_logo",
}


def _clean(value):
    """Convert pandas NaN/NaT to None; pass scalars through."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass  # non-scalar (e.g. list) — keep as is
    return value


def _row_to_job_dict(row) -> dict | None:
    d = {f: _clean(row.get(f)) for f in _DF_FIELDS}
    if not d.get("id"):
        return None
    d["id"] = str(d["id"])

    posted = row.get("date_posted")
    d["date_posted"] = None
    if posted is not None:
        ts = pd.to_datetime(posted, errors="coerce")
        if pd.notna(ts):
            d["date_posted"] = ts.date()

    d["is_remote"] = bool(d["is_remote"]) if d["is_remote"] is not None else None
    for f in ("min_amount", "max_amount"):
        d[f] = float(d[f]) if d[f] is not None else None
    for f in _STR_FIELDS:
        if d[f] is not None:
            d[f] = str(d[f])
    return d


def scrape_all(settings) -> list[dict]:
    """Scrape every configured search term across all sites; dedup by id."""
    by_id: dict[str, dict] = {}
    terms = settings.search_terms or [""]
    for term in terms:
        log.info("scraping term=%r sites=%s", term, settings.sites)
        try:
            df = scrape_jobs(
                site_name=settings.sites,
                search_term=term or None,
                google_search_term=term or None,
                location=settings.location,
                country_indeed=settings.country_indeed,
                results_wanted=settings.results_wanted,
                hours_old=settings.hours_old,
                linkedin_fetch_description=settings.linkedin_fetch_description,
                description_format="markdown",
                verbose=1,
            )
        except Exception:
            log.exception("scrape failed for term=%r", term)
            continue
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            jd = _row_to_job_dict(row)
            if jd:
                by_id[jd["id"]] = jd
    log.info("scrape_all collected %d unique jobs", len(by_id))
    return list(by_id.values())
