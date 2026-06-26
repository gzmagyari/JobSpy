"""Scraper for Reed.co.uk via the official Reed Jobseeker API.

Requires REED_API_KEY in the environment (free key from
https://www.reed.co.uk/developers/jobseeker-api). The key is the HTTP Basic
auth username, with an empty password.
"""
from __future__ import annotations

import math
import os
import time
from datetime import datetime, timedelta

from jobspy.model import (
    Compensation,
    CompensationInterval,
    Country,
    DescriptionFormat,
    JobPost,
    JobResponse,
    JobType,
    Location,
    Scraper,
    ScraperInput,
    Site,
)
from jobspy.util import create_logger, create_session, markdown_converter

log = create_logger("Reed")

_API = "https://www.reed.co.uk/api/1.0"
_UK_WIDE = {"", "uk", "united kingdom", "great britain", "england", "gb"}
_PER_PAGE = 100


class Reed(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.REED, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)
        self.api_key = os.getenv("REED_API_KEY")
        self.session = create_session(
            proxies=proxies, ca_cert=ca_cert, is_tls=False, has_retry=True, delay=2
        )
        if user_agent:
            self.session.headers["User-Agent"] = user_agent
        self.scraper_input: ScraperInput | None = None

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        self.scraper_input = scraper_input
        if not self.api_key:
            log.error("REED_API_KEY not set — skipping Reed. Add it to .env.")
            return JobResponse(jobs=[])

        wanted = scraper_input.results_wanted
        cutoff = None
        if scraper_input.hours_old:
            cutoff = (datetime.now() - timedelta(hours=scraper_input.hours_old)).date()

        jobs: list[JobPost] = []
        skip = scraper_input.offset or 0
        total = None
        pages = 0
        max_pages = math.ceil(wanted / _PER_PAGE) + 1

        while len(jobs) < wanted and pages < max_pages:
            pages += 1
            params = {
                "keywords": scraper_input.search_term or "",
                "resultsToTake": min(_PER_PAGE, wanted - len(jobs)),
                "resultsToSkip": skip,
            }
            loc = (scraper_input.location or "").strip()
            if loc and loc.lower() not in _UK_WIDE:
                params["locationName"] = loc
                params["distanceFromLocation"] = scraper_input.distance or 10
            log.info(f"search page: {pages} (skip={skip})")
            try:
                resp = self.session.get(
                    f"{_API}/search", params=params, auth=(self.api_key, ""), timeout=20
                )
            except Exception as e:
                log.error(f"Reed: {e}")
                break
            if resp.status_code == 401:
                log.error("Reed: 401 Unauthorized — check REED_API_KEY.")
                break
            if not resp.ok:
                log.error(f"Reed status {resp.status_code}")
                break

            data = resp.json()
            total = data.get("totalResults", 0) if total is None else total
            results = data.get("results", [])
            if not results:
                break

            for raw in results:
                job = self._process_job(raw)
                if job and self._within_cutoff(job, cutoff):
                    jobs.append(job)
                if len(jobs) >= wanted:
                    break
                time.sleep(0.25)

            skip += len(results)
            if total is not None and skip >= total:
                break

        return JobResponse(jobs=jobs[:wanted])

    @staticmethod
    def _within_cutoff(job: JobPost, cutoff) -> bool:
        if cutoff is None or job.date_posted is None:
            return True
        return job.date_posted >= cutoff

    def _process_job(self, raw: dict) -> JobPost | None:
        job_id = raw.get("jobId")
        if not job_id:
            return None

        detail = self._fetch_detail(job_id)
        description = (detail.get("jobDescription") if detail else None) or raw.get("jobDescription")
        if description and self.scraper_input.description_format == DescriptionFormat.MARKDOWN:
            description = markdown_converter(description)

        date_posted = None
        for src in (raw.get("date"), (detail or {}).get("datePosted")):
            if isinstance(src, str):
                for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                    try:
                        date_posted = datetime.strptime(src[:10], fmt).date()
                        break
                    except ValueError:
                        continue
            if date_posted:
                break

        return JobPost(
            id=f"rd-{job_id}",
            title=raw.get("jobTitle") or "N/A",
            company_name=raw.get("employerName"),
            location=Location(city=raw.get("locationName"), country=Country.UK),
            date_posted=date_posted,
            job_url=raw.get("jobUrl") or f"https://www.reed.co.uk/jobs/{job_id}",
            job_url_direct=(detail or {}).get("externalUrl"),
            description=description,
            job_type=self._job_type(detail or {}),
            compensation=self._salary(raw),
            is_remote=self._is_remote(raw.get("jobTitle"), description),
        )

    def _fetch_detail(self, job_id) -> dict | None:
        try:
            resp = self.session.get(
                f"{_API}/jobs/{job_id}", auth=(self.api_key, ""), timeout=20
            )
            if resp.ok:
                return resp.json()
        except Exception as e:
            log.error(f"Reed detail {job_id}: {e}")
        return None

    @staticmethod
    def _job_type(detail: dict):
        if detail.get("fullTime"):
            return [JobType.FULL_TIME]
        if detail.get("partTime"):
            return [JobType.PART_TIME]
        ct = (detail.get("contractType") or "").lower()
        if "contract" in ct:
            return [JobType.CONTRACT]
        if "temp" in ct:
            return [JobType.TEMPORARY]
        return None

    @staticmethod
    def _salary(raw: dict) -> Compensation | None:
        mn, mx = raw.get("minimumSalary"), raw.get("maximumSalary")
        if not mn and not mx:
            return None
        try:
            return Compensation(
                interval=CompensationInterval.YEARLY,
                min_amount=float(mn) if mn else None,
                max_amount=float(mx) if mx else None,
                currency=raw.get("currency") or "GBP",
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_remote(title: str | None, description: str | None) -> bool:
        blob = f"{title or ''} {description or ''}".lower()
        return any(k in blob for k in ("remote", "work from home", "wfh", "hybrid"))
