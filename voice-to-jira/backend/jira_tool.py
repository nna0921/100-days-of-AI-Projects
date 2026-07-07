"""
Wraps Jira's REST API v3 issue-creation endpoint as a plain function.
This is the same call as the original test-jira.py, just parameterized
so the agent can call it with whatever fields the conversation produced.
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")


def create_jira_ticket(
    project: str,
    issuetype: str,
    summary: str,
    description: str,
    priority: str = "Medium",
) -> dict:
    """
    Creates a Jira issue and returns Jira's JSON response (contains the new
    issue's key, e.g. {"id": "10001", "key": "ENG-42", "self": "..."}).
    Raises httpx.HTTPStatusError if Jira rejects the request (bad project
    key, invalid issue type name, auth failure, etc.) -- let this bubble up
    so the agent can tell the user it failed rather than pretending it worked.
    """
    if not all([JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN]):
        raise ValueError(
            "Missing Jira environment variables. Check your .env file "
            "(JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN)."
        )

    payload = {
        "fields": {
            "project": {"key": project},
            "summary": summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}],
                    }
                ],
            },
            "issuetype": {"name": issuetype},
            "priority": {"name": priority},
        }
    }

    response = httpx.post(
        f"{JIRA_BASE_URL}/rest/api/3/issue",
        json=payload,
        auth=(JIRA_EMAIL, JIRA_API_TOKEN),
        headers={"Content-Type": "application/json"},
    )
    response.raise_for_status()
    return response.json()