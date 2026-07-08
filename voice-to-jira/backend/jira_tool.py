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
    base_url: str                 
                                   
    headers: dict
    auth: tuple | None = None      
    site_url: str | None = None    
                        


def default_connection() -> JiraConnection:
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
    conn = _resolve(conn)
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

    result["url"] = f"{conn.site_url or conn.base_url}/browse/{result['key']}"
    return result