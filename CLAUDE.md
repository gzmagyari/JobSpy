# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

JobSpy (`python-jobspy` on PyPI) is a Python library that scrapes job postings from
LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter, Bayt, Naukri, and BDJobs concurrently
and aggregates them into a single pandas DataFrame. There is one public entry point:
`scrape_jobs()` in [jobspy/__init__.py](jobspy/__init__.py). The library has no CLI and no
server — it is imported and called.

This repo also contains a **Job Matcher dashboard** in [app/](app/) built on top of the library
(FastAPI + SQLite + OpenAI + a Vue 3 dashboard). It is separate from the upstream library and
documented in [app/README.md](app/README.md). Run it with `bash run.sh` (serves on
http://localhost:8077). Pipeline: scrape Indeed+LinkedIn (UK) → store new jobs in SQLite as
`pending` → LLM matches each (`{is_match, score, reason}`) → dashboard shows matches newest-first.
A daily APScheduler job re-runs it. The OpenAI key lives in a gitignored `.env` at the repo root.
App deps are in [requirements-app.txt](requirements-app.txt); the dev environment is a WSL venv
(`.venv`, Python 3.12) — Pyright "could not resolve app.*" warnings on Windows are false positives
since `app` resolves at runtime from the repo root.

## Commands

This is a Poetry project (requires Python >= 3.10). There is **no test suite** and no lint
config beyond Black.

```bash
poetry install                  # install deps into the poetry venv
poetry build                    # build the sdist/wheel (what CI publishes to PyPI)
poetry run black .              # format (line-length 88, enforced by pre-commit)
pre-commit run --all-files      # run the Black pre-commit hook
```

Quick manual smoke test (the library's only form of "running"):

```bash
poetry run python -c "from jobspy import scrape_jobs; print(scrape_jobs(site_name=['indeed'], search_term='engineer', results_wanted=5))"
```

Indeed is the most reliable board for ad-hoc testing (no rate limiting); LinkedIn rate-limits
aggressively and usually needs proxies.

Publishing is automated: pushing a tag (or manual `workflow_dispatch`) to `main` triggers
[.github/workflows/publish-to-pypi.yml](.github/workflows/publish-to-pypi.yml). Bump the
version in [pyproject.toml](pyproject.toml) before tagging.

## Architecture

### The aggregation pipeline (`scrape_jobs`)

[jobspy/__init__.py](jobspy/__init__.py) is the orchestrator. It:
1. Resolves `site_name` (strings/enums/list) to `Site` enum values and builds a single
   `ScraperInput` shared by all scrapers.
2. Runs every selected scraper **concurrently in a `ThreadPoolExecutor`**, one thread per site.
3. Flattens each `JobPost` into a flat dict, normalizing nested models — `location` becomes a
   display string, `compensation` is split into `interval`/`min_amount`/`max_amount`/`currency`
   columns, list fields (`job_type`, `emails`, `skills`) are joined to strings.
4. For USA searches with no direct salary data, parses salary from the description via
   `extract_salary` and tags `salary_source` as `description` vs `direct_data`.
5. Concatenates per-job DataFrames and reorders columns to match `desired_order` in
   [jobspy/util.py](jobspy/util.py) — **this list is the canonical output column set; add new
   output columns there or they will be dropped.**

### Per-site scraper packages

Each board lives in `jobspy/<site>/` with a consistent three-file layout:
- `__init__.py` — the `Scraper` subclass (the only required file).
- `constant.py` — static HTTP headers, GraphQL query templates, cookie payloads.
- `util.py` — parsing helpers (job-type mapping, remote detection, compensation parsing).

All scrapers subclass the `Scraper` ABC in [jobspy/model.py](jobspy/model.py) and implement
`scrape(self, scraper_input: ScraperInput) -> JobResponse`. Each constructor takes
`proxies`, `ca_cert`, and `user_agent`.

Scraping strategies differ per board — there is no shared HTML-parsing layer:
- **Indeed** — GraphQL API at `apis.indeed.com/graphql` (query template in `constant.py`); the
  cleanest source, returns the richest company metadata.
- **LinkedIn** — HTML scraping of the guest `seeMoreJobPostings` endpoint via BeautifulSoup;
  optional second request per job for full description (`linkedin_fetch_description`).
- **Google** — hits the `async/callback` endpoint and parses jobs out of embedded JSON arrays
  by positional index; requires a very specific `google_search_term`.
- **ZipRecruiter** — JSON API plus an initial cookie-priming request.

### Shared infrastructure ([jobspy/util.py](jobspy/util.py))

- `create_session(...)` is the single factory for HTTP sessions. It returns one of two
  proxy-rotating session types: `TLSRotating` (built on `tls_client`, for TLS fingerprint
  evasion, `is_tls=True`) or `RequestsRotating` (plain `requests`, supports retry/backoff and
  cookie clearing). Pick per scraper — e.g. LinkedIn/Indeed/Google use `is_tls=False`,
  ZipRecruiter uses TLS. Both round-robin through the `proxies` list; `"localhost"` means
  "no proxy for this request".
- `extract_salary` parses min/max/interval/currency from free-text descriptions (regex-based,
  USA only). `convert_to_annual` normalizes intervals when `enforce_annual_salary=True`.
- `create_logger(name)` produces a `JobSpy:<name>` logger; `set_logger_level(verbose)` maps
  `verbose` 0/1/2 to ERROR/WARNING/INFO across all JobSpy loggers.

### Models and enums ([jobspy/model.py](jobspy/model.py))

All data shapes are Pydantic models / enums in one file: `JobPost` (the unified job record),
`JobResponse`, `Compensation`, `Location`, `ScraperInput`, plus the `Site`, `JobType`, and
`Country` enums and the `Scraper` ABC.

`Country` is the trickiest enum: each member's tuple value encodes the Indeed subdomain/API
code and the Glassdoor domain (e.g. `USA = ("usa,us,united states", "www:us", "com")`). The
`indeed_domain_value` / `glassdoor_domain_value` properties decode these. `Country.from_string`
matches against the comma-separated aliases in the first tuple element.

### Adding a new job board

1. Add a member to the `Site` enum in [jobspy/model.py](jobspy/model.py).
2. Create `jobspy/<site>/` with `__init__.py` (a `Scraper` subclass), `constant.py`, `util.py`.
3. Register the class in `SCRAPER_MAPPING` in [jobspy/__init__.py](jobspy/__init__.py).
4. Add an exception class to [jobspy/exception.py](jobspy/exception.py) following the existing
   pattern.
5. If the board returns new fields, add them to `JobPost` and to `desired_order` in
   [jobspy/util.py](jobspy/util.py).

## Conventions

- Every `JobPost.id` is prefixed with a two-letter site code: `li-` (LinkedIn), `in-` (Indeed),
  `go-` (Google), etc.
- `description_format` accepts `markdown` (default), `html`, or `plain`; conversion helpers live
  in `util.py`.
- Each board has mutually-exclusive search filters (documented in [README.md](README.md)) — e.g.
  Indeed accepts only one of `hours_old`, `job_type`+`is_remote`, or `easy_apply` per search.
- This repo is a fork of `cullenwatson/JobSpy`; the `origin` remote is `gzmagyari/JobSpy`.
