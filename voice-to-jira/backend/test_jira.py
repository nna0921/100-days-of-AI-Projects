import os
import httpx
from dotenv import load_dotenv


load_dotenv()

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")

payload = {
    "fields": {
        "project": {"key": JIRA_PROJECT_KEY},
        "summary": "Test ticket from API",
        "description": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph", 
                    "content": [{"type": "text", "text": "This is a test ticket created via the API."}]
                }
            ]
        },
        "issuetype": {"name": "Task"},
    }
}

if not all([JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY]):
    raise ValueError("Missing one or more Jira environment variables. Check your .env file.")

response = httpx.post(
    f"{JIRA_BASE_URL}/rest/api/3/issue",
    json=payload,
    auth=(JIRA_EMAIL, JIRA_API_TOKEN),
    headers={"Content-Type": "application/json"},
)

print(response.status_code)
print(response.json())