"""
Wraps Jira's REST API v3 issue-creation endpoint as a plain function.
This is the same call as the original test-jira.py, just parameterized
so the agent can call it with whatever fields the conversation produced.

Supports two auth modes via JiraConnection:
  - Basic auth against your own site (JIRA_BASE_URL/EMAIL/API_TOKEN in .env)
    -- this is the original behavior, still the default when no connection
    is passed in.
  - OAuth bearer token against a visitor's own site, built from the tokens
    oauth.py obtains when someone clicks "Connect your Jira".
"""

import os
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv

load_dotenv()

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")


@dataclass
class JiraConnection:
    """Everything a request needs to reach one specific Jira site."""
    base_url: str                  # e.g. https://api.atlassian.com/ex/jira/{cloudId} for OAuth,
                                    # or https://yoursite.atlassian.net for basic auth
    headers: dict
    auth: tuple | None = None      # (email, api_token) for basic auth; None for OAuth
    site_url: str | None = None    # browsable https://yoursite.atlassian.net, for building
                                    # ticket links -- same as base_url in basic-auth mode,
                                    # different from it in OAuth mode (see oauth.py)


def default_connection() -> JiraConnection:
    """The owner's own site, from .env -- unchanged from the original behavior."""
    if not all([JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN]):
        raise ValueError(
            "Missing Jira environment variables. Check your .env file "
            "(JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN)."
        )
    return JiraConnection(
        base_url=JIRA_BASE_URL,
        headers={"Accept": "application/json"},
        auth=(JIRA_EMAIL, JIRA_API_TOKEN),
        site_url=JIRA_BASE_URL,
    )


def _resolve(conn: JiraConnection | None) -> JiraConnection:
    return conn or default_connection()


def find_assignee_account_id(name_or_email: str, conn: JiraConnection | None = None) -> str | None:
    """
    Looks up a user's accountId by name or email -- Jira's create-issue API
    needs an accountId, not a display name, so this runs before create_jira_ticket
    whenever the user mentions an assignee by name.
    Returns None (rather than raising) if nobody matches, so the caller can
    decide to skip the field instead of failing the whole ticket over it.
    """
    conn = _resolve(conn)
    response = httpx.get(
        f"{conn.base_url}/rest/api/3/user/search",
        params={"query": name_or_email},
        auth=conn.auth,
        headers=conn.headers,
    )
    response.raise_for_status()
    results = response.json()
    return results[0]["accountId"] if results else None


def find_similar_open_tickets(project: str, summary: str, limit: int = 3, conn: JiraConnection | None = None) -> list[dict]:
    """
    Free duplicate check: searches the project for open issues whose summary
    text is close to the new one, using Jira's own text search (JQL `~`).
    Returns a short list of {key, summary} so the agent can ask "did you mean
    the existing VT-3 instead of filing a new one?" before creating anything.
    """
    conn = _resolve(conn)
    # Keep it to the meaningful words -- JQL text search works best on a few
    # distinctive terms rather than the whole sentence.
    words = [w for w in summary.split() if len(w) > 3][:6]
    if not words:
        return []
    jql = f'project = {project} AND statusCategory != Done AND text ~ "{" ".join(words)}"'

    response = httpx.get(
        f"{conn.base_url}/rest/api/3/search",
        params={"jql": jql, "maxResults": limit, "fields": "summary"},
        auth=conn.auth,
        headers=conn.headers,
    )
    response.raise_for_status()
    issues = response.json().get("issues", [])
    return [{"key": i["key"], "summary": i["fields"]["summary"]} for i in issues]


def create_jira_ticket(
    project: str,
    issuetype: str,
    summary: str,
    description: str | None = None,
    priority: str | None = None,
    assignee_name: str | None = None,
    labels: list[str] | None = None,
    conn: JiraConnection | None = None,
) -> dict:
    """
    Creates a Jira issue and returns Jira's JSON response, plus a
    ready-to-share "url" key pointing straight at the new ticket.
    Raises httpx.HTTPStatusError if Jira rejects the request (bad project
    key, invalid issue type name, auth failure, etc.) -- let this bubble up
    so the agent can tell the user it failed rather than pretending it worked.

    All of assignee_name/labels are optional -- each is only
    added to the payload if provided. `conn` defaults to the owner's own
    site (unchanged from before); pass a visitor's JiraConnection to file
    the ticket in their site instead.
    """
    conn = _resolve(conn)

    fields: dict = {
        "project": {"key": project},
        "summary": summary,
        "issuetype": {"name": issuetype},
    }

    if description:
        fields["description"] = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": description}],
                }
            ],
        }

    if priority:
        fields["priority"] = {"name": priority}

    if assignee_name:
        account_id = find_assignee_account_id(assignee_name, conn=conn)
        if account_id:
            fields["assignee"] = {"accountId": account_id}
        # If nobody matched, we silently skip rather than failing the whole
        # ticket -- an unassigned ticket beats a rejected API call.

    if labels:
        fields["labels"] = labels

    response = httpx.post(
        f"{conn.base_url}/rest/api/3/issue",
        json={"fields": fields},
        auth=conn.auth,
        headers={**conn.headers, "Content-Type": "application/json"},
    )
    response.raise_for_status()
    result = response.json()

    # OAuth-mode base_url is api.atlassian.com/ex/jira/{cloudId}, which isn't
    # a browsable URL -- site_url (set by oauth.py, or equal to base_url in
    # basic-auth mode) is what we actually want to build ticket links from.
    result["url"] = f"{conn.site_url or conn.base_url}/browse/{result['key']}"
    return result