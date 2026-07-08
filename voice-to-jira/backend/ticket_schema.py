REQUIRED_FIELDS = {
    "project": None,      
    "issuetype": None,   
    "summary": None,      
    "priority": None,    
}

OPTIONAL_FIELDS = {
    "description": None,    
    "assignee_name": None,   
                             
    "labels": None,        
}

def is_complete(draft: dict) -> bool:
    """True only when every required field has a non-empty value.
    Optional fields never gate this, they're best-effort extras."""
    return all(draft.get(key) for key in REQUIRED_FIELDS)


def missing_fields(draft: dict) -> list[str]:
    """Which required fields are still empty, useful for debugging/logging."""
    return [key for key in REQUIRED_FIELDS if not draft.get(key)]