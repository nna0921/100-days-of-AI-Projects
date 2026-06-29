ROLE_PERMISSIONS = {
    "c_level":     ["finance", "marketing", "hr", "engineering", "general"],
    "finance":     ["finance", "general"],
    "marketing":   ["marketing", "general"],
    "hr":          ["hr", "general"],
    "engineering": ["engineering", "general"],
    "employee":    ["general"],
}


USERS = {
    "tony@finsolve.com":    {"password": "tony123",    "role": "c_level",     "name": "Tony Sharma"},
    "peter@finsolve.com":   {"password": "peter123",   "role": "engineering", "name": "Peter Pandey"},
    "finance@finsolve.com": {"password": "finance123", "role": "finance",     "name": "Finance User"},
    "hr@finsolve.com":      {"password": "hr123",      "role": "hr",          "name": "HR User"},
    "marketing@finsolve.com":{"password": "mkt123",    "role": "marketing",   "name": "Marketing User"},
    "emp@finsolve.com":     {"password": "emp123",     "role": "employee",    "name": "General Employee"},
}