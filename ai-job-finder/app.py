"""
app.py
------
Job Scout AI — Phase 1 spine:
    CV upload + parse -> fetch_jobs() -> embed both -> cosine-similarity
    ranking -> Streamlit UI showing jobs with a match %.
"""

import html

import streamlit as st

from job_fetcher import fetch_jobs, split_location
from matching import rank_jobs
from candidate_profile import build_profile_text, parse_cv

st.set_page_config(page_title="Job Scout AI", layout="wide")

# ---------------------------------------------------------------------------
# Styling - one block so it's easy to tweak. Logic below never depends on
# these classes existing; this is presentation only.
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    html, body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }

    .app-header { margin-bottom: 0.5rem; }
    .app-title { font-size: 2rem; font-weight: 700; color: #1A5FB4; line-height: 1.2; }
    .app-tagline { font-size: 1rem; color: #5B6B7B; margin-top: 0.15rem; }

    .section-header {
        font-size: 1.25rem;
        font-weight: 600;
        color: #1A5FB4;
        padding-bottom: 0.5rem;
        margin: 1.75rem 0 1rem 0;
        border-bottom: 1px solid #E3E8EF;
    }

    div[data-testid="stContainer"] {
        background-color: #FFFFFF;
        border: 1px solid #E3E8EF !important;
        border-radius: 10px !important;
        padding: 16px !important;
        margin-bottom: 14px;
        box-shadow: 0 1px 3px rgba(28, 39, 51, 0.06);
    }

    .job-title { font-size: 1.1rem; font-weight: 700; color: #123A6B; margin-bottom: 2px; }
    .job-meta { font-size: 0.9rem; color: #5B6B7B; margin-bottom: 6px; }
    .job-salary { font-size: 0.9rem; color: #1C2733; margin-bottom: 6px; }

    .match-badge {
        display: inline-block;
        padding: 4px 14px;
        border-radius: 999px;
        font-weight: 600;
        font-size: 0.85rem;
        color: #FFFFFF;
        float: right;
    }
    .match-badge.high { background-color: #1E7E44; }
    .match-badge.mid  { background-color: #B7791F; }
    .match-badge.low  { background-color: #8A94A6; }

    .match-bar-track {
        background-color: #E3E8EF;
        border-radius: 999px;
        height: 8px;
        margin: 8px 0 12px 0;
        overflow: hidden;
    }
    .match-bar-fill { height: 100%; border-radius: 999px; }
    .match-bar-fill.high { background-color: #1E7E44; }
    .match-bar-fill.mid  { background-color: #B7791F; }
    .match-bar-fill.low  { background-color: #8A94A6; }

    div[data-testid="stButton"] button,
    div[data-testid="stLinkButton"] a {
        background-color: #1A5FB4 !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 500 !important;
        transition: background-color 0.15s ease;
    }
    div[data-testid="stButton"] button:hover,
    div[data-testid="stLinkButton"] a:hover {
        background-color: #154A8F !important;
        color: #FFFFFF !important;
    }

    div[data-testid="stTextInput"] input,
    div[data-testid="stNumberInput"] input {
        background-color: #F4F6F9;
        border: 1px solid #E3E8EF;
        border-radius: 8px;
    }
    div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
        background-color: #F4F6F9;
        border: 1px solid #E3E8EF;
        border-radius: 8px;
    }
    div[data-testid="stFileUploader"] section {
        background-color: #F4F6F9;
        border: 1px dashed #E3E8EF;
        border-radius: 8px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def section_header(text: str) -> None:
    st.markdown(f'<div class="section-header">{text}</div>', unsafe_allow_html=True)


def match_tier(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 50:
        return "mid"
    return "low"


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
st.session_state.setdefault("cv", None)
st.session_state.setdefault("jobs", [])

st.markdown(
    '<div class="app-header">'
    '<div class="app-title">Job Scout AI</div>'
    '<div class="app-tagline">Builds a picture of who you are, then finds and ranks real jobs against it.</div>'
    "</div>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Step 1: CV upload
# ---------------------------------------------------------------------------
section_header("1. Upload your CV")
uploaded = st.file_uploader("Upload your CV", type=["pdf"])

if uploaded is not None:
    st.session_state.cv = parse_cv(uploaded)

if st.session_state.cv:
    st.caption(f"Detected experience level from your CV: **{st.session_state.cv['experience_label']}** "
               "— this shapes match scoring below, in addition to any Experience level filter you pick.")
    with st.expander(f"Parsed CV ({st.session_state.cv['num_pages']} page(s)) — preview"):
        st.text(st.session_state.cv["raw_text"][:2000] or "(no text extracted)")

# ---------------------------------------------------------------------------
# Step 2: Job search
# ---------------------------------------------------------------------------
section_header("2. Search for jobs")

# Label -> job_fetcher.py experience level.
EXPERIENCE_OPTIONS = {
    "Any": "any", "Fresher / Entry": "entry", "Junior": "junior",
    "Mid": "mid", "Senior": "senior",
}
# Label -> job_fetcher.py work_type.
WORK_TYPE_OPTIONS = {"Any": "any", "Onsite": "onsite", "Hybrid": "hybrid", "Remote": "remote"}
# Preset "City, Country" strings - each parses cleanly via job_fetcher.split_location().
LOCATION_OPTIONS = [
    "New York, US", "London, UK", "Lahore, Pakistan", "Bangalore, India",
    "Toronto, Canada", "Sydney, Australia", "Dubai, UAE", "Singapore, Singapore",
    "Berlin, Germany", "Paris, France", "Amsterdam, Netherlands", "Cape Town, South Africa",
    "Dublin, Ireland", "Auckland, New Zealand", "Milan, Italy", "Madrid, Spain",
    "Warsaw, Poland", "Sao Paulo, Brazil", "Mexico City, Mexico", "Remote",
]

row1 = st.columns([2, 2])
with row1[0]:
    search_term = st.text_input("Job title / keywords", value="machine learning engineer")
with row1[1]:
    location_input = st.selectbox("Location (City, Country)", LOCATION_OPTIONS, index=0)

row2 = st.columns([1, 1, 1])
with row2[0]:
    work_type_label = st.selectbox("Work arrangement", list(WORK_TYPE_OPTIONS.keys()), index=0)
with row2[1]:
    experience_label = st.selectbox("Experience level", list(EXPERIENCE_OPTIONS.keys()), index=0)
with row2[2]:
    results_wanted = st.number_input("Results", min_value=5, max_value=50, value=20, step=5)

find_clicked = st.button("Find matching jobs", type="primary", disabled=st.session_state.cv is None)

if st.session_state.cv is None:
    st.info("Upload a CV above to enable job search.")

if find_clicked:
    city, country = split_location(location_input)
    experience = EXPERIENCE_OPTIONS[experience_label]
    work_type = WORK_TYPE_OPTIONS[work_type_label]
    with st.spinner(f"Fetching jobs for '{search_term}' in '{city}'..."):
        fetched = fetch_jobs(
            search_term, location=city, results=int(results_wanted),
            country=country, experience=experience, work_type=work_type,
            linkedin_descriptions=True,
        )

    if not fetched:
        st.warning("No jobs found. Try a different title/location, or check your Adzuna/JobSpy setup.")
        st.session_state.jobs = []
    else:
        profile_text = build_profile_text(st.session_state.cv)
        candidate_level = st.session_state.cv.get("level")
        with st.spinner("Scoring matches..."):
            st.session_state.jobs = rank_jobs(profile_text, fetched, candidate_level=candidate_level)

# ---------------------------------------------------------------------------
# Step 3: Ranked results
# ---------------------------------------------------------------------------
if st.session_state.jobs:
    section_header("3. Ranked matches")
    for job in st.session_state.jobs:
        with st.container(border=True):
            score = job["match_score"]
            tier = match_tier(score)
            # Job fields come from scraped external postings (untrusted) - escape
            # before interpolating into raw HTML to avoid stored XSS.
            title = html.escape(job["title"])
            company = html.escape(job["company"])
            location = html.escape(job["location"])
            source = html.escape(job["source"])
            salary = html.escape(job["salary"]) if job.get("salary") else None
            st.markdown(
                f'<span class="match-badge {tier}">{score}% match</span>'
                f'<div class="job-title">{title}</div>'
                f'<div class="job-meta">{company} · {location} · {source}</div>'
                + (f'<div class="job-salary">{salary}</div>' if salary else "")
                + f'<div class="match-bar-track"><div class="match-bar-fill {tier}" style="width:{score}%"></div></div>',
                unsafe_allow_html=True,
            )
            st.link_button("Apply / view listing", job["url"])
