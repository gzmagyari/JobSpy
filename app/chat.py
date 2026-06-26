"""Agentic chat over the scraped jobs: an OpenAI tool-calling loop.

The agent semantically searches the job DB (matched AND rejected, with scores and
reasons), and recommends jobs by emitting ```jobcard fences containing job ids,
which the frontend renders as clickable cards. It also sees the user's matching
prompt so its suggestions align with what they actually want.
"""
from __future__ import annotations

import json
import logging
import re

from openai import OpenAI
from sqlmodel import Session

from app.config import OPENAI_API_KEY
from app.db import engine
from app.embeddings import search as embedding_search
from app.models import Job, Setting

log = logging.getLogger("jobhunter.chat")

MAX_ROUNDS = 6

_SYSTEM_TEMPLATE = (
    "You are a helpful job-search assistant for a single user.\n"
    "You can search their scraped job listings — BOTH the jobs an earlier matcher "
    "recommended and the ones it rejected — each with a 0-100 match score and a reason.\n\n"
    "THE USER'S JOB PREFERENCES (what they are looking for):\n"
    '"""\n{preferences}\n"""\n\n'
    "Tools:\n"
    "- search_jobs — semantic search; your main way to find postings. Filter by "
    "status/site/score/remote when useful.\n"
    "- get_job_details — full description for one job id.\n\n"
    "SHOWING JOBS AS CARDS — IMPORTANT:\n"
    "When you recommend specific jobs, render each as a clickable card by emitting a "
    "fenced block tagged `jobcard` containing the job id(s) EXACTLY as returned by "
    "search_jobs (the `id` field), one id per line. Example:\n"
    "```jobcard\n"
    "rd-57047734\n"
    "li-4431492439\n"
    "```\n"
    "The app turns each id into a card showing the title, company, location, salary, "
    "score, reason, and a link to the live posting — so do NOT repeat those details in "
    "prose. Keep commentary brief (a short intro plus any nuance) and place the "
    "card block(s) where they belong in your answer.\n\n"
    "FORMATTING:\n"
    "Write your replies in **Markdown** and use it well — **bold** for key terms, bullet "
    "lists for multiple points, short paragraphs, and the occasional small heading — so "
    "answers are easy to scan. (But never list job postings as markdown text — those always "
    "go in the ```jobcard fence so they render as cards.)\n\n"
    "Be concise and concrete. Cite scores/reasons when relevant. If asked why a job was "
    "rejected, explain from its reason. Never invent jobs — only use ids the tools return."
)

_FENCE_RE = re.compile(r"```jobcard\s*\n([\s\S]*?)```", re.IGNORECASE)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_jobs",
            "description": "Semantic search over the user's scraped jobs (matched and rejected). Returns compact summaries incl. each job's `id`.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for, e.g. 'remote python backend'."},
                    "top_k": {"type": "integer", "description": "Max results (default 8, max 20)."},
                    "status": {
                        "type": "string",
                        "enum": ["matched", "rejected", "pending", "error", "all"],
                        "description": "Filter by match status.",
                    },
                    "site": {"type": "string", "description": "Filter by board, e.g. reed, indeed, linkedin, totaljobs."},
                    "min_score": {"type": "integer", "description": "Minimum match score 0-100."},
                    "remote_only": {"type": "boolean", "description": "Only remote jobs."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_job_details",
            "description": "Full description and details for a single job id.",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
        },
    },
]


def _system_prompt(preferences: str | None) -> str:
    return _SYSTEM_TEMPLATE.format(preferences=(preferences or "(no preferences set)").strip())


def _extract_card_ids(text: str) -> list[str]:
    ids: list[str] = []
    for block in _FENCE_RE.findall(text or ""):
        for line in block.splitlines():
            jid = line.strip().strip("`-• ").strip()
            if jid and jid not in ids:
                ids.append(jid)
    return ids


def _validate_ids(ids: list[str]) -> list[str]:
    if not ids:
        return []
    with Session(engine) as session:
        return [jid for jid in ids if session.get(Job, jid) is not None]


def _salary(job: Job) -> str | None:
    if not job.min_amount and not job.max_amount:
        return None
    cur = job.currency or ""
    fmt = lambda n: f"{int(n):,}" if n else ""
    if job.min_amount and job.max_amount:
        return f"{cur}{fmt(job.min_amount)}-{fmt(job.max_amount)}"
    return f"{cur}{fmt(job.min_amount or job.max_amount)}"


def _summary(job: Job, sim: float | None = None) -> dict:
    d = {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "site": job.site,
        "status": job.match_status,
        "score": job.match_score,
        "reason": job.match_reason,
        "remote": job.is_remote,
        "date_posted": str(job.date_posted) if job.date_posted else None,
        "salary": _salary(job),
        "snippet": (job.description or "")[:300],
    }
    if sim is not None:
        d["similarity"] = round(sim, 3)
    return d


def _run_tool(name: str, args: dict) -> dict:
    if name == "search_jobs":
        hits = embedding_search(
            query=str(args.get("query", "")),
            top_k=min(int(args.get("top_k", 8) or 8), 20),
            status=args.get("status"),
            site=args.get("site"),
            min_score=args.get("min_score"),
            remote_only=bool(args.get("remote_only", False)),
        )
        return {"count": len(hits), "results": [_summary(j, s) for j, s in hits]}

    if name == "get_job_details":
        with Session(engine) as session:
            job = session.get(Job, str(args.get("job_id", "")))
        if job is None:
            return {"error": "job not found"}
        d = _summary(job)
        d.update(description=job.description, job_url=job.job_url, job_url_direct=job.job_url_direct)
        return d

    return {"error": f"unknown tool {name}"}


def run_chat(messages: list[dict], model: str | None = None) -> dict:
    """Run the agent loop. Returns {'reply': str, 'job_ids': [str]}."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set (see .env).")

    with Session(engine) as session:
        cfg = session.get(Setting, 1)
    model = model or (cfg.chat_model if cfg else None) or "gpt-4.1"
    preferences = cfg.match_prompt if cfg else None

    convo: list[dict] = [{"role": "system", "content": _system_prompt(preferences)}]
    for m in messages[-20:]:  # cap history
        if m.get("role") in ("user", "assistant") and m.get("content"):
            convo.append({"role": m["role"], "content": m["content"]})

    client = OpenAI(api_key=OPENAI_API_KEY)
    last_text = ""

    for _ in range(MAX_ROUNDS):
        resp = client.chat.completions.create(
            model=model, messages=convo, tools=TOOLS, tool_choice="auto"
        )
        msg = resp.choices[0].message
        if msg.content:
            last_text = msg.content

        entry: dict = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        convo.append(entry)

        if not msg.tool_calls:
            reply = msg.content or ""
            return {"reply": reply, "job_ids": _validate_ids(_extract_card_ids(reply))}

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _run_tool(tc.function.name, args)
            convo.append(
                {"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, default=str)}
            )

    return {
        "reply": last_text or "(I couldn't finish that — try rephrasing.)",
        "job_ids": _validate_ids(_extract_card_ids(last_text)),
    }
