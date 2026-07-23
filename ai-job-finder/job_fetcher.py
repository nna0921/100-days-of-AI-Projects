"""
job_fetcher.py
--------------
Job fetching layer for the AI Job Finder.

Primary source : JobSpy  -> scrapes Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google
Fallback source: Adzuna  -> official free API (needs free app_id + app_key)

Both sources are normalized into ONE clean list of `Job` dicts so the rest of the
app (matching, UI) never has to care where a job came from.

Setup
-----
    pip install python-jobspy requests

Optional (only for the Adzuna fallback):
    Get a free key at https://developer.adzuna.com/ and set:
        export ADZUNA_APP_ID=your_id
        export ADZUNA_APP_KEY=your_key

Usage
-----
    from job_fetcher import fetch_jobs

    jobs = fetch_jobs("machine learning engineer", "remote", results=20)
    for j in jobs:
        print(j["title"], "-", j["company"], "-", j["url"])
"""

from __future__ import annotations

import os
import re
import time
from typing import List, Dict, Optional

import requests

# JobSpy is optional at import time so the app still boots if it's not installed.
try:
    from jobspy import scrape_jobs  # type: ignore
    _HAS_JOBSPY = True
except Exception:  # pragma: no cover
    _HAS_JOBSPY = False


# ---------------------------------------------------------------------------
# Normalized job schema
# ---------------------------------------------------------------------------
# Every job in the app looks like this, no matter the source:
#
#   {
#       "title":       str,
#       "company":     str,
#       "location":    str,
#       "description": str,          # full text used for AI matching
#       "salary":      str | None,
#       "url":         str,          # apply / view link
#       "source":      str,          # "indeed", "linkedin", "adzuna", ...
#       "date_posted": str | None,
#   }
# ---------------------------------------------------------------------------


def _clean(text) -> str:
    """Coerce anything to a stripped string ('' for missing/NaN values)."""
    if text is None:
        return ""
    s = str(text).strip()
    return "" if s.lower() in {"nan", "none", "null"} else s


def _dedupe(jobs: List[Dict]) -> List[Dict]:
    """Drop duplicate postings (same title + company, case-insensitive)."""
    seen = set()
    out = []
    for j in jobs:
        key = (j["title"].lower(), j["company"].lower())
        if key not in seen:
            seen.add(key)
            out.append(j)
    return out


# ---------------------------------------------------------------------------
# Source 1: JobSpy (primary)
# ---------------------------------------------------------------------------
def fetch_from_jobspy(
    search: str,
    location: str,
    results: int = 20,
    sites: Optional[List[str]] = None,
    country: str = "USA",
    linkedin_descriptions: bool = False,
    is_remote: bool = False,
) -> List[Dict]:
    """
    Fetch jobs via JobSpy (Indeed + LinkedIn by default).

    LinkedIn returns rows WITHOUT descriptions by default, which makes them
    useless for semantic matching (they all score the same). Set
    `linkedin_descriptions=True` to fetch each LinkedIn description too — this
    gives far better match quality but is noticeably slower (one extra request
    per job) and raises the chance of a LinkedIn rate-limit. Trade-off: richer
    matching vs. speed/reliability. For matching quality, also embed the job
    TITLE alongside the description on the matching side.

    Returns [] on any failure so the caller can fall back to Adzuna.
    """
    if not _HAS_JOBSPY:
        return []

    sites = sites or ["indeed", "linkedin"]
    try:
        df = scrape_jobs(
            site_name=sites,
            search_term=search,
            location=location,
            results_wanted=results,
            country_indeed=country,   # JobSpy needs a country hint for Indeed
            hours_old=720,            # last 30 days
            linkedin_fetch_description=linkedin_descriptions,
            is_remote=is_remote,      # True -> JobSpy returns only remote roles
        )
    except Exception as exc:
        print(f"[job_fetcher] JobSpy failed: {exc}")
        return []

    if df is None or len(df) == 0:
        return []

    jobs = []
    for _, row in df.iterrows():
        jobs.append(
            {
                "title": _clean(row.get("title")),
                "company": _clean(row.get("company")),
                "location": _clean(row.get("location")) or location,
                "description": _clean(row.get("description")),
                "salary": _format_jobspy_salary(row),
                "url": _clean(row.get("job_url")),
                "source": _clean(row.get("site")) or "jobspy",
                "date_posted": _clean(row.get("date_posted")) or None,
            }
        )
    return [j for j in jobs if j["title"] and j["url"]]


