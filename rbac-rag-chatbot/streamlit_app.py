"""Streamlit interface for the FinSolve RBAC RAG API."""

from __future__ import annotations

import html
import os
from typing import Any

import httpx
import streamlit as st


st.set_page_config(
    page_title="FinSolve",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded",
)

DEFAULT_API_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
REQUEST_TIMEOUT = 90.0

ROLE_LABELS = {
    "c_level": "Executive",
    "finance": "Finance",
    "marketing": "Marketing",
    "hr": "People & Culture",
    "engineering": "Engineering",
    "employee": "Employee",
}

ROLE_SCOPES = {
    "c_level": ["Finance", "Marketing", "HR", "Engineering", "General"],
    "finance": ["Finance", "General"],
    "marketing": ["Marketing", "General"],
    "hr": ["HR", "General"],
    "engineering": ["Engineering", "General"],
    "employee": ["General"],
}

SUGGESTED_PROMPTS = {
    "c_level": [
        "Summarize the company's financial and marketing performance.",
        "What are the most important engineering and business risks?",
        "Give me an executive summary of employee policies.",
    ],
    "finance": [
        "Summarize the 2024 quarterly financial performance.",
        "What financial risks and mitigations are documented?",
        "Explain the reimbursement policy.",
    ],
    "marketing": [
        "Compare marketing performance across all four quarters.",
        "Which campaigns performed best in 2024?",
        "What were the recommendations for Q1 2025?",
    ],
    "hr": [
        "Summarize employee attendance and leave information.",
        "What benefits and leave policies are available?",
        "Explain the performance review process.",
    ],
    "engineering": [
        "Describe the system architecture and technology stack.",
        "What is the deployment and incident response process?",
        "Summarize the engineering roadmap.",
    ],
    "employee": [
        "What is the work-from-home policy?",
        "How do I apply for leave?",
        "What benefits are available to employees?",
    ],
}




def initialize_state() -> None:
    defaults: dict[str, Any] = {
        "token": None,
        "user": None,
        "messages": [],
        "api_url": DEFAULT_API_URL,
        "login_email": "",
        "login_password": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def api_request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    headers = kwargs.pop("headers", {})
    if st.session_state.token:
        headers["Authorization"] = f"Bearer {st.session_state.token}"
    return httpx.request(
        method,
        f"{st.session_state.api_url}{path}",
        headers=headers,
        timeout=REQUEST_TIMEOUT,
        **kwargs,
    )





def logout() -> None:
    st.session_state.token = None
    st.session_state.user = None
    st.session_state.messages = []


def render_brand() -> None:
    st.header("FinSolve ")


def render_login() -> None:
    _, col, _ = st.columns([1, 1.25, 1])
    with col:
        st.title("Welcome to FinSolve")
        st.markdown("Secure company intelligence. Ask better questions.")
        st.write("")

        with st.form("login_form"):
            email = st.text_input(
                "Work email",
                key="login_email",
                placeholder="you@finsolve.com",
            )
            password = st.text_input(
                "Password",
                key="login_password",
                type="password",
                placeholder="Enter your password",
            )
            submitted = st.form_submit_button("Sign in", use_container_width=True)

        if submitted:
            if not email.strip() or not password:
                st.warning("Enter both your email and password.")
            else:
                try:
                    response = api_request(
                        "POST",
                        "/auth/login",
                        data={"username": email.strip(), "password": password},
                    )
                    if response.status_code == 200:
                        st.session_state.token = response.json()["access_token"]
                        profile = api_request("GET", "/me")
                        profile.raise_for_status()
                        st.session_state.user = profile.json()
                        st.session_state.messages = []
                        st.rerun()
                    elif response.status_code == 401:
                        st.error("That email and password combination was not recognized.")
                    else:
                        st.error("Atlas could not complete the sign-in. Please try again.")
                except (httpx.HTTPError, KeyError, ValueError):
                    st.error("Atlas cannot reach the API. Start the FastAPI server and try again.")


def render_sidebar() -> None:
    user = st.session_state.user
    role = user["role"]
    with st.sidebar:
        render_brand()
        st.write(f"**Signed in as:** {html.escape(user['name'])}")
        st.write(f"**Email:** {html.escape(user['email'])}")
        st.caption(f"{ROLE_LABELS.get(role, role.title())} workspace")
        st.divider()

        st.write("**Your knowledge access:**")
        for scope in ROLE_SCOPES.get(role, []):
            st.write(f"- {scope}")

        st.divider()
        if st.button("Clear conversation", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
        if st.button("Sign out", use_container_width=True):
            logout()
            st.rerun()


def render_message(message: dict[str, Any]) -> None:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        sources = message.get("sources", [])
        if sources:
            st.caption(f"Sources: {', '.join(sources)}")


def ask_atlas(query: str) -> None:
    clean_query = query.strip()
    if not clean_query:
        return

    st.session_state.messages.append({"role": "user", "content": clean_query})
    try:
        with st.spinner("Searching your permitted knowledge…"):
            response = api_request("POST", "/chat", json={"query": clean_query})
        if response.status_code == 401:
            logout()
            st.error("Your session expired. Sign in again to continue.")
            return
        response.raise_for_status()
        result = response.json()
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": result["answer"],
                "sources": result.get("sources", []),
            }
        )
    except (httpx.HTTPError, KeyError, ValueError):
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": "I couldn't complete that request. Check the API connection and try again.",
                "sources": [],
            }
        )


def render_chat() -> None:
    user = st.session_state.user
    role = user["role"]
    
    st.title(f"Welcome, {html.escape(user['name'].split()[0])}")
    st.markdown("Explore company knowledge with answers grounded only in information your role is permitted to see.")

    if not st.session_state.messages:
        st.subheader("A few good places to start")
        columns = st.columns(3)
        for index, suggestion in enumerate(SUGGESTED_PROMPTS.get(role, SUGGESTED_PROMPTS["employee"])):
            with columns[index]:
                if st.button(suggestion, key=f"prompt_{index}", use_container_width=True):
                    ask_atlas(suggestion)
                    st.rerun()
        st.caption("Atlas searches only the departments shown above. It will tell you when the answer is outside your access.")

    for message in st.session_state.messages:
        render_message(message)

    if query := st.chat_input("Ask Atlas about policies, reports, people, or systems…"):
        ask_atlas(query)
        st.rerun()


initialize_state()

if st.session_state.token and st.session_state.user:
    render_sidebar()
    render_chat()
else:
    render_login()
