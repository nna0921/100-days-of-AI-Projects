"""
app.py
------
Job Scout AI — Phase 1 spine:
    CV upload + parse -> fetch_jobs() -> embed both -> cosine-similarity
    ranking -> Streamlit UI showing jobs with a match %.
"""

import hashlib
import html

import streamlit as st

import ai
from github_profile import fetch_github_repos, fetch_readme
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
    :root {
        --bg-page: #F7F9FC;
        --bg-card: #FFFFFF;
        --border-subtle: rgba(15, 23, 42, 0.08);
        --text-primary: #1C2733;
        --text-secondary: #5B6B7B;
        --text-muted: #94A3B8;
        --accent: #E8A700;
        --accent-2: #FFCB3D;
        --accent-tint: #FFF7DF;
        --accent-glow: rgba(232, 167, 0, 0.3);
    }

    html, body, .stApp {
        font-family: "SF Pro Display", Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background-color: var(--bg-page) !important;
    }

    div.st-key-app-header {
        margin-bottom: 0.75rem;
    }
    div.st-key-app-header img { display: block; margin-bottom: 22px; }
    .app-tagline-head { font-weight: 700; font-size: 1.2rem; color: var(--text-primary); margin-bottom: 4px; }
    .app-tagline-sub {
        font-size: 1.05rem;
        color: #52525B;
        font-weight: 400;
        line-height: 1.6;
        white-space: nowrap;
    }

    .section-header {
        position: relative;
        font-size: 1.2rem;
        font-weight: 700;
        color: var(--text-primary);
        padding-bottom: 0.65rem;
        margin: 2rem 0 1.15rem 0;
        letter-spacing: -0.01em;
        border-bottom: 1px solid var(--border-subtle);
    }
    .section-header::after {
        content: "";
        position: absolute;
        left: 0; bottom: -1px;
        width: 46px; height: 2px;
        background: linear-gradient(90deg, var(--accent), var(--accent-2));
        border-radius: 2px;
    }

    div[data-testid="stContainer"] {
        background-color: var(--bg-card) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: 16px !important;
        padding: 18px !important;
        margin-bottom: 14px;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
        transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
    }
    div[data-testid="stContainer"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.09);
        border-color: rgba(232, 167, 0, 0.28) !important;
    }

    .job-title { font-size: 1.1rem; font-weight: 700; color: var(--text-primary); margin-bottom: 2px; }
    .job-meta { font-size: 0.9rem; color: var(--text-secondary); margin-bottom: 6px; }
    .job-salary { font-size: 0.9rem; color: var(--text-primary); margin-bottom: 6px; }

    .match-badge {
        display: inline-block;
        padding: 4px 14px;
        border-radius: 999px;
        font-weight: 700;
        font-size: 0.85rem;
        color: #FFFFFF;
        float: right;
        box-shadow: 0 2px 8px rgba(15, 23, 42, 0.12);
    }
    .match-badge.high { background: linear-gradient(135deg, #22A35F, #1E7E44); }
    .match-badge.mid  { background: linear-gradient(135deg, #D19A3D, #B7791F); }
    .match-badge.low  { background: linear-gradient(135deg, #9AA5B4, #8A94A6); }

    .match-bar-track {
        background-color: #E9EDF3;
        border-radius: 999px;
        height: 7px;
        margin: 9px 0 12px 0;
        overflow: hidden;
    }
    .match-bar-fill { height: 100%; border-radius: 999px; }
    .match-bar-fill.high { background: linear-gradient(90deg, #22A35F, #1E7E44); }
    .match-bar-fill.mid  { background: linear-gradient(90deg, #D19A3D, #B7791F); }
    .match-bar-fill.low  { background: linear-gradient(90deg, #9AA5B4, #8A94A6); }

    div[data-testid="stButton"] button,
    div[data-testid="stLinkButton"] a,
    div[data-testid="stFormSubmitButton"] button {
        background: linear-gradient(135deg, var(--accent), var(--accent-2)) !important;
        color: var(--text-primary) !important;
        border: none !important;
        border-radius: 999px !important;
        font-weight: 600 !important;
        box-shadow: 0 4px 14px var(--accent-glow);
        transition: transform 0.15s ease, box-shadow 0.2s ease;
    }
    div[data-testid="stButton"] button:hover,
    div[data-testid="stLinkButton"] a:hover,
    div[data-testid="stFormSubmitButton"] button:hover {
        box-shadow: 0 6px 20px var(--accent-glow);
        transform: translateY(-1px);
    }

    div[data-testid="stTextInput"] input,
    div[data-testid="stNumberInput"] input,
    div[data-testid="stTextArea"] textarea {
        background-color: var(--bg-card) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: 12px !important;
        transition: box-shadow 0.15s ease, border-color 0.15s ease;
    }
    div[data-testid="stTextInput"] input:focus,
    div[data-testid="stNumberInput"] input:focus,
    div[data-testid="stTextArea"] textarea:focus {
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 3px var(--accent-glow) !important;
    }
    div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
        background-color: var(--bg-card) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: 12px !important;
    }
    div[data-testid="stFileUploader"] section {
        background-color: var(--bg-card) !important;
        border: 1.5px dashed var(--accent-glow) !important;
        border-radius: 16px !important;
    }
    div[data-testid="stExpander"] {
        background-color: var(--bg-card) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: 16px !important;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
    }
    div[data-testid="stForm"] {
        background-color: transparent !important;
        border: none !important;
    }

    .info-box {
        background-color: var(--accent-tint);
        border: 1px solid #F3DE9A;
        color: #8A6300;
        border-radius: 12px;
        padding: 12px 16px;
        font-size: 0.9rem;
        margin: 4px 0 12px 0;
    }

    .verdict-badge {
        display: inline-block;
        padding: 3px 12px 3px 20px;
        position: relative;
        border-radius: 999px;
        font-weight: 600;
        font-size: 0.78rem;
        margin-bottom: 6px;
    }
    .verdict-badge::before {
        content: "";
        position: absolute;
        left: 9px; top: 50%;
        width: 6px; height: 6px;
        border-radius: 50%;
        transform: translateY(-50%);
    }
    .verdict-badge.strong-fit   { background-color: #DCF3E3; color: #1E7E44; }
    .verdict-badge.strong-fit::before   { background-color: #1E7E44; }
    .verdict-badge.possible-fit { background-color: #FDF3D8; color: #966B14; }
    .verdict-badge.possible-fit::before { background-color: #B7791F; }
    .verdict-badge.stretch      { background-color: #EDEFF3; color: #5B6B7B; }
    .verdict-badge.stretch::before      { background-color: #8A94A6; }
    .verdict-badge.off-target   { background-color: #F8E3E1; color: #A13F34; }
    .verdict-badge.off-target::before   { background-color: #A13F34; }

    .match-reason {
        font-size: 0.88rem;
        color: var(--text-secondary);
        margin: 4px 0 8px 0;
        line-height: 1.5;
    }

    .skill-pill {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 500;
        margin: 2px 4px 2px 0;
        transition: transform 0.12s ease;
    }
    .skill-pill:hover { transform: translateY(-1px); }
    .skill-pill.matched { background-color: #E1F3E7; color: #1E7E44; border: 1px solid #BEE6CB; }
    .skill-pill.missing { background-color: #FBF0D9; color: #966B14; border: 1px solid #F2DFA8; }
    .skill-pill.neutral { background-color: var(--accent-tint); color: #8A6300; border: 1px solid #F3DE9A; }
    .skill-label { font-size: 0.78rem; color: var(--text-muted); margin-right: 4px; }
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


def verdict_class(verdict: str) -> str:
    return (verdict or "").lower().replace(" ", "-")


# Number of top cosine-ranked jobs sent to the LLM for reasoning + skill-gap
# analysis. Capped for free-tier speed/quota - the rest keep their cosine score.
AI_ANALYSIS_TOP_N = 10


@st.cache_data(show_spinner=False)
def _cached_analyze_match(candidate_hash: str, job_url: str, _profile_text: str, _job: dict) -> dict:
    """Cache key is (candidate_hash, job_url) only - the leading-underscore
    params carry the actual payload but are excluded from Streamlit's hash,
    since hashing a full CV + job description on every rerun is wasted work."""
    return ai.analyze_match(_profile_text, _job)


@st.cache_data(show_spinner=False)
def _cached_summarize_repo(username: str, repo_name: str, _repo: dict) -> dict:
    """Cache key is (username, repo_name) - re-analyzing the same repo across
    reruns/clicks reuses this instead of re-hitting Gemini."""
    return ai.summarize_repo(_repo)


@st.cache_data(show_spinner=False)
def _cached_extract_cv_skills(cv_text_hash: str, _cv_text: str) -> list:
    """Cache key is the CV text hash - re-parsing the same CV across reruns
    reuses this instead of re-hitting Gemini."""
    return ai.extract_cv_skills(_cv_text)


def add_skills(new_skills: list) -> None:
    """Merge new skills into the shared skills pool, case-insensitively
    deduped, preserving first-seen casing and order."""
    existing_lower = {s.lower() for s in st.session_state.skills}
    for raw in new_skills:
        s = (raw or "").strip()
        if s and s.lower() not in existing_lower:
            st.session_state.skills.append(s)
            existing_lower.add(s.lower())


def analyze_top_jobs(profile_text: str, jobs: list) -> list:
    """Run analyze_match on the top AI_ANALYSIS_TOP_N cosine-ranked jobs and
    re-sort that subset by adjusted_score. The remaining jobs are left as-is,
    appended after, still ordered by cosine match_score."""
    if not profile_text or not jobs:
        return jobs

    candidate_hash = hashlib.sha256(profile_text.encode("utf-8")).hexdigest()
    head, tail = jobs[:AI_ANALYSIS_TOP_N], jobs[AI_ANALYSIS_TOP_N:]

    analyzed = []
    for job in head:
        result = _cached_analyze_match(candidate_hash, job["url"], profile_text, job)
        job = dict(job)
        job.update(result)
        analyzed.append(job)

    analyzed.sort(key=lambda j: j["adjusted_score"], reverse=True)
    return analyzed + tail


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
st.session_state.setdefault("cv", None)
st.session_state.setdefault("jobs", [])
st.session_state.setdefault("profile_text", "")
st.session_state.setdefault("cover_letters", {})
st.session_state.setdefault("github_username", "")
st.session_state.setdefault("github_summary", "")
st.session_state.setdefault("github_repos", [])
st.session_state.setdefault("github_repo_analyses", {})
st.session_state.setdefault("projects", [])
st.session_state.setdefault("skills", [])
st.session_state.setdefault("cv_skills_hash", None)

with st.container(key="app-header"):
    logo_col, tagline_col = st.columns([1, 2.4], vertical_alignment="center")
    with logo_col:
        st.image("assets/logo.png", width=180)
    with tagline_col:
        st.markdown(
            '<div class="app-tagline-head">Your career copilot.</div>'
            '<div class="app-tagline-sub">Build your profile once. We analyze your experience and rank jobs that actually fit.</div>',
            unsafe_allow_html=True,
        )

# ---------------------------------------------------------------------------
# Step 1: CV upload
# ---------------------------------------------------------------------------
section_header("1. Get started")
st.caption("Upload your resume to build your AI profile.")
uploaded = st.file_uploader("Upload your CV", type=["pdf"], label_visibility="collapsed")

if uploaded is not None:
    st.session_state.cv = parse_cv(uploaded)

if st.session_state.cv:
    # Extract skills from the CV exactly once per distinct CV (keyed on a
    # hash of its text) - guards against re-running this on every unrelated
    # rerun (which would otherwise cost an API call every time, though
    # add_skills()'s own dedup would still keep the pool clean either way).
    cv_hash = hashlib.sha256(st.session_state.cv["raw_text"].encode("utf-8")).hexdigest()
    if cv_hash != st.session_state.cv_skills_hash:
        with st.spinner("Extracting skills from your CV..."):
            add_skills(_cached_extract_cv_skills(cv_hash, st.session_state.cv["raw_text"]))
        st.session_state.cv_skills_hash = cv_hash

    st.caption(f"Detected experience level from your CV: **{st.session_state.cv['experience_label']}**. "
               "This shapes match scoring below, in addition to any Experience level filter you pick.")
    with st.expander(f"Parsed CV ({st.session_state.cv['num_pages']} page(s)) preview"):
        st.text(st.session_state.cv["raw_text"][:2000] or "(no text extracted)")

# ---------------------------------------------------------------------------
# Step 1b: GitHub (optional) - adds real project evidence to the profile.
# Two-step flow: fetch the repo list first, then pick which ones are worth
# an AI's time (and a per-repo Gemini call) - so you get a breakdown for
# each project you care about instead of one blended summary.
# ---------------------------------------------------------------------------
st.markdown("**GitHub (optional)**: adds real project evidence to your profile.")
gh_col1, gh_col2 = st.columns([3, 1])
with gh_col1:
    github_username_input = st.text_input(
        "GitHub username", value=st.session_state.github_username,
        placeholder="e.g. octocat, @octocat, or a github.com/octocat URL",
        label_visibility="collapsed",
    )
with gh_col2:
    fetch_gh_clicked = st.button("Fetch repos", disabled=not github_username_input)

if fetch_gh_clicked:
    st.session_state.github_username = github_username_input
    with st.spinner(f"Fetching public repos for '{github_username_input}'..."):
        st.session_state.github_repos = fetch_github_repos(github_username_input)
    st.session_state.github_repo_analyses = {}
    st.session_state.github_summary = ""
    if not st.session_state.github_repos:
        st.warning("No public repos found for that username (or it doesn't exist). "
                   "Continuing without GitHub evidence.")

if st.session_state.github_repos:
    repo_by_name = {r["name"]: r for r in st.session_state.github_repos}
    repo_names = list(repo_by_name.keys())
    default_selection = [
        r["name"] for r in
        sorted(st.session_state.github_repos, key=lambda r: r["stars"], reverse=True)[:3]
    ]

    def _repo_label(name: str) -> str:
        r = repo_by_name[name]
        return f"{name} ({r['language'] or 'n/a'}, {r['stars']}★)"

    selected_repos = st.multiselect(
        "Select repos to analyze",
        repo_names,
        default=default_selection,
        format_func=_repo_label,
    )
    analyze_repos_clicked = st.button("Analyze selected repos", disabled=not selected_repos)

    if analyze_repos_clicked:
        analyses = {}
        with st.spinner(f"Analyzing {len(selected_repos)} repo(s) with AI..."):
            for name in selected_repos:
                repo = repo_by_name[name]
                readme = fetch_readme(st.session_state.github_username, name)
                repo_with_readme = {**repo, "readme": readme}
                result = _cached_summarize_repo(
                    st.session_state.github_username, name, repo_with_readme
                )
                analyses[name] = {**repo_with_readme, **result}
        st.session_state.github_repo_analyses = analyses
        st.session_state.github_summary = "\n".join(
            f"{name}: {a['summary']}" for name, a in analyses.items() if a["summary"]
        )
        # Every skill the AI actually found evidence of, across all analyzed
        # repos, flows straight into the shared skills pool below.
        for a in analyses.values():
            add_skills(a.get("skills") or [])

    if st.session_state.github_repo_analyses:
        st.caption("Analyzed projects (merged into your profile below):")
        for name, a in st.session_state.github_repo_analyses.items():
            with st.expander(f"{name} · {a['language'] or 'n/a'}, {a['stars']}★"):
                if a.get("description"):
                    st.caption(a["description"])
                st.write(a.get("summary") or "AI summary unavailable for this repo.")
                if a.get("skills"):
                    pills = "".join(
                        f'<span class="skill-pill neutral">{html.escape(s)}</span>'
                        for s in a["skills"]
                    )
                    st.markdown(pills, unsafe_allow_html=True)
                if a.get("url"):
                    st.markdown(f"[View on GitHub]({a['url']})")

# ---------------------------------------------------------------------------
# Step 1c: Manual project entry (optional) - for work not on GitHub or the CV.
# Collapsible since it's optional; the form stays open after each add (no
# rerun-collapse) so adding several projects back-to-back is one continuous
# flow, not a re-expand-every-time chore.
# ---------------------------------------------------------------------------
with st.expander("Add a project manually (optional)", expanded=bool(st.session_state.projects)):
    with st.form("add_project_form", clear_on_submit=True):
        proj_title = st.text_input("Project title")
        proj_description = st.text_area("Description", height=80)
        proj_skills = st.text_input("Skills / tags (comma-separated)")
        add_project_submitted = st.form_submit_button("Add project")

    if add_project_submitted:
        if proj_title.strip():
            st.session_state.projects.append({
                "title": proj_title.strip(),
                "description": proj_description.strip(),
                "skills": proj_skills.strip(),
            })
            if proj_skills.strip():
                add_skills(proj_skills.split(","))
        else:
            st.warning("Give the project a title before adding it.")

    if st.session_state.projects:
        st.caption(f"Your added projects ({len(st.session_state.projects)}):")
        for proj_idx, proj in enumerate(st.session_state.projects):
            proj_cols = st.columns([6, 1])
            with proj_cols[0]:
                skills_suffix = f" · _{html.escape(proj['skills'])}_" if proj.get("skills") else ""
                st.markdown(f"- **{html.escape(proj['title'])}**{skills_suffix}")
            with proj_cols[1]:
                if st.button("Remove", key=f"rm_project_{proj_idx}"):
                    st.session_state.projects.pop(proj_idx)
                    st.rerun()

# ---------------------------------------------------------------------------
# Step 1d: Shared skills pool - auto-fed by analyzed GitHub repos and by
# whatever's typed into a manual project's "Skills" field, and editable
# directly too. This is what actually gets listed in the candidate profile
# used for matching, on top of whatever's already in the prose above.
# ---------------------------------------------------------------------------
st.markdown("**Skills**")
with st.form("add_skill_form", clear_on_submit=True):
    skill_cols = st.columns([4, 1])
    with skill_cols[0]:
        new_skill_input = st.text_input(
            "Add a skill", placeholder="e.g. Python, Docker, SQL (comma-separated for multiple)",
            label_visibility="collapsed",
        )
    with skill_cols[1]:
        add_skill_submitted = st.form_submit_button("Add")

if add_skill_submitted and new_skill_input.strip():
    add_skills(new_skill_input.split(","))

if st.session_state.skills:
    # Each skill is its own small button ("skill ✕") in a horizontal flex
    # container - they hug together and wrap to the next line on their own,
    # unlike st.columns() which forces equal-width slots regardless of each
    # button's actual text length. Clicking one removes just that skill.
    with st.container(horizontal=True, gap="small"):
        for skill in st.session_state.skills:
            if st.button(f"{skill}  ✕", key=f"rm_skill_{skill}"):
                st.session_state.skills = [s for s in st.session_state.skills if s != skill]
                st.rerun()
else:
    st.caption("No skills yet. Add some above, analyze GitHub repos, or add a project.")

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
    st.markdown(
        '<div class="info-box">Upload a CV above to enable job search.</div>',
        unsafe_allow_html=True,
    )

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
        profile_text = build_profile_text(
            st.session_state.cv,
            github_summary=st.session_state.github_summary,
            projects=st.session_state.projects,
            skills=st.session_state.skills,
        )
        candidate_level = st.session_state.cv.get("level")
        with st.spinner("Scoring matches..."):
            ranked = rank_jobs(profile_text, fetched, candidate_level=candidate_level)
        if ai.is_configured():
            with st.spinner("Analyzing top matches with AI..."):
                ranked = analyze_top_jobs(profile_text, ranked)
        st.session_state.jobs = ranked
        st.session_state.profile_text = profile_text

# ---------------------------------------------------------------------------
# Step 3: Ranked results
# ---------------------------------------------------------------------------
if st.session_state.jobs:
    section_header("3. Ranked matches")
    candidate_hash = hashlib.sha256(st.session_state.profile_text.encode("utf-8")).hexdigest()
    for job_idx, job in enumerate(st.session_state.jobs):
        with st.container(border=True):
            # Once AI reasoning has run, its role-fit score replaces the raw
            # cosine score for display too, so the badge/bar agree with the
            # verdict and skill gap shown below it.
            score = job.get("adjusted_score", job["match_score"])
            tier = match_tier(score)
            # Job fields come from scraped external postings (untrusted) - escape
            # before interpolating into raw HTML to avoid stored XSS.
            title = html.escape(job["title"])
            company = html.escape(job["company"])
            location = html.escape(job["location"])
            source = html.escape(job["source"])
            salary = html.escape(job["salary"]) if job.get("salary") else None

            verdict = job.get("verdict")
            reason = job.get("reason")
            matched_skills = job.get("matched_skills") or []
            missing_skills = job.get("missing_skills") or []

            verdict_html = (
                f'<span class="verdict-badge {verdict_class(verdict)}">{html.escape(verdict)}</span>'
                if verdict else ""
            )
            reason_html = f'<div class="match-reason">{html.escape(reason)}</div>' if reason else ""

            pills_html = ""
            if matched_skills:
                pills_html += '<span class="skill-label">Has:</span>' + "".join(
                    f'<span class="skill-pill matched">{html.escape(s)}</span>' for s in matched_skills
                )
            if missing_skills:
                pills_html += '<span class="skill-label" style="margin-left:8px;">Missing:</span>' + "".join(
                    f'<span class="skill-pill missing">{html.escape(s)}</span>' for s in missing_skills
                )
            if pills_html:
                pills_html = f'<div style="margin-bottom:8px;">{pills_html}</div>'

            st.markdown(
                f'<span class="match-badge {tier}">{score}% match</span>'
                + verdict_html
                + f'<div class="job-title">{title}</div>'
                f'<div class="job-meta">{company} · {location} · {source}</div>'
                + (f'<div class="job-salary">{salary}</div>' if salary else "")
                + f'<div class="match-bar-track"><div class="match-bar-fill {tier}" style="width:{score}%"></div></div>'
                + reason_html
                + pills_html,
                unsafe_allow_html=True,
            )
            st.link_button("Apply / view listing", job["url"])

            # --- One-click cover letter (Step 2) ---------------------------
            # Isolated from the rest of the card: any failure here shows up
            # only inline in this job's text area, via write_cover_letter's
            # own error handling - it never raises up into the job list.
            cover_key = (candidate_hash, job["url"])
            if st.button("Generate cover letter", key=f"coverbtn_{job_idx}"):
                if cover_key not in st.session_state.cover_letters:
                    stream_slot = st.empty()
                    with stream_slot:
                        full_letter = st.write_stream(
                            ai.write_cover_letter(st.session_state.profile_text, job)
                        )
                    st.session_state.cover_letters[cover_key] = full_letter
                    stream_slot.empty()

            if cover_key in st.session_state.cover_letters:
                st.text_area(
                    "Cover letter (copy and edit as needed)",
                    value=st.session_state.cover_letters[cover_key],
                    height=240,
                    key=f"coverletter_{job_idx}",
                )