def _format_jobspy_salary(row) -> Optional[str]:
    lo = row.get("min_amount")
    hi = row.get("max_amount")
    unit = _clean(row.get("interval")) or "year"
    try:
        if lo and hi:
            return f"${int(float(lo)):,} - ${int(float(hi)):,} / {unit}"
        if lo:
            return f"From ${int(float(lo)):,} / {unit}"
    except (ValueError, TypeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Source 2: Adzuna (fallback)
# ---------------------------------------------------------------------------
def fetch_from_adzuna(
    search: str,
    location: str,
    results: int = 20,
    country: str = "us",
    app_id: Optional[str] = None,
    app_key: Optional[str] = None,
) -> List[Dict]:
    """
    Fetch jobs from the Adzuna API. Free key required.

    Credentials come from args or the ADZUNA_APP_ID / ADZUNA_APP_KEY env vars.
    Returns [] if credentials are missing or the request fails.
    """
    app_id = app_id or os.getenv("ADZUNA_APP_ID")
    app_key = app_key or os.getenv("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        print("[job_fetcher] Adzuna skipped: no ADZUNA_APP_ID / ADZUNA_APP_KEY set.")
        return []

    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": min(results, 50),
        "what": search,
        "where": "" if location.lower() == "remote" else location,
        "content-type": "application/json",
    }
    if location.lower() == "remote":
        params["what"] = f"{search} remote"

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"[job_fetcher] Adzuna failed: {exc}")
        return []

    jobs = []
    for item in data.get("results", []):
        jobs.append(
            {
                "title": _clean(item.get("title")),
                "company": _clean((item.get("company") or {}).get("display_name")),
                "location": _clean((item.get("location") or {}).get("display_name")) or location,
                "description": _clean(item.get("description")),
                "salary": _format_adzuna_salary(item),
                "url": _clean(item.get("redirect_url")),
                "source": "adzuna",
                "date_posted": _clean(item.get("created")) or None,
            }
        )
    return [j for j in jobs if j["title"] and j["url"]]


