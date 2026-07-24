"""
ai.py
-----
Single module for all LLM calls, so the model/provider is easy to swap.

Provider: Google Gemini (free tier via Google AI Studio).
Setup:
    pip install google-genai
    Get a free key at https://aistudio.google.com/apikey
    Put it in .env as GOOGLE_API_KEY=...
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, Iterator, List

from dotenv import load_dotenv
from google import genai

load_dotenv()

MODEL_NAME = "gemini-flash-lite-latest"

_api_key = os.getenv("GOOGLE_API_KEY")
_client = genai.Client(api_key=_api_key) if _api_key else None


def is_configured() -> bool:
    return _client is not None


def generate(prompt: str, system: str | None = None) -> str:
    """Send a prompt to Gemini and return the text response.

    Returns a clear error string instead of raising, so the UI can display
    it inline rather than crashing the demo.
    """
    if not is_configured():
        return "[AI not configured: set GOOGLE_API_KEY in .env]"

    try:
        config = {"system_instruction": system} if system else None
        response = _client.models.generate_content(
            model=MODEL_NAME, contents=prompt, config=config
        )
        return (response.text or "").strip()
    except Exception as exc:  # noqa: BLE001 - surface any provider error to the UI
        return f"[AI error: {exc}]"


def _strip_json_fence(text: str) -> str:
    """Gemini sometimes wraps JSON in ```json ... ``` even when told not to."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    return match.group(1) if match else text


_VALID_VERDICTS = {"Strong fit", "Possible fit", "Stretch", "Off-target"}


def _verdict_from_score(score: int) -> str:
    if score >= 80:
        return "Strong fit"
    if score >= 55:
        return "Possible fit"
    if score >= 30:
        return "Stretch"
    return "Off-target"


def _fallback_match(job: Dict) -> Dict:
    """Used when the LLM call fails or returns unparseable JSON, so a job
    card always has something to render instead of crashing the page."""
    score = round(job.get("match_score", job.get("raw_score", 0)) or 0)
    score = max(0, min(100, int(score)))
    return {
        "adjusted_score": score,
        "reason": "AI reasoning unavailable for this job; showing the keyword-based match instead.",
        "matched_skills": [],
        "missing_skills": [],
        "verdict": _verdict_from_score(score),
    }


ANALYZE_MATCH_SYSTEM = """You are a sharp, honest technical recruiter. You judge how well a \
candidate actually fits a specific job - not how many keywords overlap. An adjacent-field \
role (e.g. a web development job for a candidate who wants AI/ML work) must score lower even \
if some skills overlap, because the ROLE ITSELF is a poor fit. A role well above or below the \
candidate's experience level (e.g. a senior/staff role for a fresher, or a wildly junior role \
for a senior candidate) must also score lower, regardless of skill overlap. Reward genuine \
role relevance, not keyword density.

Respond with ONLY valid JSON matching this exact schema, no prose, no markdown fences:
{
  "adjusted_score": <int 0-100, true role fit>,
  "reason": "<one concrete sentence naming a real strength AND a real gap>",
  "matched_skills": ["<skill candidate has that the job wants>", ...],
  "missing_skills": ["<skill the job wants that the candidate lacks>", ...],
  "verdict": "<one of: Strong fit, Possible fit, Stretch, Off-target>"
}"""


def analyze_match(candidate_profile: str, job: Dict) -> Dict:
    """One Gemini call per job: true role-fit score + a concrete skill gap.

    Never raises - on any failure (LLM error, bad JSON, missing keys) this
    falls back to the job's existing cosine match_score with empty skill
    lists, so a bad LLM response never crashes the job list.
    """
    prompt = (
        f"CANDIDATE PROFILE (CV text + detected experience level):\n{candidate_profile}\n\n"
        f"JOB:\nTitle: {job.get('title', '')}\n"
        f"Description: {job.get('description', '')}\n"
    )

    raw = generate(prompt, system=ANALYZE_MATCH_SYSTEM)

    try:
        data = json.loads(_strip_json_fence(raw))
        score = int(data["adjusted_score"])
        score = max(0, min(100, score))
        verdict = data.get("verdict") if data.get("verdict") in _VALID_VERDICTS else _verdict_from_score(score)
        return {
            "adjusted_score": score,
            "reason": str(data.get("reason") or "").strip(),
            "matched_skills": [str(s) for s in (data.get("matched_skills") or [])],
            "missing_skills": [str(s) for s in (data.get("missing_skills") or [])],
            "verdict": verdict,
        }
    except Exception:  # noqa: BLE001 - any parse/shape failure -> safe fallback
        return _fallback_match(job)


