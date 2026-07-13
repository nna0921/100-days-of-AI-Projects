from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from idea_generator import (
    IdeaGenerationError,
    generate_ideas,
)
from reddit_api import (
    RedditClient,
    RedditError,
    ViralPost,
    has_engagement,
    has_usable_signal,
    suggest_subreddits,
)

load_dotenv()
st.set_page_config(page_title="RedGen", layout="wide")
CACHE_VERSION = "reddit-v2-oldreddit"
LOGO_PATH = Path(__file__).parent / "assets" / "redgen-logo.png"


def main() -> None:
    inject_theme()
    render_header()

    with st.container(border=True):
        st.markdown("**Build your angle**")
        first_row = st.columns([1.25, 1.25, 0.7, 0.7], gap="medium")
        with first_row[0]:
            niche = st.text_input("Niche", value="fitness coach busy dads")
        with first_row[1]:
            audience = st.text_input("Target audience", value="busy dads in their 30s and 40s")
        with first_row[2]:
            tone = st.selectbox("Tone", ["direct", "educational", "contrarian", "warm", "premium"])
        with first_row[3]:
            time_filter = st.selectbox("Search window", ["week", "month", "year", "all"], index=1)

        offering = st.text_area(
            "Your offering",
            value="8-week fat loss coaching for busy dads who only have 30 minutes a day",
            height=92,
        )

        second_row = st.columns(2, gap="medium")
        with second_row[0]:
            search_limit = st.slider("Posts to search", min_value=10, max_value=50, value=25)
        with second_row[1]:
            top_posts = st.slider("Top posts to use", min_value=1, max_value=2, value=2)

        st.markdown('<div class="action-divider"></div>', unsafe_allow_html=True)
        action_row = st.columns([1.45, 0.55], gap="medium")
        with action_row[1]:
            run = st.button("Find me ideas ", type="primary", use_container_width=True)

    if not run:
        render_empty_state()
        return

    try:
        client = RedditClient()
    except RedditError as exc:
        st.error(str(exc))
        return

    try:
        with st.status("Finding viral Reddit posts...", expanded=True) as status:
            subreddits = cached_subreddits(niche, CACHE_VERSION)
            st.write(f"Relevant subreddits for this niche: r/{', r/'.join(subreddits)}")
            posts = cached_reddit_posts(niche, subreddits, time_filter, search_limit, CACHE_VERSION)
            st.write(f"Found {len(posts)} posts.")
            usable = [p for p in posts if has_usable_signal(p) and has_engagement(p)]
            ignored_count = len(posts) - len(usable)
            if ignored_count:
                st.write(f"Ignored {ignored_count} posts with no usable signal.")
            selected = usable[:top_posts]
            st.write(f"Selected {len(selected)} top posts by viral score.")
            st.write("Generating ideas.")
            ideas = generate_ideas(
                niche,
                offering,
                audience,
                tone,
                selected,
                allow_local_fallback=False,
            )
            status.update(label="Done", state="complete")
        render_results(selected, ideas)
    except RedditError as exc:
        st.error(str(exc))
    except IdeaGenerationError as exc:
        st.error(str(exc))


