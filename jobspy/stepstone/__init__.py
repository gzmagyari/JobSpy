"""Scraper for the Stepstone-platform UK boards: Totaljobs, CWjobs, Jobsite.

All three share one site engine: a search page at /jobs/<keyword>/in-<location>
that server-renders ~25 job links per page, and detail pages that expose a
schema.org JSON-LD JobPosting (title, company, location, date, full description).
"""
from __future__ import annotations

import json
import math
import random
import re
import time
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from jobspy.model import (
    Compensation,
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
from jobspy.stepstone.constant import headers
from jobspy.util import (
    create_logger,
    create_session,
    extract_emails_from_text,
    markdown_converter,
)

# Locations that mean "anywhere in the UK" — drop the /in-<loc> path segment.
_UK_WIDE = {"", "uk", "united-kingdom", "great-britain", "england", "gb"}

_EMPLOYMENT_TYPE = {
    "FULL_TIME": JobType.FULL_TIME,
    "PART_TIME": JobType.PART_TIME,
    "CONTRACTOR": JobType.CONTRACT,
    "CONTRACT": JobType.CONTRACT,
    "TEMPORARY": JobType.TEMPORARY,
    "INTERN": JobType.INTERNSHIP,
    "OTHER": JobType.OTHER,
}


def _slug(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


class StepstoneScraper(Scraper):
    """Base engine; subclasses set DOMAIN / SITE / ID_PREFIX / LABEL."""

    DOMAIN: str = ""
    SITE: Site | None = None
    ID_PREFIX: str = ""
    LABEL: str = "Stepstone"
    jobs_per_page = 25
    delay = 1
    band_delay = 2

    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(self.SITE, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)
        self.log = create_logger(self.LABEL)
        # has_retry=False: detail pages throttle under rapid access; we'd rather
        # fail fast and skip a job than burn ~75s in urllib3 retry/backoff.
        self.session = create_session(
            proxies=proxies, ca_cert=ca_cert, is_tls=False, has_retry=False
        )
        self.session.headers.update(headers)
        if user_agent:
            self.session.headers["user-agent"] = user_agent
        self.scraper_input: ScraperInput | None = None

    # -- main loop ----------------------------------------------------------
    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        self.scraper_input = scraper_input
        keyword = _slug(scraper_input.search_term) or "jobs"
        loc_slug = _slug(scraper_input.location)
        path = f"/jobs/{keyword}"
        if loc_slug and loc_slug not in _UK_WIDE:
            path += f"/in-{loc_slug}"

        cutoff = None
        if scraper_input.hours_old:
            cutoff = (datetime.now() - timedelta(hours=scraper_input.hours_old)).date()

        wanted = scraper_input.results_wanted
        max_pages = min(20, math.ceil(wanted / self.jobs_per_page) + 2)
        seen: set[str] = set()
        jobs: list[JobPost] = []

        for page in range(1, max_pages + 1):
            if len(jobs) >= wanted:
                break
            url = f"https://{self.DOMAIN}{path}?page={page}"
            self.log.info(f"search page: {page} / {max_pages}")
            try:
                resp = self.session.get(url, timeout=20)
            except Exception as e:
                self.log.error(f"{self.LABEL}: {e}")
                break
            if resp.status_code not in range(200, 400):
                self.log.error(f"{self.LABEL} status {resp.status_code}")
                break

            page_links = self._extract_job_links(resp.text)
            new_links = [u for u in page_links if u not in seen]
            if not new_links:
                break  # ran out of results

            for job_url in new_links:
                seen.add(job_url)
                try:
                    job = self._process_job(job_url)
                except Exception as e:
                    self.log.error(f"failed to parse {job_url}: {e}")
                    job = None
                if job and self._within_cutoff(job, cutoff):
                    jobs.append(job)
                if len(jobs) >= wanted:
                    break
                time.sleep(random.uniform(self.delay, self.delay + self.band_delay))

        return JobResponse(jobs=jobs[:wanted])

    @staticmethod
    def _within_cutoff(job: JobPost, cutoff) -> bool:
        if cutoff is None or job.date_posted is None:
            return True
        return job.date_posted >= cutoff

    def _extract_job_links(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        ordered: list[str] = []
        for a in soup.find_all("a", href=True):
            href = str(a["href"])
            if re.match(r"^(https?://[^/]+)?/job/", href):
                full = href if href.startswith("http") else f"https://{self.DOMAIN}{href}"
                full = full.split("?")[0]
                if full not in ordered:
                    ordered.append(full)
        return ordered

    # -- detail page --------------------------------------------------------
    def _process_job(self, job_url: str) -> JobPost | None:
        resp = self.session.get(job_url, timeout=15)
        if resp.status_code not in range(200, 400):
            return None
        node = self._find_jobposting(resp.text)
        if not node:
            return None

        title = (node.get("title") or "").strip() or "N/A"
        org = node.get("hiringOrganization") or {}
        company = org.get("name")
        company_logo = org.get("logo")

        description = node.get("description") or None
        if description and self.scraper_input.description_format == DescriptionFormat.MARKDOWN:
            description = markdown_converter(description)

        date_posted = None
        dp = node.get("datePosted")
        if isinstance(dp, str) and len(dp) >= 10:
            try:
                date_posted = datetime.strptime(dp[:10], "%Y-%m-%d").date()
            except ValueError:
                date_posted = None

        job_type = None
        et = node.get("employmentType")
        if isinstance(et, str) and et.upper() in _EMPLOYMENT_TYPE:
            job_type = [_EMPLOYMENT_TYPE[et.upper()]]

        match = re.search(r"job(\d+)", job_url)
        job_id = f"{self.ID_PREFIX}-{match.group(1)}" if match else f"{self.ID_PREFIX}-{abs(hash(job_url))}"

        return JobPost(
            id=job_id,
            title=title,
            company_name=company,
            location=self._parse_location(node.get("jobLocation")),
            date_posted=date_posted,
            job_url=node.get("url") or job_url,
            description=description,
            job_type=job_type,
            compensation=self._parse_salary(node.get("baseSalary")),
            company_logo=company_logo,
            is_remote=self._is_remote(title, description),
            emails=extract_emails_from_text(description) if description else None,
        )

    @staticmethod
    def _find_jobposting(html: str) -> dict | None:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            for candidate in data if isinstance(data, list) else [data]:
                if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                    return candidate
        return None

    def _parse_location(self, job_location) -> Location:
        place = None
        if isinstance(job_location, list) and job_location:
            place = job_location[0]
        elif isinstance(job_location, dict):
            place = job_location
        addr = (place or {}).get("address") or {}
        return Location(
            city=addr.get("addressLocality"),
            state=addr.get("addressRegion"),
            country=Country.UK,
        )

    @staticmethod
    def _parse_salary(base_salary) -> Compensation | None:
        if not isinstance(base_salary, dict):
            return None
        value = base_salary.get("value") or {}
        if not isinstance(value, dict):
            return None
        mn, mx = value.get("minValue"), value.get("maxValue")
        if mn is None and mx is None:
            return None
        try:
            return Compensation(
                min_amount=float(mn) if mn is not None else None,
                max_amount=float(mx) if mx is not None else None,
                currency=base_salary.get("currency", "GBP"),
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_remote(title: str | None, description: str | None) -> bool:
        blob = f"{title or ''} {description or ''}".lower()
        return any(k in blob for k in ("remote", "work from home", "wfh", "hybrid"))


class TotalJobs(StepstoneScraper):
    DOMAIN = "www.totaljobs.com"
    SITE = Site.TOTALJOBS
    ID_PREFIX = "tj"
    LABEL = "TotalJobs"


# NOTE: cwjobs.co.uk and jobsite.co.uk are the same Stepstone platform — their
# search results link to www.totaljobs.com detail pages (the same job pool).
# Scraping them would just duplicate Totaljobs results, so they are intentionally
# not implemented; Totaljobs already covers that pool.
