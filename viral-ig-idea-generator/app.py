from __future__ import annotations

import os

import streamlit as st
from dotenv import load_dotenv

from idea_generator import generate_ideas
from sociavault_api import (
    SociaVaultClient,
    SociaVaultError,
    ViralPost,
    has_engagement,
    has_usable_signal,
    with_transcript,
)


load_dotenv()

st.set_page_config(page_title="Viral IG Idea Generator", layout="wide")
CACHE_VERSION = "reels-v2"


def main() -> None:
    st.title("Viral IG Idea Generator")
    st.caption("Find public Instagram reels with proven traction, then generate ideas for your offer.")

    with st.sidebar:
        st.header("Input")
        niche = st.text_input("Niche", value="fitness coach busy dads")
        offering = st.text_area(
            "Your offering",
            value="8-week fat loss coaching for busy dads who only have 30 minutes a day",
            height=90,
        )
        audience = st.text_input("Target audience", value="busy dads in their 30s and 40s")
        tone = st.selectbox("Tone", ["direct", "educational", "contrarian", "warm", "premium"])

        st.divider()
        region = st.text_input("Google region", value="US", max_chars=2)
        max_urls = st.slider("Reel URLs to resolve", min_value=2, max_value=8, value=5)
        fetch_transcripts = st.checkbox("Fetch transcripts for top reels", value=True)
        top_reels = st.slider("Top reels to use", min_value=1, max_value=2, value=2)
        run = st.button("Generate ideas", type="primary", use_container_width=True)

        st.divider()
        render_api_status(max_urls, fetch_transcripts, top_reels)

    if not run:
        render_empty_state()
        return

    api_key = os.getenv("SOCIAVAULT_API_KEY")
    if not api_key:
        st.error("Missing SOCIAVAULT_API_KEY. Add it to .env first.")
        return

    client = SociaVaultClient(api_key)

    try:
        with st.status("Finding viral source reels...", expanded=True) as status:
            st.write("Searching Google for public Instagram reel URLs.")
            urls = cached_google_urls(api_key, niche, region, CACHE_VERSION)
            st.write(f"Found {len(urls)} candidate URLs. Resolving top {min(max_urls, len(urls))}.")
            reels, ignored_count = resolve_reels(api_key, urls[:max_urls])
            if ignored_count:
                st.write(f"Ignored {ignored_count} responses with missing engagement metrics.")

            reels = sorted(reels, key=lambda post: (has_engagement(post), post.score), reverse=True)
            selected = reels[:top_reels]
            st.write(f"Selected {len(selected)} top reels by viral score.")

            if fetch_transcripts:
                st.write("Fetching transcripts for selected source reels.")
                selected = add_transcripts(api_key, selected)

            st.write("Generating ideas.")
            ideas = generate_ideas(niche, offering, audience, tone, selected)
            status.update(label="Done", state="complete")

        render_results(selected, ideas)
    except SociaVaultError as exc:
        st.error(str(exc))


def render_api_status(
    max_urls: int,
    fetch_transcripts: bool,
    top_reels: int,
) -> None:
    st.subheader("Status")
    st.write("SociaVault:", "connected" if os.getenv("SOCIAVAULT_API_KEY") else "missing")
    st.write("Gemini:", "connected" if os.getenv("GEMINI_API_KEY") else "fallback mode")

    transcript_cost = top_reels if fetch_transcripts else 0
    st.caption(f"Estimated SociaVault credits: {1 + max_urls + transcript_cost}")


def render_empty_state() -> None:
    left, right = st.columns([1.1, 0.9], gap="large")
    with left:
        st.subheader("How this works")
        st.write(
            "Enter a niche to discover public Instagram reel URLs through SociaVault Google search."
        )
        st.write(
            "The app resolves a capped number of reels, ranks them by engagement, takes the top two, "
            "and generates two idea variations for your offer."
        )
    with right:
        st.subheader("Built around tested endpoints")
        st.write("- Google search discovery")
        st.write("- Instagram post-info")
        st.write("- Optional transcript for reel hooks")


def render_results(reels: list[ViralPost], ideas: list[dict]) -> None:
    st.subheader("Viral source reels")
    if not reels:
        st.warning("No usable source reels found. Try a broader niche or resolve more URLs.")
        return

    for post in reels:
        with st.container(border=True):
            metric_cols = st.columns(4)
            metric_cols[0].metric("Score", f"{post.score:,}")
            metric_cols[1].metric("Plays", f"{post.play_count:,}")
            metric_cols[2].metric("Likes", f"{post.like_count:,}")
            metric_cols[3].metric("Comments", f"{post.comment_count:,}")
            st.write(post.caption[:500] or "No caption returned.")
            if post.transcript:
                st.caption(f"Transcript: {post.transcript[:280]}")
            if post.url:
                st.link_button("Open source", post.url)

    st.subheader("Ideas")
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


@st.cache_data(ttl=3600, show_spinner=False)
def cached_google_urls(api_key: str, niche: str, region: str, cache_version: str) -> list[str]:
    return SociaVaultClient(api_key).google_instagram_urls(niche, region)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_post_info(api_key: str, url: str, cache_version: str) -> ViralPost | None:
    return SociaVaultClient(api_key).post_info(url)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_transcript(api_key: str, url: str, cache_version: str) -> str:
    return SociaVaultClient(api_key).transcript(url)


def resolve_reels(api_key: str, urls: list[str]) -> tuple[list[ViralPost], int]:
    reels: list[ViralPost] = []
    ignored_count = 0
    for url in urls:
        post = cached_post_info(api_key, url, CACHE_VERSION)
        if post and has_usable_signal(post) and has_engagement(post):
            reels.append(post)
        else:
            ignored_count += 1
    return reels, ignored_count


def add_transcripts(api_key: str, reels: list[ViralPost]) -> list[ViralPost]:
    enriched: list[ViralPost] = []
    for post in reels:
        if "/reel/" in post.url:
            transcript = cached_transcript(api_key, post.url, CACHE_VERSION)
            enriched.append(with_transcript(post, transcript))
        else:
            enriched.append(post)
    return enriched


if __name__ == "__main__":
    main()
