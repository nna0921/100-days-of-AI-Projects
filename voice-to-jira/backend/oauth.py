import os
import secrets
import time
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

from jira_tool import JiraConnection

load_dotenv()

CLIENT_ID = os.getenv("ATLASSIAN_CLIENT_ID")
CLIENT_SECRET = os.getenv("ATLASSIAN_CLIENT_SECRET")
REDIRECT_URI = os.getenv("ATLASSIAN_REDIRECT_URI", "http://localhost:8000/auth/jira/callback")

SCOPES = "read:jira-work write:jira-work read:jira-user offline_access"

AUTHORIZE_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ACCESSIBLE_RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"

SESSIONS: dict[str, dict] = {}

_PENDING_STATES: dict[str, float] = {}


def build_authorize_url() -> tuple[str, str]:
    """Returns (authorize_url, state). Caller stashes `state` in a cookie so
    /callback can verify the redirect wasn't forged."""
    state = secrets.token_urlsafe(24)
    _PENDING_STATES[state] = time.time()

    params = {
        "audience": "api.atlassian.com",
        "client_id": CLIENT_ID,
        "scope": SCOPES,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}", state


def verify_state(state: str) -> bool:
    """One-time use -- pops the state so it can't be replayed."""
    return _PENDING_STATES.pop(state, None) is not None


def _exchange(payload: dict) -> dict:
    response = httpx.post(TOKEN_URL, json=payload, headers={"Content-Type": "application/json"})
    response.raise_for_status()
    return response.json()


def exchange_code_for_tokens(code: str) -> dict:
    """Trades the one-time authorization code for an access + refresh token."""
    return _exchange({
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI,
    })


def refresh_tokens(refresh_token: str) -> dict:
    """Access tokens expire in about an hour -- this trades the refresh
    token (from offline_access) for a new access token."""
    return _exchange({
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token,
    })


def get_accessible_site(access_token: str) -> dict:
    response = httpx.get(
        ACCESSIBLE_RESOURCES_URL,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    response.raise_for_status()
    sites = response.json()
    if not sites:
        raise ValueError("This Atlassian account has no accessible Jira sites.")
    return sites[0] 


def start_connection(code: str) -> str:
    tokens = exchange_code_for_tokens(code)
    site = get_accessible_site(tokens["access_token"])

    session_id = secrets.token_urlsafe(24)
    SESSIONS[session_id] = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
        "expires_at": time.time() + tokens.get("expires_in", 3600) - 30,  
        "cloud_id": site["id"],
        "site_url": site["url"],
        "site_name": site.get("name", site["url"]),
    }
    return session_id


def get_connection(session_id: str | None) -> JiraConnection | None:
    """
    Returns a ready-to-use JiraConnection for this session, refreshing the
    access token first if it's expired. Returns None if there's no session
    (caller should fall back to the owner's own default_connection()).
    """
    if not session_id or session_id not in SESSIONS:
        return None

    session = SESSIONS[session_id]

    if time.time() >= session["expires_at"] and session["refresh_token"]:
        tokens = refresh_tokens(session["refresh_token"])
        session["access_token"] = tokens["access_token"]
        session["expires_at"] = time.time() + tokens.get("expires_in", 3600) - 30
        if tokens.get("refresh_token"):  # Atlassian sometimes rotates it
            session["refresh_token"] = tokens["refresh_token"]

    return JiraConnection(
        base_url=f"https://api.atlassian.com/ex/jira/{session['cloud_id']}",
        headers={
            "Authorization": f"Bearer {session['access_token']}",
            "Accept": "application/json",
        },
        auth=None,
        site_url=session["site_url"],
    )


def get_site_name(session_id: str | None) -> str | None:
    if session_id and session_id in SESSIONS:
        return SESSIONS[session_id]["site_name"]
    return None
