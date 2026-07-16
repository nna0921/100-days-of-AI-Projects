"""
Streamlit UI for the pipeline: Scraper -> Cleanup Agent (Roman Urdu + typo
normalization) -> Insight Agent (what's missing). Skinned to match
design_handoff_daraz_gap_finder/README.md's spec: dark pipeline tracker with
a live terminal, market-structure cards, a popularity-scored product table,
a missing-features accordion, a per-aspect sentiment heatmap, and product
concept cards.

Streamlit stays the only backend -- there's no separate frontend framework.
Rich sections are rendered as real HTML/CSS/JS via st.html(...,
unsafe_allow_javascript=True), which (unlike st.markdown) executes <script>
tags directly in the page (not a sandboxed iframe), giving genuine
count-up animation, a click-to-close accordion, and terminal auto-scroll.
Only the controls that need to round-trip to Python -- the search box,
submit button, and category switcher -- are native Streamlit widgets.
"""
import html as html_escape
import json
import os
import re
import subprocess
import sys
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from analysis import (
    discover_categories,
    estimated_reviews_per_month,
    popularity_score,
    seller_diversity,
)

PIPELINE_STEPS = [
    {"label": "Scraping Daraz", "script": "main_scraper.py"},
    {"label": "Cleaning reviews", "script": "cleanup_agent.py"},
    {"label": "Finding gaps", "script": "insight_agent.py"},
]

st.set_page_config(page_title="Daraz AI Product Finder", layout="wide")

PAGE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