def _format_adzuna_salary(item) -> Optional[str]:
    lo = item.get("salary_min")
    hi = item.get("salary_max")
    try:
        if lo and hi:
            return f"${int(lo):,} - ${int(hi):,} / year"
    except (ValueError, TypeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Experience-level filtering
# ---------------------------------------------------------------------------
# We rank a job's seniority on a 0-5 scale by scanning its title + description,
# then keep only jobs at or below the candidate's level (plus one step of
# tolerance, so a "fresher" still sees entry AND mid roles but not senior).
#
# Candidate levels the UI can pass:
#   "intern" | "entry" | "junior" | "mid" | "senior" | "any"
# ---------------------------------------------------------------------------

_CANDIDATE_LEVELS = {
    "intern": 0,
    "entry": 1,     # fresher / new grad / 0-1 yr
    "junior": 1,
    "mid": 2,       # 2-4 yr
    "senior": 3,    # 5+ yr
    "any": 99,      # no filtering
}


def _detect_job_seniority(title: str, description: str) -> int:
    """Guess a job's seniority (0=intern ... 4=principal/lead) from its text."""
    text = f"{title} {description}".lower()

    # highest signals first
    if re.search(r"\b(principal|staff|lead|director|head of|vp|chief)\b", text):
        return 4
    if re.search(r"\b(senior|sr\.?)\b", text) or re.search(r"\b(6|7|8|9|10|1[0-9])\+?\s*years?\b", text):
        return 3
    if re.search(r"\b(intern|internship)\b", text):
        return 0
    if re.search(r"\b(junior|jr\.?|entry[- ]level|graduate|new grad|fresher|0-1\s*year)\b", text):
        return 1
    return 2  # default: mid-level


def filter_by_experience(jobs: List[Dict], level: str, tolerance: int = 1) -> List[Dict]:
    """
    Keep jobs at or below the candidate's experience level (+tolerance steps).

    A "fresher" (entry, 1) with tolerance=1 keeps jobs up to seniority 2 (mid),
    dropping senior/lead/principal roles. Pass level="any" to disable filtering.
    Each kept job is annotated with a 'seniority' int for the UI if useful.
    """
    cand = _CANDIDATE_LEVELS.get(level.lower(), 99)
    if cand >= 99:
        for j in jobs:
            j["seniority"] = _detect_job_seniority(j["title"], j["description"])
        return jobs

    kept = []
    for j in jobs:
        s = _detect_job_seniority(j["title"], j["description"])
        j["seniority"] = s
        if s <= cand + tolerance:
            kept.append(j)
    return kept


# ---------------------------------------------------------------------------
# Work-arrangement filtering (onsite / hybrid / remote)
# ---------------------------------------------------------------------------
# "remote" is handled upstream by JobSpy's is_remote flag, so it isn't
# re-filtered here. "hybrid" and "onsite" have no native filter, so we infer
# them from the job text (title + location + description).
# ---------------------------------------------------------------------------
def filter_by_work_type(jobs: List[Dict], work_type: str) -> List[Dict]:
    wt = (work_type or "any").lower()
    if wt in {"any", "", "remote"}:
        return jobs

    out = []
    for j in jobs:
        blob = f"{j['title']} {j['location']} {j['description']}".lower()
        if wt == "hybrid" and "hybrid" in blob:
            out.append(j)
        elif wt == "onsite" and "remote" not in blob and "hybrid" not in blob:
            out.append(j)
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
# ISO code -> (JobSpy Indeed country name, Adzuna supports this code?)
# JobSpy needs a country NAME for Indeed; Adzuna uses the 2-letter code.
_COUNTRY_MAP = {
    "us": "USA", "gb": "UK", "uk": "UK", "in": "India", "ca": "Canada",
    "au": "Australia", "pk": "Pakistan", "ae": "UAE", "sg": "Singapore",
    "de": "Germany", "fr": "France", "nl": "Netherlands", "za": "South Africa",
    "ie": "Ireland", "nz": "New Zealand", "it": "Italy", "es": "Spain",
    "pl": "Poland", "br": "Brazil", "mx": "Mexico",
}
# Countries Adzuna actually serves (used to decide whether the fallback is viable)
_ADZUNA_COUNTRIES = {
    "us", "gb", "ca", "au", "in", "de", "fr", "nl", "za", "at",
    "br", "ch", "es", "it", "mx", "nz", "pl", "sg",
}

# Reverse lookup: full country NAME -> ISO code, so callers can pass either
# "pk" or "Pakistan" (handy when a single "Lahore, Pakistan" field is split).
_NAME_TO_ISO = {name.lower(): iso for iso, name in _COUNTRY_MAP.items()}
_NAME_TO_ISO.update({
    "usa": "us", "united states": "us", "america": "us",
    "united kingdom": "gb", "england": "gb", "britain": "gb",
    "uae": "ae", "united arab emirates": "ae",
})


def _normalize_country(value: str) -> str:
    """Accept an ISO code ('pk') OR a country name ('Pakistan') -> ISO code."""
    v = (value or "us").strip().lower()
    if v in _COUNTRY_MAP:          # already an ISO code we know
        return v
    if v in _NAME_TO_ISO:          # a country name
        return _NAME_TO_ISO[v]
    return v[:2] if len(v) >= 2 else "us"  # last-ditch guess


def split_location(text: str) -> tuple[str, str]:
    """
    Split a combined 'City, Country' string into (city, country_iso).

    Examples:
        "Lahore, Pakistan" -> ("Lahore", "pk")
        "Lahore"           -> ("Lahore", "us")   # country defaults; set it in UI
        "remote"           -> ("remote", "us")
    """
    parts = [p.strip() for p in (text or "").split(",") if p.strip()]
    if len(parts) >= 2:
        return parts[0], _normalize_country(parts[-1])
    return (parts[0] if parts else ""), "us"


def fetch_jobs(
    search: str,
    location: str,
    results: int = 20,
    country: str = "us",
    experience: str = "any",
    work_type: str = "any",
    prefer: str = "jobspy",
    linkedin_descriptions: bool = False,
) -> List[Dict]:
    """
    Fetch jobs from the best available source, routed to the right country and
    filtered to the candidate's experience level.

    IMPORTANT: `country` must match `location`. If the user searches "Lahore",
    pass country="pk" — otherwise Indeed defaults to the US and returns US jobs.

    Args:
        search     : job title / keywords, e.g. "data scientist"
        location   : city (+ region), or "remote"
        results    : max jobs to return
        country    : ISO code that matches the location ("us", "pk", "gb", "in"...)
        experience : "intern" | "entry" | "junior" | "mid" | "senior" | "any"
                     Filters out roles above the candidate's level.
        prefer     : "jobspy" or "adzuna" (which source to try first)

    Returns:
        List of normalized job dicts (see schema at top of file), each with an
        extra 'seniority' int.
    """
    country = _normalize_country(country)   # accepts "pk" OR "Pakistan"
    indeed_country = _COUNTRY_MAP.get(country, "USA")

    def _jobspy():
        return fetch_from_jobspy(
            search, location, results,
            country=indeed_country,
            linkedin_descriptions=linkedin_descriptions,
            is_remote=(work_type.lower() == "remote"),
        )

    def _adzuna():
        if country not in _ADZUNA_COUNTRIES:
            print(f"[job_fetcher] Adzuna has no coverage for '{country}'; skipping fallback.")
            return []
        return fetch_from_adzuna(search, location, results, country=country)

    order = [_jobspy, _adzuna] if prefer == "jobspy" else [_adzuna, _jobspy]

    jobs: List[Dict] = []
    for source_fn in order:
        jobs = source_fn()
        if jobs:
            break
        time.sleep(0.5)  # tiny pause before trying the fallback

    jobs = _dedupe(jobs)
    jobs = filter_by_work_type(jobs, work_type)
    jobs = filter_by_experience(jobs, experience)
    return jobs[:results]


# ---------------------------------------------------------------------------
# Quick manual test:  python job_fetcher.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Fetching sample jobs ...\n")
    sample = fetch_jobs("machine learning engineer", "remote", results=10)
    if not sample:
        print("No jobs returned. Install JobSpy (pip install python-jobspy) "
              "or set Adzuna credentials.")
    for i, job in enumerate(sample, 1):
        print(f"{i}. {job['title']} — {job['company']} ({job['source']})")
        print(f"   {job['location']} | {job['salary'] or 'salary n/a'}")
        print(f"   {job['url']}\n")
