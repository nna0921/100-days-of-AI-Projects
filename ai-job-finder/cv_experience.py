"""
cv_experience.py
----------------
Estimate a candidate's experience level from raw CV text.

Returns a dict the app can drop straight into st.session_state.cv:

    {
        "years": float,           # best estimate of total years
        "level": str,             # "entry" | "junior" | "mid" | "senior"
                                  #   -> matches fetch_jobs(experience=...)
        "experience_label": str,  # human label for the UI caption
    }

Heuristics (in priority order):
  1. Explicit "X years of experience" phrases.
  2. Employment date ranges (2019-2023, "Jan 2020 - Present", etc.) summed up.
  3. Fresher/intern/new-grad keywords -> entry.
  4. Fallback: entry.

It's a heuristic, not truth — good enough to drive filtering and the UI caption.
"""

from __future__ import annotations

import re
from datetime import datetime

_CURRENT_YEAR = datetime.now().year


def _level_from_years(years: float) -> tuple[str, str]:
    """Map years of experience -> (machine level, human label)."""
    if years < 1:
        return "entry", "Fresher / Entry level (0-1 yrs)"
    if years < 2:
        return "junior", "Junior (1-2 yrs)"
    if years < 5:
        return "mid", f"Mid level (~{round(years)} yrs)"
    return "senior", f"Senior ({round(years)}+ yrs)"


