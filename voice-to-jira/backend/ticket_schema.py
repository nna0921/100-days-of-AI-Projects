"""
Defines the fields a Jira ticket needs, and the completeness check the
backend uses to decide whether the conversation is finished. Gemini never
decides completeness itself -- it just fills in what it can, and this
function is the judge.
"""

REQUIRED_FIELDS = {
    "project": None,      # Jira project key, e.g. "ENG"
    "issuetype": None,    # "Task" / "Bug" / "Story"
    "summary": None,      # one-line title
    "priority": None,     # "Highest" / "High" / "Medium" / "Low"
}

# Optional fields: the agent fills these in if the user mentions them, but
# the conversation is never blocked waiting on them the way REQUIRED_FIELDS is.
OPTIONAL_FIELDS = {
    "description": None,     # detailed body
    "assignee_name": None,   # plain name/email as the user said it -- resolved
                              # to an accountId by jira_tool before the API call
    "labels": None,          # list[str]
}


def is_complete(draft: dict) -> bool:
    """True only when every required field has a non-empty value.
    Optional fields never gate this -- they're best-effort extras."""
    return all(draft.get(key) for key in REQUIRED_FIELDS)


def missing_fields(draft: dict) -> list[str]:
    """Which required fields are still empty -- useful for debugging/logging."""
    return [key for key in REQUIRED_FIELDS if not draft.get(key)]