"""
Defines the fields a Jira ticket needs, and the completeness check the
backend uses to decide whether the conversation is finished. Gemini never
decides completeness itself -- it just fills in what it can, and this
function is the judge.
"""

REQUIRED_FIELDS = {
    "project": None,      
    "issuetype": None,   
    "summary": None,     
    "description": None,  
    "priority": None,    
}


def is_complete(draft: dict) -> bool:
    """True only when every required field has a non-empty value."""
    return all(draft.get(key) for key in REQUIRED_FIELDS)


def missing_fields(draft: dict) -> list[str]:
    """Which fields are still empty -- useful for debugging/logging."""
    return [key for key in REQUIRED_FIELDS if not draft.get(key)]