html, body, .stApp, [class*="css"] { font-family:'Space Grotesk',Helvetica,sans-serif; }
.stApp { background:#f4f4f1; }
#MainMenu, div[data-testid="stDecoration"], header[data-testid="stHeader"], footer { visibility:hidden; height:0; }
.block-container { max-width:1240px !important; padding:28px 32px 72px !important; }

@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
@keyframes slideIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
@keyframes fadeUp{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
@keyframes barGrow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes popIn{from{opacity:0;transform:scale(.6)}to{opacity:1;transform:scale(1)}}

/* restyle native widgets to read as the mockup's search pill */
div[data-testid="stForm"] { border:none !important; padding:0 !important; background:transparent !important; }
div[data-testid="stForm"] div[data-testid="stHorizontalBlock"] { gap:10px !important; align-items:flex-end !important; }
div[data-testid="stTextInput"] { margin-bottom:0 !important; padding:0 !important; }
div[data-testid="stTextInput"] label { display:none !important; }
div[data-testid="stTextInput"] > div { border:none !important; background:transparent !important; padding:0 !important; }
div[data-testid="stTextInput"] input {
  font-family:'IBM Plex Mono',monospace !important; font-size:13.5px !important;
  height:42px !important; max-height:42px !important; box-sizing:border-box !important;
  border:1px solid #dcdcd4 !important; border-radius:10px !important;
  box-shadow:0 1px 2px rgba(20,22,30,.04) !important; padding:0 14px !important;
  background:#fff !important; color:#16181d !important;
}
/* Force orange button — target every known Streamlit button selector */
div[data-testid="stForm"] button,
div[data-testid="stForm"] .stButton button,
div[data-testid="stForm"] [data-testid="stButton"] button,
div[data-testid="stForm"] [data-testid="stFormSubmitButton"],
div[data-testid="stForm"] button[kind="formSubmit"],
div[data-testid="stForm"] .stFormSubmitButton,
.stButton button[kind="formSubmit"],
button.ef3psqc12,
[data-testid="stForm"] [data-testid="baseButton-secondaryFormSubmit"],
[data-testid="stForm"] [data-testid="baseButton-primaryFormSubmit"],
[data-testid="stForm"] button[class*="baseButton"] {
  background-color:#e2703a !important; color:#ffffff !important; border:none !important;
  border-radius:10px !important; height:42px !important; max-height:42px !important;
  box-sizing:border-box !important; padding:0 16px !important; width:100%;
  font:600 13px 'Space Grotesk',sans-serif !important; margin:0 !important;
}
div[data-testid="stForm"] button:hover,
[data-testid="stForm"] button[class*="baseButton"]:hover { background-color:#c95e2e !important; color:#ffffff !important; }
div[data-testid="stForm"] button p,
div[data-testid="stForm"] button span { color:#ffffff !important; }
div[data-testid="stForm"] div[data-testid="stButton"],
div[data-testid="stForm"] [data-testid="stFormSubmitButton"] { margin:0 !important; padding:0 !important; }

div[data-testid="stSelectbox"] label {
  font:500 11px 'IBM Plex Mono',monospace !important; color:#8a8a82 !important;
  letter-spacing:.08em; text-transform:uppercase;
}
/* the closed select box */
div[data-baseweb="select"] > div {
  background:#fff !important; border-color:#dcdcd4 !important; color:#16181d !important;
}
div[data-baseweb="select"] span, div[data-baseweb="select"] input { color:#16181d !important; }
/* the open dropdown menu is rendered in a portal outside .stApp, so it
   needs its own (unscoped) rules or it inherits the browser/OS dark-mode
   colors instead of this page's light theme */
ul[role="listbox"] { background:#fff !important; }
li[role="option"] { background:#fff !important; color:#16181d !important; }
li[role="option"]:hover, li[aria-selected="true"] { background:#e7edfb !important; color:#16181d !important; }
</style>
"""

def _load_logo_b64():
    """Load assets/logo.png and return a data-URI string for embedding in HTML."""
    import base64 as _b64
    logo_path = os.path.join(os.path.dirname(__file__), "assets", "logo.png")
    with open(logo_path, "rb") as f:
        return "data:image/png;base64," + _b64.b64encode(f.read()).decode()

_LOGO_DATA_URI = _load_logo_b64()

HEADER_HTML = f"""
<div style="display:flex;align-items:center;gap:16px;padding:2px 0 18px">
  <img src="{_LOGO_DATA_URI}" alt="DarazHunt logo" style="height:120px;width:auto;object-fit:contain;background:transparent;border:none" />
  <div>
    <div style="font-size:20px;font-weight:700;letter-spacing:-.01em">Daraz AI Product Finder</div>
    <div style="font-size:11.5px;color:#8a8a82;font-family:'IBM Plex Mono',monospace">scrape &rarr; clean &rarr; find gaps</div>
  </div>
</div>
"""


def esc(s):
    return html_escape.escape(str(s), quote=True)


def slugify(text):
    text = text.strip().lower().replace("_", "-")
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text).strip("-")
    return text


@st.cache_data
def load_json(path):
    return json.load(open(path, encoding="utf-8"))


def classify_log_color(line):
    if line.startswith("$"):
        return "#6b6e62"
    if line.strip().startswith("WARN"):
        return "#a05c17"
    if "Saved" in line or line.strip().startswith("Done."):
        return "#2f7a4d"
    return "#4d5044"


def step_states(step_idx, failed_idx):
    states = []
    for i in range(3):
        if failed_idx == i:
            states.append("failed")
        elif failed_idx is not None and i > failed_idx:
            states.append("pending")
        elif step_idx > i or (step_idx >= 3):
            states.append("done")
        elif step_idx == i:
            states.append("active")
        else:
            states.append("pending")
    return states


def render_pipeline_html(slug, log_lines, step_idx, failed_idx, running):
    states = step_states(step_idx, failed_idx)
    style_map = {
        "pending": {"border": "#e2e2dc", "bg": "#f7f7f4", "dotBg": "#dcdcd4", "dotColor": "#8a8a82",
                    "labelColor": "#8a8a82", "anim": "none"},
        "active": {"border": "#b9c8f0", "bg": "#e7edfb", "dotBg": "#2f5fd0", "dotColor": "#fff",
                   "labelColor": "#16181d", "anim": "pulse 1.1s infinite"},
        "done": {"border": "#d4e6d7", "bg": "#edf5ee", "dotBg": "#2f7a4d", "dotColor": "#fff",
                 "labelColor": "#16181d", "anim": "none"},
        "failed": {"border": "#f0c9bd", "bg": "#fbeee9", "dotBg": "#b04b3a", "dotColor": "#fff",
                   "labelColor": "#16181d", "anim": "none"},
    }
    icons = {"pending": None, "active": "&#9679;", "done": "&#10003;", "failed": "&#10005;"}

    if failed_idx is not None:
        status_text, status_color = "FAILED", "#b04b3a"
    elif running:
        status_text, status_color = "RUNNING", "#a05c17"
    elif step_idx >= 3:
        status_text, status_color = "COMPLETE", "#2f7a4d"
    else:
        status_text, status_color = "", "#2f7a4d"

    cards = []
    for i, s in enumerate(PIPELINE_STEPS):
        sty = style_map[states[i]]
        icon = icons[states[i]] or str(i + 1)
        cards.append(f"""
        <div style="border:1px solid {sty['border']};background:{sty['bg']};border-radius:10px;padding:12px 14px;display:flex;align-items:center;gap:10px">
          <div style="width:22px;height:22px;border-radius:50%;display:grid;place-items:center;font:600 11px 'IBM Plex Mono',monospace;background:{sty['dotBg']};color:{sty['dotColor']};animation:{sty['anim']}">{icon}</div>
          <div>
            <div style="font:600 12.5px 'Space Grotesk',sans-serif;color:{sty['labelColor']}">{esc(s['label'])}</div>
            <div style="font:400 10.5px 'IBM Plex Mono',monospace;color:#8a8a82">{esc(s['script'])}</div>
          </div>
        </div>""")

    lines_html = "".join(
        f'<div style="color:{ln["color"]};animation:slideIn .2s ease">'
        f'<span style="color:#a6a69e">{esc(ln["time"])}</span>&nbsp;&nbsp;{esc(ln["text"])}</div>'
        for ln in log_lines[-80:]
    )
    cursor = '<div style="color:#8a8a82;animation:pulse 1.2s infinite">&#9611;</div>' if running else ""

    return f"""
    {PAGE_CSS}
    <div style="margin-top:6px;background:#fff;border:1px solid #e2e2dc;border-radius:14px;padding:20px 22px;box-shadow:0 1px 2px rgba(20,22,30,.03);animation:slideIn .3s ease">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
        <div style="font:600 12px 'IBM Plex Mono',monospace;color:#8a8a82;letter-spacing:.08em">PIPELINE &mdash; {esc(slug)}</div>
        <div style="font:500 11.5px 'IBM Plex Mono',monospace;color:{status_color}">{status_text}</div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:16px">
        {''.join(cards)}
      </div>
      <div id="terminal-box" style="background:#f7f7f4;border:1px solid #eeeee9;border-radius:10px;padding:14px 16px;height:150px;overflow-y:auto;font:400 11.5px/1.75 'IBM Plex Mono',monospace;color:#4d5044">
        {lines_html}{cursor}
      </div>
    </div>
    <script>
      (function() {{
        var box = document.getElementById('terminal-box');
        if (box) box.scrollTop = box.scrollHeight;
      }})();
    </script>
    """


def compute_heat(v):
    if v is None:
        return {"bg": "#f4f4f1", "fg": "#c9c9c1"}
    t = (v - 1) / 9
    hue = 25 + t * 120
    lightness = 0.92 - t * 0.14
    chroma = 0.06 + t * 0.06
    fg = "#173322" if t > 0.45 else "#4d2a1a"
    return {"bg": f"oklch({lightness:.3f} {chroma:.3f} {hue:.1f})", "fg": fg}


def render_dashboard_html(data):
    slug = data["slug"]
    m = data["market"]
    market_bg = "#fbf3e7" if m["dominated"] else "#edf5ee"
    market_border = "#eeddc2" if m["dominated"] else "#d4e6d7"
    market_color = "#a05c17" if m["dominated"] else "#2f7a4d"
    market_icon = "&#128274;" if m["dominated"] else "&#127793;"
    market_title = "Seller-dominated market" if m["dominated"] else "Fragmented market"
    if m["dominated"]:
        market_desc = (f"{m['num_products']} products come from only {m['num_sellers']} seller(s), "
                        f"with the top seller holding {m['top_share']:.0%} of total review volume. "
                        "Harder to enter &mdash; incumbents own the review history.")
    else:
        market_desc = (f"{m['num_products']} products spread across {m['num_sellers']} sellers, "
                        f"top seller holds just {m['top_share']:.0%} of review volume. "
                        "No incumbent moat &mdash; easier to enter as a new seller.")

    metrics = [
        {"label": "PRODUCTS", "target": m["num_products"], "suffix": "", "sub": "scraped this run"},
        {"label": "DISTINCT SELLERS", "target": m["num_sellers"], "suffix": "", "sub": "in this category"},
        {"label": "TOP SELLER SHARE", "target": round(m["top_share"] * 100), "suffix": "%",
         "sub": "of total review volume"},
    ]
    metric_cards = []
    for i, mt in enumerate(metrics):
        delay = f"{0.08 + i * 0.09:.2f}s"
        metric_cards.append(f"""
        <div class="metric-card" style="background:#fff;border:1px solid #e2e2dc;border-radius:14px;padding:18px 20px;box-shadow:0 1px 2px rgba(20,22,30,.03);animation:fadeUp .5s cubic-bezier(.2,.7,.3,1) both;animation-delay:{delay};transition:transform .2s,box-shadow .2s">
          <div style="font:500 10.5px 'IBM Plex Mono',monospace;color:#8a8a82;letter-spacing:.08em;margin-bottom:10px">{esc(mt['label'])}</div>
          <div class="count-up" data-target="{mt['target']}" data-suffix="{esc(mt['suffix'])}" style="font-size:32px;font-weight:700;letter-spacing:-.02em;line-height:1;font-variant-numeric:tabular-nums">0{esc(mt['suffix'])}</div>
          <div style="font-size:11.5px;color:#8a8a82;margin-top:8px">{esc(mt['sub'])}</div>
        </div>""")

    prod_rows = []
    for i, p in enumerate(data["products"]):
        delay = f"{0.15 + i * 0.06:.2f}s"
        prod_rows.append(f"""
        <div class="prod-row" style="display:grid;grid-template-columns:1fr 64px 46px 60px;gap:0 12px;align-items:center;padding:9px 2px;border-bottom:1px solid #f2f2ee;cursor:default;animation:fadeUp .45s cubic-bezier(.2,.7,.3,1) both;animation-delay:{delay};transition:background .15s,transform .15s">
          <div style="min-width:0">
            <div style="font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{esc(p['name'])}</div>
            <div style="height:5px;border-radius:3px;background:#eeeee9;margin-top:6px;overflow:hidden"><div style="height:100%;border-radius:3px;background:{p['bar_color']};width:{p['bar_w']}%;transform-origin:left;animation:barGrow .9s cubic-bezier(.2,.7,.3,1) both;animation-delay:{delay}"></div></div>
          </div>
          <div style="text-align:right;font:500 12px 'IBM Plex Mono',monospace;color:#4d5044">{esc(p['price'])}</div>
          <div style="text-align:right;font:500 12px 'IBM Plex Mono',monospace;color:#4d5044">{esc(p['rating'])}</div>
          <div style="text-align:right;font:600 13px 'IBM Plex Mono',monospace;color:{p['score_color']}">{esc(p['score'])}</div>
        </div>""")

    gap_cards = []
    max_gap = max([g["evidence_count"] for g in data["gaps"]], default=1) or 1
    for i, g in enumerate(data["gaps"]):
        delay = f"{0.2 + i * 0.08:.2f}s"
        bar_w = round(100 * g["evidence_count"] / max_gap)
        quotes_html = "".join(
            f'<div class="gap-quote" style="font-size:11.5px;color:#6b6e62;font-style:italic;'
            f'border-left:2px solid #e2e2dc;padding-left:10px;line-height:1.5">&ldquo;{esc(q)}&rdquo;</div>'
            for q in g.get("example_quotes", [])[:3]
        )
        open_style = "display:flex" if i == 0 else "display:none"
        gap_cards.append(f"""
        <div class="gap-card" style="border:1px solid #eeeee9;border-radius:10px;padding:12px 14px;cursor:pointer;animation:fadeUp .45s cubic-bezier(.2,.7,.3,1) both;animation-delay:{delay};transition:border-color .15s,transform .15s,box-shadow .2s">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:10px">
            <div style="font-size:13px;font-weight:600">{esc(g['feature'])}</div>
            <div style="font:500 11px 'IBM Plex Mono',monospace;color:#8a8a82;white-space:nowrap">{g['evidence_count']} reviews</div>
          </div>
          <div style="height:5px;border-radius:3px;background:#eeeee9;margin-top:8px;overflow:hidden"><div style="height:100%;background:#e2703a;border-radius:3px;width:{bar_w}%;transform-origin:left;animation:barGrow .9s cubic-bezier(.2,.7,.3,1) both;animation-delay:{delay}"></div></div>
          <div class="gap-quotes" style="margin-top:10px;flex-direction:column;gap:6px;{open_style}">
            {quotes_html}
          </div>
        </div>""")

    aspects = data["aspects"]
    heat_headers = "".join(
        f'<div style="font:500 10.5px \'IBM Plex Mono\',monospace;color:#8a8a82;text-align:center;padding:6px 2px;letter-spacing:.03em">{esc(a)}</div>'
        for a in aspects
    )
    heat_rows = []
    for ri, row in enumerate(data["score_rows"]):
        cells = []
        for ci, c in enumerate(row["cells"]):
            delay = f"{0.1 + ri * 0.05 + ci * 0.035:.3f}s"
            flag_badge = ('<span style="position:absolute;top:3px;right:5px;font-size:9px">&#9888;</span>'
                          if c["flag"] else "")
            cells.append(f"""
            <div title="{esc(c['tip'])}" style="height:38px;border-radius:7px;display:grid;place-items:center;font:600 12.5px 'IBM Plex Mono',monospace;background:{c['bg']};color:{c['fg']};cursor:default;position:relative;animation:popIn .4s cubic-bezier(.3,1.4,.5,1) both;animation-delay:{delay};transition:transform .12s" class="heat-cell">{c['label']}{flag_badge}</div>""")
        heat_rows.append(f"""
        <div style="display:contents">
          <div style="font-size:12px;font-weight:500;display:flex;align-items:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-right:8px">{esc(row['name'])}</div>
          {''.join(cells)}
        </div>""")
    n_aspects = max(len(aspects), 1)

    concept_colors = [
        {"border": "linear-gradient(180deg,#2f5fd0,#7f9ce6)", "label": "#2f5fd0", "badge_bg": "#e7edfb"},
        {"border": "linear-gradient(180deg,#e2703a,#f0a87c)", "label": "#c2410c", "badge_bg": "#fdf0e7"},
        {"border": "linear-gradient(180deg,#2f7a4d,#6bc48d)", "label": "#2f7a4d", "badge_bg": "#edf5ee"},
    ]
    concept_cards = []
    for i, c in enumerate(data["concepts"]):
        delay = f"{0.2 + i * 0.12:.2f}s"
        cc = concept_colors[i % len(concept_colors)]
        concept_cards.append(f"""
        <div class="concept-card" style="background:#fff;color:#16181d;border:1px solid #e2e2dc;border-radius:14px;padding:20px 22px 20px 26px;display:flex;flex-direction:column;gap:10px;box-shadow:0 1px 2px rgba(20,22,30,.03);animation:fadeUp .55s cubic-bezier(.2,.7,.3,1) both;animation-delay:{delay};transition:transform .2s,box-shadow .2s;overflow:hidden;position:relative">
          <div style="position:absolute;top:0;left:0;width:4px;height:100%;background:{cc['border']}"></div>
          <div style="display:flex;align-items:center;gap:8px">
            <span style="font:600 10.5px 'IBM Plex Mono',monospace;color:{cc['label']};background:{cc['badge_bg']};border-radius:5px;padding:3px 8px;letter-spacing:.1em">CONCEPT {i+1:02d}</span>
          </div>
          <div style="font-size:15.5px;font-weight:700;line-height:1.3;color:#16181d">{esc(c['concept'])}</div>
          <div style="font-size:12px;line-height:1.55;color:#6b6e62">{esc(c['rationale'])}</div>
        </div>""")

    top_html = f"""
    {PAGE_CSS}
    <style>
      .prod-row:hover {{ background:#fafaf7; transform:translateX(3px); }}
      .metric-card:hover {{ transform:translateY(-2px); box-shadow:0 6px 18px rgba(20,22,30,.08); }}
      .gap-card:hover {{ border-color:#c9d6f2 !important; transform:translateY(-1px); box-shadow:0 4px 12px rgba(20,22,30,.06); }}
      .heat-cell:hover {{ outline:2px solid #2f5fd0; outline-offset:-2px; transform:scale(1.08); }}
      .concept-card:hover {{ transform:translateY(-3px); box-shadow:0 8px 24px rgba(20,22,30,.1); border-color:#c9d6f2 !important; }}
    </style>

    <div style="display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin:14px 0 18px">
      <div>
        <div style="font:500 11px 'IBM Plex Mono',monospace;color:#8a8a82;letter-spacing:.1em;margin-bottom:6px">VIEWING CATEGORY</div>
        <div style="display:flex;align-items:center;gap:12px">
          <h1 style="margin:0;font-size:30px;font-weight:700;letter-spacing:-.02em">{esc(data['category_title'])}</h1>
          <span style="font:500 11px 'IBM Plex Mono',monospace;color:#2f5fd0;background:#e7edfb;border-radius:6px;padding:4px 9px">{esc(slug)}</span>
        </div>
      </div>
      <div style="font:400 12px 'IBM Plex Mono',monospace;color:#8a8a82">last run &middot; {esc(data['last_run'])}</div>
    </div>

    <div style="display:grid;grid-template-columns:1.6fr 1fr 1fr 1fr;gap:14px;margin-bottom:14px">
      <div style="background:{market_bg};border:1px solid {market_border};border-radius:14px;padding:18px 20px;animation:fadeUp .5s cubic-bezier(.2,.7,.3,1) both">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <span style="font-size:15px">{market_icon}</span>
          <span style="font:700 14px 'Space Grotesk',sans-serif;color:{market_color}">{market_title}</span>
        </div>
        <div style="font-size:12.5px;line-height:1.55;color:#4d5044">{market_desc}</div>
      </div>
      {''.join(metric_cards)}
    </div>

    <details style="background:#fff;border:1px solid #e2e2dc;border-radius:14px;margin-bottom:14px;box-shadow:0 1px 2px rgba(20,22,30,.03)">
      <summary style="cursor:pointer;padding:14px 20px;font-size:13px;font-weight:600;list-style:none;display:flex;align-items:center;gap:8px">
        <span style="font:400 11px 'IBM Plex Mono',monospace;color:#8a8a82">&#9654;</span>
        Seller breakdown <span style="font:400 11.5px 'IBM Plex Mono',monospace;color:#8a8a82;font-weight:400">&middot; {len(data['seller_rows'])} seller(s)</span>
      </summary>
      <div style="padding:0 20px 18px">
        <div style="display:grid;grid-template-columns:1fr 100px 120px;gap:0 12px;font:500 10px 'IBM Plex Mono',monospace;color:#a6a69e;letter-spacing:.08em;padding:8px 2px;border-bottom:1px solid #eeeee9">
          <div>SELLER</div><div style="text-align:right">PRODUCTS</div><div style="text-align:right">TOTAL REVIEWS</div>
        </div>
        {''.join(
          f'<div style="display:grid;grid-template-columns:1fr 100px 120px;gap:0 12px;padding:8px 2px;border-bottom:1px solid #f2f2ee;font-size:12.5px">'
          f'<div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{esc(s["seller"])}</div>'
          f'<div style="text-align:right;font-family:\'IBM Plex Mono\',monospace;color:#4d5044">{s["products"]}</div>'
          f'<div style="text-align:right;font-family:\'IBM Plex Mono\',monospace;color:#4d5044">{s["total_reviews"]:,}</div>'
          f'</div>'
          for s in data["seller_rows"]
        )}
      </div>
    </details>
    <style>details > summary::-webkit-details-marker {{ display:none; }}
    details[open] summary span:first-child {{ transform:rotate(90deg); display:inline-block; }}</style>

    <div style="display:grid;grid-template-columns:1.25fr 1fr;gap:14px;align-items:start">
      <div style="background:#fff;border:1px solid #e2e2dc;border-radius:14px;padding:20px 22px;box-shadow:0 1px 2px rgba(20,22,30,.03)">
        <div style="font-size:16px;font-weight:700;margin-bottom:4px">Popular products</div>
        <div style="font-size:11.5px;color:#8a8a82;line-height:1.5;margin-bottom:16px">Composite score: review count &middot; velocity &middot; avg rating &middot; consistency (z-weighted). A proxy, not sales.</div>
        <div style="display:grid;grid-template-columns:1fr 64px 46px 60px;gap:0 12px;font:500 10px 'IBM Plex Mono',monospace;color:#a6a69e;letter-spacing:.08em;padding:0 2px 8px;border-bottom:1px solid #eeeee9">
          <div>PRODUCT</div><div style="text-align:right">PRICE</div><div style="text-align:right">&#9733;</div><div style="text-align:right">SCORE</div>
        </div>
        {''.join(prod_rows)}
        <div style="font:400 10.5px 'IBM Plex Mono',monospace;color:#a6a69e;margin-top:12px">est. reviews/mo from earliest scraped review date &middot; sample-limited</div>
      </div>

      <div style="background:#fff;border:1px solid #e2e2dc;border-radius:14px;padding:20px 22px;box-shadow:0 1px 2px rgba(20,22,30,.03)">
        <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:4px">
          <div style="font-size:16px;font-weight:700">Missing features</div>
          <div style="font:500 11px 'IBM Plex Mono',monospace;color:#c2410c;background:#fdf0e7;border-radius:5px;padding:2px 7px">{len(data['gaps'])} gaps</div>
        </div>
        <div style="font-size:11.5px;color:#8a8a82;margin-bottom:16px">What buyers ask for that no product delivers</div>
        <div style="display:flex;flex-direction:column;gap:10px">
          {''.join(gap_cards)}
        </div>
      </div>
    </div>

    <script>
      (function() {{
        document.querySelectorAll('.count-up').forEach(function(el) {{
          var target = parseFloat(el.getAttribute('data-target')) || 0;
          var suffix = el.getAttribute('data-suffix') || '';
          var start = performance.now(), dur = 1000;
          function frame(t) {{
            var p = Math.min((t - start) / dur, 1);
            var eased = 1 - Math.pow(1 - p, 3);
            el.textContent = Math.round(target * eased) + suffix;
            if (p < 1) requestAnimationFrame(frame);
          }}
          requestAnimationFrame(frame);
        }});
        document.querySelectorAll('.gap-card').forEach(function(card) {{
          card.addEventListener('click', function() {{
            var quotes = card.querySelector('.gap-quotes');
            var isOpen = quotes.style.display === 'flex';
            document.querySelectorAll('.gap-quotes').forEach(function(q) {{ q.style.display = 'none'; }});
            quotes.style.display = isOpen ? 'none' : 'flex';
          }});
        }});
      }})();
    </script>
    """

    bottom_html = f"""
    <div style="background:#fff;border:1px solid #e2e2dc;border-radius:14px;padding:20px 22px;box-shadow:0 1px 2px rgba(20,22,30,.03)">
      <div style="font-size:16px;font-weight:700;margin-bottom:4px">Product scorecard</div>
      <div style="font-size:11.5px;color:#8a8a82;margin-bottom:16px">Aspects discovered from reviews, each product scored 1&ndash;10 by sentiment. Blank = not enough mentions.</div>
      <div style="overflow-x:auto">
        <div style="display:grid;grid-template-columns:220px repeat({n_aspects}, minmax(86px,1fr));gap:4px;min-width:760px">
          <div></div>
          {heat_headers}
          {''.join(heat_rows)}
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:16px;margin-top:14px;font:400 10.5px 'IBM Plex Mono',monospace;color:#8a8a82">
        <div style="display:flex;align-items:center;gap:6px"><div style="width:34px;height:8px;border-radius:4px;background:linear-gradient(90deg,#e5484d,#f0b429,#30a46c)"></div>1 &rarr; 10</div>
        <div>&#9888; local sentiment check disagrees with score &mdash; worth a manual look</div>
      </div>
    </div>

    <div style="margin-top:14px">
      <div style="display:flex;align-items:baseline;gap:10px;margin:24px 0 14px">
        <div style="font-size:16px;font-weight:700">Product concepts nobody's selling</div>
        <div style="font:400 11.5px 'IBM Plex Mono',monospace;color:#8a8a82">synthesized from the gaps above</div>
      </div>
      <div style="display:grid;grid-template-columns:repeat({min(len(data['concepts']), 3) or 1},1fr);gap:14px">
        {''.join(concept_cards)}
      </div>
    </div>
    """

    return top_html, bottom_html


def build_dashboard_data(category_slug, dataset, insights):
    seller_rows, num_products, num_sellers, top_share, dominated = seller_diversity(dataset)

    scores = popularity_score(dataset)
    score_vals = [float(s) for s in scores]
    smin, smax = min(score_vals, default=0), max(score_vals, default=0)
    products = []
    for p, score in sorted(zip(dataset, score_vals), key=lambda x: -x[1]):
        try:
            price_num = int(float(p.get("price") or 0))
            price_str = f"Rs. {price_num:,}"
        except (TypeError, ValueError):
            price_str = "—"
        try:
            rating_str = f"{float(p.get('rating') or 0):.1f}"
        except (TypeError, ValueError):
            rating_str = "—"
        bar_w = 8 + 92 * (score - smin) / (smax - smin) if smax > smin else 50
        products.append({
            "name": p["product_name"][:60],
            "price": price_str,
            "rating": rating_str,
            "score": ("+" if score >= 0 else "") + f"{score:.2f}",
            "score_raw": round(score, 3),
            "score_color": "#2f7a4d" if score >= 1 else ("#16181d" if score >= 0 else "#b04b3a"),
            "bar_color": "#2f5fd0" if score >= 0 else "#c9c9c1",
            "bar_w": round(bar_w, 1),
        })

    gaps = (insights or {}).get("missing_features") or []

    aspects = (insights or {}).get("discovered_aspects") or []
    score_rows = []
    for prod in (insights or {}).get("per_product_scorecard") or []:
        lookup = {a["aspect"]: a for a in prod.get("aspect_scores", [])}
        cells = []
        for aspect in aspects:
            a = lookup.get(aspect)
            v = a["score"] if a and a.get("score") else None
            heat = compute_heat(v)
            flag = bool(a and (a.get("sentiment_check") or {}).get("disagreement"))
            tip = f"{prod['product_name']} — {aspect}: {v if v is not None else 'n/a'}/10"
            if flag:
                tip += " · sentiment check disagrees"
            cells.append({"label": str(v) if v is not None else "", "bg": heat["bg"], "fg": heat["fg"],
                          "flag": flag, "tip": tip})
        score_rows.append({"name": prod["product_name"][:40], "cells": cells})

    concepts = (insights or {}).get("product_concepts") or []

    dataset_path = f"output/raw/daraz_reviews_dataset{'' if category_slug == 'wireless-earbuds' else '_' + category_slug}.json"
    try:
        last_run = datetime.fromtimestamp(os.path.getmtime(dataset_path)).strftime("%b %-d, %H:%M")
    except OSError:
        last_run = "unknown"

    return {
        "slug": category_slug,
        "category_title": category_slug.replace("-", " ").title(),
        "last_run": last_run,
        "market": {"dominated": dominated, "num_products": num_products,
                   "num_sellers": num_sellers, "top_share": top_share},
        "seller_rows": seller_rows,
        "products": products,
        "gaps": gaps,
        "aspects": aspects,
        "score_rows": score_rows,
        "concepts": concepts,
    }


def run_pipeline_live(category_slug, placeholder):
    env = dict(os.environ)
    env["DARAZ_CATEGORY"] = category_slug
    log_lines = []
    failed_idx = None

    def render(step_idx, running):
        placeholder.empty()
        with placeholder:
            st.html(render_pipeline_html(category_slug, log_lines, step_idx, failed_idx, running),
                    unsafe_allow_javascript=True)

    for step_idx, step in enumerate(PIPELINE_STEPS):
        now = datetime.now().strftime("%H:%M:%S")
        log_lines.append({"time": now, "text": f"$ python {step['script']}", "color": "#6b6e62"})
        render(step_idx, True)

        proc = subprocess.Popen(
            [sys.executable, step["script"]], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        for line in proc.stdout:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            log_lines.append({"time": datetime.now().strftime("%H:%M:%S"),
                              "text": line, "color": classify_log_color(line)})
            render(step_idx, True)
        proc.wait()

        if proc.returncode != 0:
            failed_idx = step_idx
            log_lines.append({"time": datetime.now().strftime("%H:%M:%S"),
                              "text": f"exited with code {proc.returncode}", "color": "#b04b3a"})
            render(step_idx, False)
            return False

    log_lines.append({"time": datetime.now().strftime("%H:%M:%S"),
                      "text": "pipeline complete", "color": "#2f7a4d"})
    render(3, False)
    return True


st.markdown(PAGE_CSS, unsafe_allow_html=True)
st.html(HEADER_HTML)

with st.form("search_form", clear_on_submit=False):
    c1, c2 = st.columns([5, 1], gap="small")
    with c1:
        new_category_input = st.text_input(
            "Daraz category slug", placeholder="Daraz category slug — e.g. laptops, skincare",
            label_visibility="collapsed")
    with c2:
        find_clicked = st.form_submit_button("Find gaps", use_container_width=True)

if find_clicked and new_category_input.strip():
    slug = slugify(new_category_input)
    tracker_slot = st.empty()
    if run_pipeline_live(slug, tracker_slot):
        load_json.clear()
        st.session_state["active_category"] = slug
        st.rerun()

available_categories = discover_categories()
if not available_categories:
    st.info("No data yet — enter a category slug above and click **Find gaps**.")
    st.stop()

default_category = st.session_state.get("active_category", sorted(available_categories)[0])
if default_category not in available_categories:
    default_category = sorted(available_categories)[0]

category_slug = st.selectbox(
    "Viewing category", sorted(available_categories),
    index=sorted(available_categories).index(default_category),
    format_func=lambda s: s.replace("-", " ").title(),
)
st.session_state["active_category"] = category_slug

suffix = "" if category_slug == "wireless-earbuds" else f"_{category_slug}"
DATASET_FILE = f"output/raw/daraz_reviews_dataset{suffix}.json"
INSIGHTS_FILE = f"output/insights/insights{suffix}.json"

dataset = load_json(DATASET_FILE)
try:
    insights = load_json(INSIGHTS_FILE)
except FileNotFoundError:
    insights = None

dashboard_data = build_dashboard_data(category_slug, dataset, insights)
top_html, bottom_html = render_dashboard_html(dashboard_data)
st.html(top_html, unsafe_allow_javascript=True)

chart_df = pd.DataFrame([
    {"product": p["name"], "popularity_score": p["score_raw"]} for p in dashboard_data["products"]
]).sort_values("popularity_score", ascending=True)
fig = px.bar(
    chart_df, x="popularity_score", y="product", orientation="h",
    labels={"popularity_score": "Popularity score (z-weighted)", "product": ""},
    color="popularity_score", color_continuous_scale=["#c9c9c1", "#2f5fd0"],
)
fig.update_layout(
    height=max(320, 32 * len(chart_df)), showlegend=False, coloraxis_showscale=False,
    plot_bgcolor="#fff", paper_bgcolor="#fff",
    font=dict(family="IBM Plex Mono, monospace", color="#16181d", size=12),
    margin=dict(l=0, r=10, t=14, b=0),
)
fig.update_xaxes(gridcolor="#eeeee9", zerolinecolor="#dcdcd4")
fig.update_yaxes(gridcolor="#fff")
with st.container(border=True):
    st.markdown("**Popularity ranking**")
    st.caption(f"All {len(chart_df)} products, sorted by composite popularity score.")
    st.plotly_chart(fig, use_container_width=True)

st.html(bottom_html, unsafe_allow_javascript=True)

if not insights:
    st.info(f"No insights yet for this category — click **Find gaps** above to generate `{INSIGHTS_FILE}`.")