def _explicit_years(text: str) -> float | None:
    """Find phrases like '3 years of experience' / '5+ yrs experience'."""
    best = None
    for m in re.finditer(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b[^.\n]{0,25}experience", text):
        val = float(m.group(1))
        best = val if best is None else max(best, val)
    return best


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# One endpoint of a date range: "Jan 2020", "January 2020", "03/2020",
# "2020-03", or a bare "2020". Captured as a single token to parse later.
# The month-name form only accepts REAL months so words like "Dev 2020" or
# "Tutor 2021" (job titles ending right before a year) aren't mistaken for dates.
_MONTH_NAME = (
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
)
_DATE = (
    rf"(?:{_MONTH_NAME}\.?\s+\d{{4}}|\d{{1,2}}[/-]\d{{4}}|\d{{4}}[/-]\d{{1,2}}|\d{{4}})"
)
_RANGE_RE = re.compile(
    rf"({_DATE})\s*(?:-|–|—|to|until)\s*({_DATE}|present|current|now|to date)",
    re.IGNORECASE,
)


def _parse_point(token: str) -> float | None:
    """Turn a date token into a decimal year (year + month/12). None if unparseable."""
    token = token.strip().lower()
    if token in {"present", "current", "now", "to date"}:
        return _CURRENT_YEAR + (datetime.now().month - 1) / 12.0

    # Month name + year, e.g. "jan 2020" / "january 2020"
    m = re.match(r"([a-z]{3,9})\.?\s+(\d{4})", token)
    if m and m.group(1)[:3] in _MONTHS:
        return int(m.group(2)) + (_MONTHS[m.group(1)[:3]] - 1) / 12.0

    # Numeric month/year "03/2020" or year/month "2020-03"
    m = re.match(r"(\d{1,2})[/-](\d{4})", token)
    if m:
        return int(m.group(2)) + (int(m.group(1)) - 1) / 12.0
    m = re.match(r"(\d{4})[/-](\d{1,2})", token)
    if m:
        return int(m.group(1)) + (int(m.group(2)) - 1) / 12.0

    # Bare year
    m = re.match(r"(\d{4})$", token)
    if m:
        return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Section scoping
# ---------------------------------------------------------------------------
# A CV's EDUCATION section routinely contains its own date range (e.g. a
# "Bachelor's ... 2022-2026" degree still in progress), and PROJECTS often has
# one too. If we sum every date range in the whole document, a final-year
# student's 4-year degree gets counted as 4 years of "experience" - worse
# than having no signal at all. So: find the work-history heading, only scan
# ranges between it and the next section heading, and only fall back to
# scanning the surrounding text if no such heading exists at all.
_WORK_HEADING_RE = re.compile(r"\b(professional\s+experiences?|work\s+experience|employment\s+history|experience)\b", re.IGNORECASE)
_STOP_HEADING_RE = re.compile(
    r"\b(education|projects?|skills?|certificat\w*|honou?rs?|awards?|publications?|"
    r"languages?|interests?|references?|activit\w*|summary|objective|contact|achievements?)\b",
    re.IGNORECASE,
)


def _is_heading_line(line: str) -> bool:
    """A short line that's all-uppercase where it has letters at all -
    the common resume convention for section headers (and company names,
    which is fine - we only act on ones matching a known keyword)."""
    letters = [c for c in line if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters) and len(line) <= 60


def _extract_experience_section(raw_text: str) -> str | None:
    """Return the text between a work-experience heading and the next section
    heading, or None if no work-experience heading is found."""
    lines = raw_text.splitlines()
    start_idx = None
    end_idx = len(lines)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or not _is_heading_line(stripped):
            continue
        if start_idx is None:
            if _WORK_HEADING_RE.search(stripped):
                start_idx = i + 1
        elif i > start_idx and _STOP_HEADING_RE.search(stripped):
            end_idx = i
            break

    if start_idx is None:
        return None
    return "\n".join(lines[start_idx:end_idx])


def _years_from_date_ranges(text: str) -> float | None:
    """
    Total professional experience from work-history date ranges.

    Extracts every "start - end" range (month-level when present), MERGES
    overlapping periods so concurrent roles aren't double-counted, then sums
    the merged spans. Returns None if no ranges are found.
    """
    intervals = []
    for m in _RANGE_RE.finditer(text):
        start = _parse_point(m.group(1))
        end = _parse_point(m.group(2))
        if start is None or end is None:
            continue
        if 1970 <= start <= _CURRENT_YEAR + 1 and end >= start:
            intervals.append((start, min(end, _CURRENT_YEAR + 1)))

    if not intervals:
        return None

    # Merge overlapping / touching intervals
    intervals.sort()
    merged = [list(intervals[0])]
    for s, e in intervals[1:]:
        if s <= merged[-1][1]:          # overlap
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    total = sum(e - s for s, e in merged)
    return min(total, 45.0)  # guard against absurd sums


def detect_experience(cv_text: str) -> dict:
    """Estimate experience level from CV text. Never raises; always returns the dict."""
    cv_text = cv_text or ""
    text = cv_text.lower()

    # 3. Obvious fresher signals short-circuit to entry
    fresher_signal = re.search(
        r"\b(fresher|fresh graduate|recent graduate|new grad|seeking (?:an )?internship|"
        r"final[- ]year student|final[- ]year project|aspiring)\b",
        text,
    )

    years = _explicit_years(text)
    if years is None:
        # Prefer scoping to the work-experience section if we can find one -
        # avoids counting the EDUCATION section's degree dates as
        # "experience". Only fall back to a whole-document scan when no
        # heading is found at all (e.g. a CV with no labeled sections).
        experience_section = _extract_experience_section(cv_text)
        years = _years_from_date_ranges(
            experience_section if experience_section is not None else cv_text
        )

    if years is None:
        years = 0.0 if fresher_signal else 0.0  # fallback -> entry

    # If explicit years is tiny but no strong signal, keep as-is.
    level, label = _level_from_years(years)

    # A clear fresher keyword overrides an inflated date-range guess.
    if fresher_signal and years < 2:
        level, label = "entry", "Fresher / Entry level (0-1 yrs)"

    return {"years": round(years, 1), "level": level, "experience_label": label}


if __name__ == "__main__":
    samples = {
        "explicit": "Software Engineer with 6 years of experience in Python and ML.",
        "work_history": "Data Analyst, Acme   Jan 2022 - Present\n"
                        "ML Intern, Foo   Jun 2021 - Dec 2021",
        "overlapping": "Freelance Dev   2020 - 2023\n"
                       "Part-time Tutor  2021 - 2022",  # should NOT sum to 4 yrs
        "months": "Backend Engineer   03/2019 - 09/2021",
        "fresher": "Final-year student and aspiring data scientist seeking an internship.",
        "empty": "",
    }
    for name, txt in samples.items():
        print(name, "->", detect_experience(txt))
