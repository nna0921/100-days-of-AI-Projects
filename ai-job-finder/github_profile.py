"""
github_profile.py
------------------
Fetches a candidate's public GitHub repos (+ top-repo READMEs) as extra
evidence for matching, on top of whatever's in their CV.

No auth needed - GitHub's unauthenticated rate limit (60 req/hr) is plenty
for a single profile lookup. Everything here fails soft: a bad username, a
private/empty account, or a network error all just return an empty result
so the rest of the app keeps working without GitHub data.
"""

from __future__ import annotations

import re
from typing import Dict, List

import requests
import streamlit as st

_TIMEOUT = 10
_HEADERS = {"Accept": "application/vnd.github+json"}
_README_HEADERS = {"Accept": "application/vnd.github.v3.raw"}

# Accepts a bare username ("octocat"), an "@octocat" handle, or a pasted
# profile/repo URL ("https://github.com/octocat" or ".../octocat/some-repo") -
# whatever someone naturally pastes into the field should just work.
_GITHUB_URL_RE = re.compile(r"github\.com/([^/\s]+)", re.IGNORECASE)


def normalize_username(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    match = _GITHUB_URL_RE.search(value)
    if match:
        return match.group(1)
    return value.lstrip("@")


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_github_repos(username: str, max_repos: int = 30) -> List[Dict]:
    """Fetch a user's public, non-fork repos. Returns [] on any failure."""
    username = normalize_username(username)
    if not username:
        return []

    try:
        resp = requests.get(
            f"https://api.github.com/users/{username}/repos",
            params={"per_page": max_repos, "sort": "updated"},
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        if not isinstance(data, list):
            return []
    except Exception:  # noqa: BLE001 - bad username/network issue -> no GitHub data
        return []

    repos = []
    for r in data:
        if not isinstance(r, dict) or r.get("fork"):
            continue
        repos.append(
            {
                "name": r.get("name") or "",
                "description": r.get("description") or "",
                "language": r.get("language") or "",
                "stars": r.get("stargazers_count") or 0,
                "url": r.get("html_url") or "",
            }
        )
    return [r for r in repos if r["name"]]


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_readme(username: str, repo: str) -> str:
    """Fetch a repo's README as plain text (truncated). '' on any failure."""
    username = normalize_username(username)
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{username}/{repo}/readme",
            headers=_README_HEADERS,
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            return ""
        return resp.text[:3000]
    except Exception:  # noqa: BLE001 - missing/private README -> skip it
        return ""
