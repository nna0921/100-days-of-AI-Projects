import os
import sys
import httpx
from dotenv import load_dotenv

load_dotenv()

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")


def discover(project_key: str, issuetype_name: str):
    response = httpx.get(
        f"{JIRA_BASE_URL}/rest/api/3/issue/createmeta",
        params={
            "projectKeys": project_key,
            "issuetypeNames": issuetype_name,
            "expand": "projects.issuetypes.fields",
        },
        auth=(JIRA_EMAIL, JIRA_API_TOKEN),
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    data = response.json()

    projects = data.get("projects", [])
    if not projects:
        print(f"No project found for key '{project_key}' -- check JIRA_PROJECT_KEY and the issue type name.")
        return

    issuetypes = projects[0].get("issuetypes", [])
    if not issuetypes:
        print(f"No issue type '{issuetype_name}' found on project '{project_key}'.")
        return

    fields = issuetypes[0].get("fields", {})
    print(f"\nFields available when creating a '{issuetype_name}' in '{project_key}':\n")
    for field_id, meta in sorted(fields.items()):
        required = "REQUIRED" if meta.get("required") else "optional"
        print(f"  {field_id:<20} {meta.get('name', ''):<28} [{required}]")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python discover_fields.py <PROJECT_KEY> <ISSUE_TYPE_NAME>")
        print("Example: python discover_fields.py VT Bug")
        sys.exit(1)

    discover(sys.argv[1], sys.argv[2])
