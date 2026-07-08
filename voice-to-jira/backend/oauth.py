"""
Atlassian OAuth 2.0 (3LO) flow -- lets a visitor connect their own Jira Cloud
site instead of tickets always landing in the owner's site.

Setup (one-time, free, no card):
  1. Go to https://developer.atlassian.com/console/myapps/ and create an
     OAuth 2.0 (3LO) app.
  2. Under "Permissions", add the Jira API with scopes:
       read:jira-work  write:jira-work  read:jira-user  offline_access
     (offline_access is what gets you a refresh token, so the connection
     survives past the ~1 hour access-token expiry.)
  3. Under "Authorization", set the callback URL to:
       http://localhost:8000/auth/jira/callback   (local dev)
       https://your-app.onrender.com/auth/jira/callback   (deployed)
  4. Copy the Client ID and Secret into your .env as ATLASSIAN_CLIENT_ID
     and ATLASSIAN_CLIENT_SECRET.

This module only talks to Atlassian's own OAuth endpoints -- no cost, same
free Jira REST API you're already using, just called with a bearer token
scoped to whichever site the visitor picked instead of basic auth against
your own site.
"""

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

# In-memory session store: session_id -> {access_token, refresh_token,
# expires_at, cloud_id, site_url, site_name}.
# Fine for a portfolio demo -- resets if the server restarts (e.g. Render's
# free tier spinning down), so a visitor may need to reconnect after a long
# idle period. Swap for a real DB if this needs to survive that.
SESSIONS: dict[str, dict] = {}

# Short-lived store for the CSRF "state" param between /login and /callback.
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
    """
    A single Atlassian account can have multiple Jira sites. For a portfolio
    demo, we keep it simple and use the first one -- good enough unless the
    visitor's account manages several sites, in which case you'd extend this
    into a "pick a site" step.
    """
    response = httpx.get(
        ACCESSIBLE_RESOURCES_URL,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    response.raise_for_status()
    sites = response.json()
    if not sites:
        raise ValueError("This Atlassian account has no accessible Jira sites.")
    return sites[0]  # {"id": cloudId, "url": "https://x.atlassian.net", "name": "..."}


def start_connection(code: str) -> str:
    """
    Full callback-time flow: code -> tokens -> site info -> stored session.
    Returns a new session_id for the caller to set as a cookie.
    """
    tokens = exchange_code_for_tokens(code)
    site = get_accessible_site(tokens["access_token"])

    session_id = secrets.token_urlsafe(24)
    SESSIONS[session_id] = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
        "expires_at": time.time() + tokens.get("expires_in", 3600) - 30,  # 30s safety margin
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
