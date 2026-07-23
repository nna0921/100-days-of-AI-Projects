"""
matching.py
-----------
Embeds the candidate profile and job descriptions with sentence-transformers
and ranks jobs by cosine similarity to the profile.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Union

import numpy as np
import streamlit as st
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"


@st.cache_resource(show_spinner="Loading embedding model...")
def get_model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)


@st.cache_data(show_spinner=False)
def embed_texts(texts: tuple[str, ...]) -> np.ndarray:
    """Embed a tuple of texts. Tuple (not list) so it's hashable for caching."""
    model = get_model()
    return model.encode(list(texts), normalize_embeddings=True)


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


# Raw cosine similarity between a full profile and a job description almost
# always lands in a narrow 0.3-0.5 band, even for a great match - that's a
# property of the embedding space, not a sign of a weak match. The relative
# order is what's meaningful, so we min-max normalize the raw scores across
# the current result set into this friendlier band before display, purely
# so a recruiter reading "92% match" isn't misled by the compressed raw scale.
DISPLAY_MIN = 30
DISPLAY_MAX = 97


def _rescale_for_display(raw_scores: List[float]) -> List[int]:
    if not raw_scores:
        return []
    lo, hi = min(raw_scores), max(raw_scores)
    if hi - lo < 1e-6:
        # All jobs equally (dis)similar - nothing to spread, show one flat value.
        mid = round((DISPLAY_MIN + DISPLAY_MAX) / 2)
        return [mid] * len(raw_scores)
    return [
        round(DISPLAY_MIN + (s - lo) / (hi - lo) * (DISPLAY_MAX - DISPLAY_MIN))
        for s in raw_scores
    ]



# How much a candidate's own experience level (from their CV, see
# candidate_profile.detect_experience_level) shapes the ranking, not just
# filters it. A job whose seniority (job_fetcher._detect_job_seniority, same
# 0-4 scale) is far from the candidate's level gets its semantic score pulled
# down; an exact match is left untouched. Capped so a great semantic match
# never gets nuked entirely by a one-level seniority gap.
SENIORITY_WEIGHT = 0.3

# cv_experience.detect_experience() returns a string level ("entry" | "junior" |
# "mid" | "senior") on the same scale fetch_jobs(experience=...) filters by.
# job_fetcher._detect_job_seniority tags each job on a separate 0-4 int scale
# (it also has "principal/lead" above senior). This maps the former onto the
# latter so the two are comparable.
_LEVEL_STR_TO_INT = {"intern": 0, "entry": 1, "junior": 1, "mid": 2, "senior": 3}


def _seniority_alignment(candidate_level: int, job_seniority: int) -> float:
    """1.0 for an exact seniority match, decaying toward a floor as the gap grows."""
    diff = abs(job_seniority - candidate_level)
    return max(0.4, 1.0 - 0.2 * diff)


def rank_jobs(
    profile_text: str,
    jobs: List[Dict],
    candidate_level: Optional[Union[int, str]] = None,
) -> List[Dict]:
    """Score each job against the profile text and return jobs sorted by
    descending raw similarity, each annotated with:
        raw_score    - cosine similarity * 100, modulated by seniority
                       alignment when candidate_level is given (unrounded, 0-100)
        match_score  - display-rescaled % for the UI (see _rescale_for_display)

    candidate_level is the candidate's own experience level, detected from
    their CV - passing it makes "I'm a fresher" shape the ranking itself, on
    top of whatever hard experience-level filter was applied to the job list
    before it got here. Accepts either cv_experience's string level ("entry",
    "junior", "mid", "senior") or an already-converted 0-4 int.
    """
    if isinstance(candidate_level, str):
        candidate_level = _LEVEL_STR_TO_INT.get(candidate_level.lower())

    if not profile_text or not jobs:
        for job in jobs:
            job["raw_score"] = 0.0
            job["match_score"] = 0
        return jobs

    # Include the title alongside the description: some sources (e.g. JobSpy's
    # LinkedIn rows) come back with an empty description, and a bare "" embeds
    # near-identically for every job, collapsing them all to the same score.
    # The title alone still carries real signal even when the description doesn't.
    job_texts = tuple(f"{j.get('title') or ''}. {j.get('description') or ''}" for j in jobs)
    profile_emb = embed_texts((profile_text,))[0]
    job_embs = embed_texts(job_texts)

    scored = []
    for job, emb in zip(jobs, job_embs):
        sim = cosine_sim(profile_emb, emb)
        job = dict(job)
        raw = max(0.0, sim) * 100

        if candidate_level is not None and "seniority" in job:
            alignment = _seniority_alignment(candidate_level, job["seniority"])
            raw *= (1 - SENIORITY_WEIGHT) + SENIORITY_WEIGHT * alignment

        job["raw_score"] = raw
        scored.append(job)

    scored.sort(key=lambda j: j["raw_score"], reverse=True)

    display_scores = _rescale_for_display([j["raw_score"] for j in scored])
    for job, display_score in zip(scored, display_scores):
        job["match_score"] = display_score

    return scored
