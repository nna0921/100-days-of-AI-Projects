"""
profile.py
----------
Builds the candidate profile from a CV upload (Phase 1).

Phase 2 will extend this with manual project entries and GitHub repo
fetching, merged into the same profile dict.
"""

from __future__ import annotations

import io
from typing import Dict, List, Optional

import pdfplumber
import streamlit as st

from cv_experience import detect_experience


SAMPLE_CV_TEXT = """Anna Zubair
Machine Learning Engineer

SUMMARY
Machine learning engineer with 3 years of experience building and shipping production ML
systems, from data pipelines to deployed models. Comfortable across the full ML lifecycle:
data wrangling, model training, evaluation, and deployment.

WORK EXPERIENCE
Machine Learning Engineer, Northwind Analytics   Jun 2022 - Present
- Built and deployed a customer-churn prediction model (scikit-learn, XGBoost) serving
  real-time predictions via a FastAPI microservice, reducing churn by 12%.
- Designed a PyTorch-based recommendation model trained on user interaction data, improving
  click-through rate by 18% over the previous heuristic system.
- Owned the team's feature store and data pipelines (Python, pandas, Airflow, SQL).

Data Analyst, Northwind Analytics   Jul 2021 - Jun 2022
- Automated weekly reporting pipelines in Python, cutting manual analyst hours by 6/week.
- Built dashboards in SQL + Pandas for the growth team.

SKILLS
Python, PyTorch, TensorFlow, scikit-learn, XGBoost, pandas, NumPy, SQL, FastAPI, Docker,
Airflow, Git, AWS (S3, SageMaker), experiment tracking (MLflow), NLP basics (transformers,
embeddings).

PROJECTS
- Built and open-sourced a small NLP toolkit for sentiment classification using Hugging Face
  transformers, with a Streamlit demo UI.
- Kaggle competition: top 15% finish on a tabular data prediction challenge using LightGBM.

EDUCATION
B.S. Computer Science, State University   2017 - 2021
"""


def get_sample_cv() -> Dict:
    """A hand-written, known-good CV so the demo's wow moment happens in ~2
    seconds with zero upload risk - skips PDF parsing entirely."""
    experience = detect_experience(SAMPLE_CV_TEXT)
    return {"raw_text": SAMPLE_CV_TEXT.strip(), "num_pages": 1, **experience}


@st.cache_data(show_spinner="Parsing CV...")
def _parse_cv_bytes(data: bytes) -> Dict:
    """The actual PDF-parsing work, cached on the raw bytes so re-running
    the script (e.g. after clicking a filter) never re-parses an unchanged
    upload."""
    text_parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        num_pages = len(pdf.pages)
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)

    raw_text = "\n".join(text_parts).strip()
    experience = detect_experience(raw_text)
    return {
        "raw_text": raw_text,
        "num_pages": num_pages,
        **experience,
    }


def parse_cv(file) -> Dict:
    """Extract raw text from an uploaded PDF CV.

    Args:
        file: a file-like object from st.file_uploader (or an open file in
              "rb" mode for the sample profile).

    Returns:
        {
            "raw_text": str, "num_pages": int,
            "years": float,           # estimated total years of experience
            "level": str,             # "entry" | "junior" | "mid" | "senior"
            "experience_label": str,  # human label for the UI caption
        }
    """
    return _parse_cv_bytes(file.read())


def build_profile_text(
    cv: Optional[Dict],
    github_summary: str = "",
    projects: Optional[List[Dict]] = None,
    skills: Optional[List[str]] = None,
) -> str:
    """Flatten whatever profile pieces exist into one text blob used for both
    embedding (cosine ranking) and the AI match/cover-letter prompts.

    cv: parsed CV dict from parse_cv(), or None.
    github_summary: joined per-repo summaries from ai.summarize_repo(), or ""
        if GitHub wasn't used.
    projects: manually-added {"title", "description", "skills"} dicts.
    skills: the shared skills pool (from analyzed repos, project entries, and
        anything typed in directly) - listed explicitly so it counts as
        strong evidence in matching, not just buried in prose.
    """
    parts = []
    if cv and cv.get("raw_text"):
        parts.append(cv["raw_text"])

    if github_summary:
        parts.append(f"GitHub portfolio summary:\n{github_summary}")

    if projects:
        project_blocks = []
        for p in projects:
            block = f"Project: {p.get('title', '')}\n{p.get('description', '')}"
            if p.get("skills"):
                block += f"\nSkills: {p['skills']}"
            project_blocks.append(block)
        parts.append("Additional projects:\n\n" + "\n\n".join(project_blocks))

    if skills:
        parts.append("Skills: " + ", ".join(skills))

    return "\n\n".join(parts).strip()
