"""
profile.py
----------
Builds the candidate profile from a CV upload (Phase 1).

Phase 2 will extend this with manual project entries and GitHub repo
fetching, merged into the same profile dict.
"""

from __future__ import annotations

import io
from typing import Dict

import pdfplumber

from cv_experience import detect_experience


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
    data = file.read()
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


def build_profile_text(cv: Dict) -> str:
    """Flatten whatever profile pieces exist into one text blob for embedding.

    Phase 1: just the CV text. Phase 2 will append manual projects and
    GitHub-derived skills here too.
    """
    parts = []
    if cv and cv.get("raw_text"):
        parts.append(cv["raw_text"])
    return "\n\n".join(parts).strip()
