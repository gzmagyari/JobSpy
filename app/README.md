# Job Matcher Dashboard

A personal job-hunting tool built on top of the JobSpy library. It scrapes UK jobs from
**Indeed** and **LinkedIn**, asks an **OpenAI** model whether each job matches a prompt you
write, and shows the matches in a **Vue dashboard** — newest first, each card clickable through
to the original posting. A daily scheduler keeps it fresh.

## How it works

```
scrape (Indeed + LinkedIn)  ->  store new jobs as "pending" (SQLite)
        ->  LLM matches each pending job  ->  "matched" / "rejected" (+ score + reason)
        ->  dashboard shows matches
```

- **Stateless scraping, stateful matching.** JobSpy hands back full job records (description
  included) in one call. We dedup by JobSpy's stable id and store every job in SQLite. The DB
  doubles as the work-queue for the LLM step, so runs are resumable and we only ever pay to
  match *new* jobs.
- **One process.** FastAPI serves the API *and* the built Vue app, and hosts the APScheduler
  daily job. No Redis/Celery, no separate worker.

### Pieces

| File | Role |
|------|------|
| `config.py` | paths, `.env` (OpenAI key), default settings |
| `models.py` | SQLModel tables: `Job`, `Run`, `Setting` |
| `db.py` | SQLite engine + seeding |
| `scraper.py` | wraps `jobspy.scrape_jobs` → clean dicts |
| `matcher.py` | OpenAI structured matching → `{is_match, score, reason}` |
| `pipeline.py` | scrape → store → match; run-lock; CLI entry |
| `scheduler.py` | APScheduler daily run + manual trigger |
| `api.py` / `main.py` | FastAPI endpoints + frontend serving |
| `frontend/` | Vue 3 (Options API) + Vuex + vue-router, built with Vite |

## Setup

From the repo root, inside WSL:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e . -r requirements-app.txt
```

Put your key in a `.env` at the repo root (gitignored):

```
OPENAI_API_KEY=sk-...
```

## Run

```bash
bash run.sh
```

This builds the frontend on first run, then serves everything at **http://localhost:8077**.
(`run.sh` binds `127.0.0.1`; change to `0.0.0.0` in the script to reach it from other devices
on your LAN.)

### Frontend development (hot reload)

```bash
# terminal 1 — backend
PYTHONPATH=. .venv/bin/python -m uvicorn app.main:app --port 8077
# terminal 2 — Vite dev server (proxies /api to :8077)
cd app/frontend && npm run dev      # http://localhost:5173
```

After changing frontend code for real use, rebuild: `cd app/frontend && npm run build`.

### One-off run from the command line (no server)

```bash
PYTHONPATH=. .venv/bin/python -m app.pipeline
```

## Using the dashboard

- **Config page** — write your matching prompt (plain English), set search terms (one per
  line), boards, location, model, results-per-site, max age, and the daily schedule. **Save.**
- **Jobs page** — matched jobs newest-first. Click a card to open the posting; mark **Applied**
  or **Dismiss**. Filter by status/site, sort by date or score, search.
- **Run now** (top bar) — trigger a scrape+match immediately; the bar shows live progress.
- **Re-match stored jobs** (Config) — re-evaluate everything already in the DB with the current
  prompt (uses API credits; doesn't re-scrape).

## Daily schedule — keeping it running

The daily run fires only while `run.sh` (the server) is running. On an always-on machine, the
simplest options:

- Leave `run.sh` running in a WSL terminal, **or**
- **Windows Task Scheduler** → action: `wsl bash /mnt/c/xampp/htdocs/JobSpy/run.sh`, trigger:
  *At log on* (so it restarts with the machine). The in-app scheduler then handles the daily run.

To run the pipeline truly independently of the web server, point Task Scheduler at
`wsl bash -c "cd /mnt/c/xampp/htdocs/JobSpy && PYTHONPATH=. .venv/bin/python -m app.pipeline"`
on a daily trigger instead.

## Resetting

Delete `app/data/jobs.db` to wipe all stored jobs and settings; the app re-seeds defaults on
next start.

## Cost

Matching uses `gpt-4o-mini` by default — roughly a few cents per day for ~100 jobs. Change the
model on the Config page. Only new jobs are matched each run.
