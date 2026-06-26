"""OpenAI-based job matcher returning structured {is_match, score, reason}."""
from __future__ import annotations

import logging
import time

import openai
from openai import OpenAI
from pydantic import BaseModel, Field

from app.config import DESCRIPTION_CHAR_LIMIT, OPENAI_API_KEY

log = logging.getLogger("jobhunter.matcher")


class MatchResult(BaseModel):
    is_match: bool = Field(description="True only if the job genuinely fits the preferences")
    score: int = Field(description="0-100 relevance score (100 = perfect fit)")
    reason: str = Field(description="One concise sentence explaining the decision")


_SYSTEM_TEMPLATE = (
    "You are a job-matching assistant helping a job seeker filter postings.\n"
    "Given the seeker's preferences and a single job posting, decide whether it is "
    "a good match. Be decisive: only set is_match=true when it genuinely fits.\n\n"
    "The seeker's preferences:\n{prompt}"
)

_TRANSIENT = (
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.InternalServerError,
)


class Matcher:
    def __init__(self, model: str, prompt: str):
        if not OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to the .env file at the repo root."
            )
        self.client = OpenAI(api_key=OPENAI_API_KEY)
        self.model = model or "gpt-4o-mini"
        self.system = _SYSTEM_TEMPLATE.format(prompt=(prompt or "(no preferences given)"))

    def _user_content(self, job) -> str:
        desc = (job.description or "")[:DESCRIPTION_CHAR_LIMIT]
        return (
            f"Title: {job.title}\n"
            f"Company: {job.company or 'N/A'}\n"
            f"Location: {job.location or 'N/A'}\n"
            f"Remote: {job.is_remote}\n\n"
            f"Description:\n{desc or '(no description available)'}"
        )

    def match(self, job, max_retries: int = 4) -> MatchResult:
        messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self._user_content(job)},
        ]
        delay = 2.0
        for attempt in range(max_retries):
            try:
                completion = self.client.chat.completions.parse(
                    model=self.model,
                    messages=messages,
                    response_format=MatchResult,
                    temperature=0,
                )
                parsed = completion.choices[0].message.parsed
                if parsed is None:
                    raise ValueError("model returned no parsed result")
                parsed.score = max(0, min(100, int(parsed.score)))
                return parsed
            except _TRANSIENT as exc:
                if attempt == max_retries - 1:
                    raise
                log.warning("OpenAI transient error: %s — retrying in %.0fs", exc, delay)
                time.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable")  # pragma: no cover

    def check(self) -> None:
        """Lightweight connectivity/credential check (one tiny request)."""
        self.client.models.retrieve(self.model)


class SuggestedTerms(BaseModel):
    terms: list[str] = Field(default_factory=list, description="Broad job-board search queries")


_SUGGEST_SYSTEM = (
    "You generate job-board search queries for Indeed and LinkedIn.\n"
    "Given a job seeker's preferences, output a short list of BROAD keyword queries "
    "(job titles / role keywords) that will surface relevant postings.\n"
    "Rules:\n"
    "- Focus on the role/title and core skills (e.g. 'python developer', 'backend engineer').\n"
    "- Keep each query short (1-4 words).\n"
    "- Do NOT encode filters like 'remote', seniority, or location — those are handled separately.\n"
    "- Prefer broad over narrow so good jobs are not missed.\n"
    "- Return at most {max_terms} distinct queries."
)


def suggest_search_terms(model: str, prompt: str, max_terms: int = 6) -> list[str]:
    """Use the LLM to expand a free-text preferences prompt into search queries."""
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to the .env file at the repo root."
        )
    client = OpenAI(api_key=OPENAI_API_KEY)
    completion = client.chat.completions.parse(
        model=model or "gpt-4o-mini",
        messages=[
            {"role": "system", "content": _SUGGEST_SYSTEM.format(max_terms=max_terms)},
            {"role": "user", "content": prompt},
        ],
        response_format=SuggestedTerms,
        temperature=0.3,
    )
    parsed = completion.choices[0].message.parsed
    raw = parsed.terms if parsed else []
    seen, out = set(), []
    for term in raw:
        cleaned = (term or "").strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out[:max_terms]