def render_empty_state() -> None:
    st.markdown(
        """
        <section class="mini-steps" aria-label="How RedGen works">
          <div class="mini-step">
            <span class="step-badge">01</span>
            <strong>Niche drop</strong>
            <p>Tell RedGen the corner of the internet you want to mine.</p>
          </div>
          <div class="mini-step">
            <span class="step-badge">02</span>
            <strong>Post hunt</strong>
            <p>It catches Reddit posts with real upvote and comment heat.</p>
          </div>
          <div class="mini-step">
            <span class="step-badge">03</span>
            <strong>Offer remix</strong>
            <p>Gemini turns the winning hook pattern into your next idea.</p>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_results(posts: list[ViralPost], ideas: list[dict]) -> None:
    st.subheader("Viral Source Posts")
    if not posts:
        st.warning("No usable source posts found. Try a broader niche or wider search window.")
        return
    for post in posts:
        with st.container(border=True):
            metric_cols = st.columns(3)
            metric_cols[0].metric("Viral score", f"{post.viral_score:,}")
            metric_cols[1].metric("Upvotes", f"{post.score:,}")
            metric_cols[2].metric("Comments", f"{post.comment_count:,}")
            st.markdown(f"**r/{post.subreddit}** — {post.title}")
            if post.body:
                st.write(post.body[:400])
            if post.top_comment:
                st.caption(f"Top comment: {post.top_comment[:280]}")
            st.link_button("Open source", post.url)

    st.subheader("Adapted Ideas")
    if not ideas:
        st.warning("No ideas generated.")
        return
    for index, idea in enumerate(ideas, start=1):
        with st.container(border=True):
            st.markdown(f"### {index}. {idea['hook']}")
            st.markdown(f"**Source pattern:** {idea['source_pattern']}")
            st.write(idea["caption"])
            if idea["reel_outline"]:
                st.markdown("**Reel outline**")
                for point in idea["reel_outline"]:
                    st.write(f"- {point}")
            st.markdown(f"**CTA:** {idea['cta']}")
            st.caption(idea["why_it_maps"])
            if idea["source_url"]:
                st.link_button("Source inspiration", idea["source_url"])


def render_header() -> None:
    logo_data = base64.b64encode(LOGO_PATH.read_bytes()).decode("utf-8")
    st.markdown(
        f"""
        <section class="brand-shell">
          <div class="logo-plate">
            <img src="data:image/png;base64,{logo_data}" alt="RedGen logo" />
          </div>
          <div class="brand-panel">
            <p class="eyebrow">AI content signal lab</p>
            <h1>RedGen</h1>
            <p class="brand-tagline">
              Find viral Reddit posts in your niche, then turn their hook pattern into an idea for your offer.
            </p>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def inject_theme() -> None:
    st.markdown(
        """
        <style>
          :root {
            --ink: #111111;
            --muted: #5f5f5f;
            --line: #e5e5e5;
            --surface: #ffffff;
            --accent: #ff2d20;
            --accent-dark: #a90f08;
            --black: #050505;
          }

          .stApp {
            background:
              linear-gradient(180deg, #ffffff 0%, #fff7f6 100%);
            color: var(--ink);
          }

          .block-container {
            max-width: 1240px;
            padding-top: 2rem;
          }

          header[data-testid="stHeader"] {
            background: transparent;
          }

          .brand-shell {
            display: flex;
            align-items: center;
            gap: 1.1rem;
            margin-bottom: 1.15rem;
          }

          .logo-plate {
            width: 132px;
            min-width: 132px;
            border: 1px solid #eeeeee;
            border-radius: 8px;
            background: #f2f2f2;
            padding: 0.55rem;
            box-shadow: 0 12px 30px rgba(0, 0, 0, 0.07);
          }

          .logo-plate img {
            display: block;
            width: 100%;
            height: auto;
          }

          .brand-panel {
            border-left: 6px solid var(--accent);
            padding: 0.2rem 0 0.35rem 1rem;
          }

          .brand-panel h1 {
            margin: 0;
            color: var(--ink);
            font-size: clamp(2.7rem, 5vw, 5.5rem);
            line-height: 0.95;
            letter-spacing: 0;
          }

          .eyebrow {
            margin: 0 0 0.35rem;
            color: var(--accent);
            font-size: 0.78rem;
            font-weight: 800;
            text-transform: uppercase;
          }

          .brand-tagline {
            max-width: 760px;
            margin: 0.65rem 0 0;
            color: var(--muted);
            font-size: 1.03rem;
            line-height: 1.45;
          }

          .mini-steps {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.9rem;
            margin-top: 1.25rem;
          }

          .mini-step {
            position: relative;
            overflow: hidden;
            min-height: 138px;
            border: 1px solid #151515;
            border-radius: 8px;
            background: #ffffff;
            padding: 1rem 1rem 0.95rem;
            box-shadow: 8px 8px 0 #111111;
          }

          .mini-step::after {
            content: "";
            position: absolute;
            right: -20px;
            top: -22px;
            width: 72px;
            height: 72px;
            border-radius: 999px;
            background: var(--accent);
          }

          .step-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 38px;
            height: 30px;
            margin-bottom: 0.7rem;
            border-radius: 999px;
            background: #111111;
            color: #ffffff !important;
            font-size: 0.78rem;
            font-weight: 900;
          }

          .mini-step strong {
            display: block;
            color: #111111;
            font-size: 1.08rem;
            line-height: 1.2;
          }

          .mini-step p {
            max-width: 270px;
            margin: 0.45rem 0 0;
            color: #585858;
            font-size: 0.95rem;
            line-height: 1.42;
          }

          .action-divider {
            height: 1px;
            margin: 0.45rem 0 0.75rem;
            background: linear-gradient(90deg, transparent, #efc0bd 20%, #efc0bd 80%, transparent);
          }

          div[data-testid="stSidebar"] {
            display: none;
          }

          div[data-testid="stVerticalBlockBorderWrapper"] {
            border: 1px solid var(--line);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.96);
            box-shadow: 0 18px 45px rgba(90, 0, 0, 0.08);
          }

          div[data-testid="stVerticalBlockBorderWrapper"]:has(.stTextInput) {
            border-top: 4px solid var(--accent);
          }

          label,
          p,
          span,
          div {
            color: var(--ink);
          }

          div[data-testid="stStatusWidget"],
          div[data-testid="stStatusWidget"] div {
            background-color: #111111 !important;
            border-color: #333333 !important;
          }

          div[data-testid="stStatusWidget"] label,
          div[data-testid="stStatusWidget"] p,
          div[data-testid="stStatusWidget"] span,
          div[data-testid="stStatusWidget"] div {
            color: #ffffff !important;
          }

          div[data-testid="stStatusWidget"] svg {
            color: #ffffff !important;
            fill: #ffffff !important;
          }

          .stTextInput div:has(> input),
          .stSelectbox div[role="group"],
          .stTextArea div:has(> textarea),
          .stSlider div:has(> input) {
            background: #ffffff !important;
            border: 1px solid #d8d8d8 !important;
            box-shadow: none !important;
          }

          div[data-baseweb="input"],
          div[data-baseweb="input"] > div,
          div[data-baseweb="select"],
          div[data-baseweb="select"] > div,
          div[data-baseweb="textarea"],
          div[data-baseweb="textarea"] > div,
          textarea {
            background: #ffffff !important;
            border-color: #d8d8d8 !important;
            color: #111111 !important;
          }

          input,
          textarea,
          div[data-baseweb="select"] span,
          div[data-baseweb="select"] div,
          .stSelectbox input,
          .stSlider input {
            color: #111111 !important;
            -webkit-text-fill-color: #111111 !important;
          }

          div[data-baseweb="select"] svg {
            color: #111111 !important;
            fill: #111111 !important;
          }

          /* Dropdown menu options */
          ul[role="listbox"],
          ul[role="listbox"] li,
          div[data-baseweb="popover"] > div {
            background-color: #ffffff !important;
            color: #111111 !important;
          }

          ul[role="listbox"] li:hover {
            background-color: #f0f0f0 !important;
          }

          div[data-baseweb="slider"] div {
            color: #111111 !important;
          }

          .stSlider input {
            background: #ffffff !important;
            border: 1px solid #d8d8d8 !important;
            border-radius: 6px !important;
          }

          div[data-baseweb="slider"] div[role="slider"] {
            background-color: var(--accent) !important;
            border-color: var(--accent) !important;
          }

          input::placeholder,
          textarea::placeholder {
            color: #777777 !important;
          }

          .stButton > button,
          .stLinkButton > a {
            background: linear-gradient(135deg, var(--accent), var(--accent-dark)) !important;
            border-radius: 6px !important;
            border: 1px solid var(--accent) !important;
            color: #ffffff !important;
            min-height: 3.05rem !important;
            font-weight: 800 !important;
            box-shadow: 0 12px 22px rgba(169, 15, 8, 0.24) !important;
            transition: transform 140ms ease, box-shadow 140ms ease !important;
            text-decoration: none !important;
          }

          .stButton > button:hover,
          .stLinkButton > a:hover {
            transform: translateY(-1px) !important;
            box-shadow: 0 16px 28px rgba(169, 15, 8, 0.28) !important;
            color: #ffffff !important;
            border: 1px solid var(--accent) !important;
          }

          .stLinkButton > a p {
            color: #ffffff !important;
            font-weight: 800 !important;
          }

          div[data-testid="stMetric"] {
            border-left: 3px solid var(--accent);
            padding-left: 0.7rem;
          }

          @media (max-width: 760px) {
            .brand-shell {
              align-items: flex-start;
            }

            .mini-steps {
              grid-template-columns: 1fr;
              gap: 0.85rem;
            }

            .mini-step {
              min-height: 118px;
              box-shadow: 5px 5px 0 #111111;
            }

            .action-divider {
              margin-top: 0.2rem;
            }

            .logo-plate {
              width: 84px;
              min-width: 84px;
              padding: 0.35rem;
            }

            .brand-panel {
              padding-left: 0.75rem;
            }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=3600, show_spinner=False)
def cached_subreddits(niche: str, cache_version: str) -> list[str]:
    return suggest_subreddits(niche)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_reddit_posts(
    niche: str,
    subreddits: list[str],
    time_filter: str,
    limit: int,
    cache_version: str,
) -> list[ViralPost]:
    return RedditClient().find_viral_posts(niche, subreddits, time_filter=time_filter, limit=limit)


if __name__ == "__main__":
    main()
