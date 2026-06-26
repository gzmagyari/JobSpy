"""Job embeddings: batched OpenAI embeddings, cached in SQLite, in-memory cosine search.

Used by the chat agent's search tool. Embeddings are computed once per job
(immutable), cached in the job_embeddings table, and searched with numpy cosine
similarity — fast for the few hundred/thousand jobs we hold.
"""
from __future__ import annotations

import logging

import numpy as np
from openai import OpenAI
from sqlmodel import Session, select

from app.config import OPENAI_API_KEY
from app.db import engine
from app.models import Job, JobEmbedding

log = logging.getLogger("jobhunter.embeddings")

MODEL = "text-embedding-3-small"
EMBED_CHAR_LIMIT = 8000
_BATCH = 128

# Module-level cache of the (ids, normalized matrix); rebuilt when row count changes.
_cache: dict = {"count": -1, "ids": None, "matrix": None}


def _client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set (see .env).")
    return OpenAI(api_key=OPENAI_API_KEY)


def _job_text(job: Job) -> str:
    head = " | ".join(p for p in (job.title, job.company, job.location) if p)
    desc = (job.description or "")[:EMBED_CHAR_LIMIT]
    return f"{head}\n{desc}".strip() or (job.id or "job")


def embed_missing(batch_size: int = _BATCH) -> int:
    """Embed any jobs that don't yet have a cached vector. Returns count embedded."""
    with Session(engine) as session:
        done = set(session.exec(select(JobEmbedding.job_id)).all())
        jobs = [j for j in session.exec(select(Job)).all() if j.id not in done]
    if not jobs:
        return 0

    client = _client()
    embedded = 0
    for i in range(0, len(jobs), batch_size):
        batch = jobs[i : i + batch_size]
        resp = client.embeddings.create(model=MODEL, input=[_job_text(j) for j in batch])
        with Session(engine) as session:
            for job, item in zip(batch, resp.data):
                session.merge(
                    JobEmbedding(job_id=job.id, vector=list(item.embedding), model=MODEL)
                )
            session.commit()
        embedded += len(batch)
        log.info("embedded %d/%d jobs", min(i + batch_size, len(jobs)), len(jobs))
    return embedded


def _load() -> tuple[list[str], np.ndarray]:
    with Session(engine) as session:
        rows = session.exec(select(JobEmbedding)).all()
    if _cache["count"] == len(rows) and _cache["matrix"] is not None:
        return _cache["ids"], _cache["matrix"]
    ids = [r.job_id for r in rows]
    if rows:
        matrix = np.array([r.vector for r in rows], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        matrix = matrix / norms
    else:
        matrix = np.zeros((0, 1), dtype=np.float32)
    _cache.update(count=len(rows), ids=ids, matrix=matrix)
    return ids, matrix


def search(
    query: str,
    top_k: int = 8,
    status: str | None = None,
    site: str | None = None,
    min_score: int | None = None,
    remote_only: bool = False,
) -> list[tuple[Job, float]]:
    """Semantic search over cached job embeddings. Returns (Job, similarity) pairs."""
    embed_missing()  # lazy fill — cheap no-op when nothing is missing
    ids, matrix = _load()
    if not ids:
        return []

    qv = _client().embeddings.create(model=MODEL, input=[query]).data[0].embedding
    q = np.array(qv, dtype=np.float32)
    q /= np.linalg.norm(q) or 1.0
    sims = matrix @ q
    order = np.argsort(-sims)

    with Session(engine) as session:
        job_map = {j.id: j for j in session.exec(select(Job)).all()}

    results: list[tuple[Job, float]] = []
    for idx in order:
        job = job_map.get(ids[idx])
        if job is None:
            continue
        if status and status != "all" and job.match_status != status:
            continue
        if site and job.site != site:
            continue
        if min_score is not None and (job.match_score or 0) < min_score:
            continue
        if remote_only and not job.is_remote:
            continue
        results.append((job, float(sims[idx])))
        if len(results) >= top_k:
            break
    return results