COVER_LETTER_SYSTEM = """You are a sharp, honest career writer. Write a complete, ready-to-send \
cover letter, formatted like a real person would send it:

1. Start with the candidate's name, then any contact details actually present in the candidate \
   profile (email, phone, LinkedIn/GitHub) - one per line. Only include details you can \
   actually find in the profile; never invent a placeholder like "[Your Email]".
2. A blank line, then a greeting: "Dear Hiring Manager," unless a specific company name is \
   given, in which case "Dear <Company> Team,".
3. 2-3 short body paragraphs - concise and specific, no generic filler like "I am excited to \
   apply" without backing it up with a concrete detail from the candidate's actual background. \
   Ground every claim in something from the candidate profile.
4. A closing: "Sincerely," (or "Best regards,") on its own line, followed by the candidate's \
   name on the next line.

Output plain text only, no markdown, no subject line, no placeholder brackets."""


def write_cover_letter(candidate_profile: str, job: Dict) -> Iterator[str]:
    """Yields cover-letter text chunks as they stream from Gemini.

    Isolated from analyze_match: a failure here only affects the cover
    letter panel, never the job list itself. Yields a bracketed error
    string instead of raising if the call isn't configured or fails.
    """
    if not is_configured():
        yield "[AI not configured: set GOOGLE_API_KEY in .env]"
        return

    prompt = (
        f"CANDIDATE PROFILE:\n{candidate_profile}\n\n"
        f"JOB:\nTitle: {job.get('title', '')}\n"
        f"Company: {job.get('company', '')}\n"
        f"Description: {job.get('description', '')}\n\n"
        "Write a cover letter for this candidate applying to this job."
    )

    try:
        stream = _client.models.generate_content_stream(
            model=MODEL_NAME,
            contents=prompt,
            config={"system_instruction": COVER_LETTER_SYSTEM},
        )
        for chunk in stream:
            if chunk.text:
                yield chunk.text
    except Exception as exc:  # noqa: BLE001 - surface inline, never raise
        yield f"\n\n[AI error: {exc}]"


REPO_SUMMARY_SYSTEM = """You are a technical recruiter reviewing one specific GitHub project, \
based only on the description and README given - no guessing beyond what's shown.

Respond with ONLY valid JSON matching this exact schema, no prose, no markdown fences:
{
  "summary": "<1-2 concrete sentences on what this project actually demonstrates - the real \
tech stack and what was built. If there's genuinely not enough information, say so briefly here \
instead of guessing.>",
  "skills": ["<specific technology/language/skill actually evidenced by this repo>", ...]
}
Keep skills specific and concrete (e.g. "PyTorch", "REST APIs", "Docker"), never vague \
(e.g. "programming", "software development"). Empty list if nothing concrete is evidenced."""


def summarize_repo(repo: Dict) -> Dict:
    """One Gemini call per repo: what this specific project demonstrates.

    repo: {"name", "description", "language", "stars", "readme"} dict.
    Returns {"summary": str, "skills": [str, ...]}, both empty if there's
    nothing to summarize or the call/parse fails - one bad repo never breaks
    the analysis of the others.
    """
    empty = {"summary": "", "skills": []}
    if not repo or not is_configured():
        return empty

    readme_snippet = (repo.get("readme") or "")[:2000]
    prompt = (
        f"Repo: {repo.get('name', '')}\n"
        f"Language: {repo.get('language') or 'unknown'}\n"
        f"Stars: {repo.get('stars', 0)}\n"
        f"Description: {repo.get('description') or 'none'}\n"
        + (f"README excerpt:\n{readme_snippet}" if readme_snippet else "")
    )
    raw = generate(prompt, system=REPO_SUMMARY_SYSTEM)

    try:
        data = json.loads(_strip_json_fence(raw))
        return {
            "summary": str(data.get("summary") or "").strip(),
            "skills": [str(s).strip() for s in (data.get("skills") or []) if str(s).strip()],
        }
    except Exception:  # noqa: BLE001 - any parse/shape failure -> safe empty result
        return empty


CV_SKILLS_SYSTEM = """You are a technical recruiter extracting a candidate's skills from their \
CV/resume text. Respond with ONLY valid JSON, no prose, no markdown fences:
{
  "skills": ["<specific skill/technology/language/tool actually mentioned or clearly evidenced \
in the CV>", ...]
}
Keep skills specific and concrete (e.g. "Python", "AWS", "Docker", "Machine Learning"), never \
vague (e.g. "programming", "technical skills"). Don't invent anything not evidenced in the text."""


def extract_cv_skills(cv_text: str) -> List[str]:
    """One Gemini call: pull a concrete skills list out of raw CV text.

    Returns [] if there's nothing to extract or the call/parse fails, so a
    bad CV or a down API never blocks the rest of the profile from working.
    """
    if not cv_text or not is_configured():
        return []

    raw = generate(cv_text[:6000], system=CV_SKILLS_SYSTEM)
    try:
        data = json.loads(_strip_json_fence(raw))
        return [str(s).strip() for s in (data.get("skills") or []) if str(s).strip()]
    except Exception:  # noqa: BLE001 - any parse/shape failure -> safe empty result
        return []
