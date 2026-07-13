from __future__ import annotations

import html
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import requests

OLD_REDDIT_BASE_URL = "https://old.reddit.com"
TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 viral-idea-generator/0.1 by local-dev"


@dataclass(frozen=True)
class ViralPost:
    url: str
    title: str
    body: str
    top_comment: str
    score: int
    comment_count: int
    upvote_ratio: float
    subreddit: str
    viral_score: int
    source: str = "oldreddit-current"
    created_utc: int = 0


class RedditError(RuntimeError):
    pass


class RedditClient:
    """
    Free current Reddit data client using old.reddit.com HTML.

    It needs no credentials, but HTML parsing is less stable than an official API.
    """

    def __init__(self, request_delay: float = 0.35) -> None:
        self.request_delay = request_delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def find_viral_posts(
        self,
        niche: str,
        subreddits: list[str],
        time_filter: str = "month",
        limit: int = 25,
    ) -> list[ViralPost]:
        return self._find_oldreddit_posts(niche, subreddits, time_filter, limit)

    def _find_oldreddit_posts(
        self,
        niche: str,
        subreddits: list[str],
        time_filter: str,
        limit: int,
    ) -> list[ViralPost]:
        all_posts: list[ViralPost] = []
        targets = [s.strip().lstrip("r/") for s in subreddits if s.strip()] or ["all"]

        for subreddit in targets:
            for query in _query_variants(niche):
                html_text = self._oldreddit_get(
                    f"/r/{subreddit}/search",
                    {"q": query, "restrict_sr": "on", "sort": "top", "t": time_filter},
                )
                posts = self._parse_oldreddit_listing(html_text)
                all_posts.extend(posts)
                if len(all_posts) >= limit:
                    break

            if len(all_posts) >= limit:
                break

        if len(all_posts) < limit:
            for query in _query_variants(niche):
                html_text = self._oldreddit_get(
                    "/search",
                    {"q": query, "sort": "top", "t": time_filter},
                )
                all_posts.extend(self._parse_oldreddit_listing(html_text))
                if len(all_posts) >= limit:
                    break

        ranked = _rank_posts(_dedupe_posts(all_posts))
        enriched = [self._enrich_oldreddit_post(post) for post in ranked[: min(limit, 10)]]
        if len(ranked) > len(enriched):
            enriched.extend(ranked[len(enriched) : limit])
        return _rank_posts(_dedupe_posts(enriched))[:limit]

    def _parse_oldreddit_listing(self, html_text: str) -> list[ViralPost]:
        posts = self._parse_oldreddit_things(html_text)
        posts.extend(self._parse_oldreddit_search_results(html_text))
        return posts

    def _parse_oldreddit_things(self, html_text: str) -> list[ViralPost]:
        chunks = re.split(r'(?=<div class=" thing )', html_text)
        posts: list[ViralPost] = []
        for chunk in chunks:
            if not chunk.startswith('<div class=" thing '):
                continue
            tag_match = re.match(r"<div\s+([^>]+)>", chunk)
            if not tag_match:
                continue
            attrs = _parse_attrs(tag_match.group(1))
            if attrs.get("data-promoted") == "true" or attrs.get("data-nsfw") == "true":
                continue

            title_match = re.search(r'<a[^>]+class="title[^"]*"[^>]*>(.*?)</a>', chunk, re.S)
            title = _strip_html(title_match.group(1)) if title_match else ""
            permalink = attrs.get("data-permalink") or attrs.get("data-url") or ""
            subreddit = attrs.get("data-subreddit", "")
            score = _to_int(attrs.get("data-score"))
            comment_count = _to_int(attrs.get("data-comments-count"))
            created_utc = _to_int(attrs.get("data-timestamp")) // 1000

            if not title or not permalink:
                continue
            posts.append(
                ViralPost(
                    url=_absolute_reddit_url(permalink),
                    title=title,
                    body="",
                    top_comment="",
                    score=score,
                    comment_count=comment_count,
                    upvote_ratio=0.0,
                    subreddit=subreddit,
                    viral_score=score + (comment_count * 10),
                    source="oldreddit-current",
                    created_utc=created_utc,
                )
            )
        return posts

    def _parse_oldreddit_search_results(self, html_text: str) -> list[ViralPost]:
        chunks = re.split(r'(?=<div class=" search-result search-result-link)', html_text)
        posts: list[ViralPost] = []
        for chunk in chunks:
            if not chunk.startswith('<div class=" search-result search-result-link'):
                continue

            title_match = re.search(
                r'<a href="([^"]+)" class="search-title[^"]*"[^>]*>(.*?)</a>',
                chunk,
                re.S,
            )
            if not title_match:
                continue
            url = _absolute_reddit_url(html.unescape(title_match.group(1)))
            title = _strip_html(title_match.group(2))
            score_match = re.search(r'<span class="search-score">([\d,]+)\s+points?</span>', chunk)
            comments_match = re.search(
                r'<a[^>]+class="search-comments[^"]*"[^>]*>([\d,]+)\s+comments?</a>',
                chunk,
            )
            subreddit_match = re.search(
                r'<a href="https://old\.reddit\.com/r/([^/]+)/" class="search-subreddit-link',
                chunk,
            )
            body_match = re.search(
                r'<div class="search-result-body[^"]*">(?:<div class="md">)?(.*?)(?:</div></div>|</div>)',
                chunk,
                re.S,
            )
            score = _to_int(score_match.group(1) if score_match else 0)
            comment_count = _to_int(comments_match.group(1) if comments_match else 0)
            subreddit = html.unescape(subreddit_match.group(1)) if subreddit_match else ""
            body = _strip_html(body_match.group(1)) if body_match else ""

            if not title or not url:
                continue
            posts.append(
                ViralPost(
                    url=url,
                    title=title,
                    body=body[:2000],
                    top_comment="",
                    score=score,
                    comment_count=comment_count,
                    upvote_ratio=0.0,
                    subreddit=subreddit,
                    viral_score=score + (comment_count * 10),
                    source="oldreddit-current",
                    created_utc=0,
                )
            )
        return posts

    def _enrich_oldreddit_post(self, post: ViralPost) -> ViralPost:
        try:
            path = post.url.replace("https://www.reddit.com", "").replace(
                "https://old.reddit.com", ""
            )
            html_text = self._oldreddit_get(path, {"sort": "top"})
            texts = [_strip_html(match) for match in re.findall(r'<div class="usertext-body[^"]*">(.*?)</div>\s*</div>', html_text, re.S)]
            texts = [text for text in texts if _is_usable_text(text) and not _looks_sidebar_text(text)]
            body = texts[0] if texts else ""
            top_comment = texts[1] if len(texts) > 1 else ""
            return ViralPost(
                url=post.url,
                title=post.title,
                body=body[:2000],
                top_comment=top_comment[:500],
                score=post.score,
                comment_count=post.comment_count,
                upvote_ratio=post.upvote_ratio,
                subreddit=post.subreddit,
                viral_score=post.viral_score,
                source=post.source,
                created_utc=post.created_utc,
            )
        except Exception:
            return post

    def _oldreddit_get(self, path: str, params: dict[str, Any]) -> str:
        time.sleep(self.request_delay)
        try:
            response = self.session.get(
                f"{OLD_REDDIT_BASE_URL}{path}", params=params, timeout=TIMEOUT
            )
        except requests.RequestException as exc:
            raise RedditError(f"old.reddit.com request failed: {exc}") from exc
        if response.status_code == 429:
            raise RedditError("old.reddit.com rate-limited this request. Wait a bit and retry.")
        if response.status_code >= 400:
            raise RedditError(
                f"old.reddit.com returned {response.status_code} for {path}. "
                f"Body: {response.text[:300]}"
            )
        return response.text


def suggest_subreddits(niche: str, max_subs: int = 3) -> list[str]:
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        subs = _suggest_with_gemini(api_key, niche, max_subs)
        if subs:
            return subs
    subs = _suggest_from_static_map(niche, max_subs)
    if subs:
        return subs
    return ["AskReddit"]


def _suggest_with_gemini(api_key: str, niche: str, max_subs: int) -> list[str]:
    try:
        from google import genai
    except ImportError:
        return []
    try:
        client = genai.Client(api_key=api_key)
        prompt = (
            f'Given this content niche: "{niche}", list the {max_subs} most relevant, '
            "active Reddit subreddits where people in or around this niche discuss things. "
            "Return ONLY a comma-separated list of subreddit names, no r/ prefix, no explanation."
        )
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        text = getattr(response, "text", "") or ""
        subs = [s.strip().lstrip("r/").strip() for s in text.split(",")]
        return [s for s in subs if s][:max_subs]
    except Exception:
        return []


_STATIC_NICHE_MAP: dict[str, list[str]] = {
    "fitness": ["Fitness", "loseit", "bodyweightfitness"],
    "fat loss": ["loseit", "Fitness", "CICO"],
    "weight loss": ["loseit", "CICO", "Fitness"],
    "dad": ["daddit", "Fitness", "loseit"],
    "parent": ["Parenting", "daddit", "Mommit"],
    "business": ["Entrepreneur", "smallbusiness"],
    "marketing": ["marketing", "socialmedia"],
    "finance": ["personalfinance", "financialindependence"],
    "productivity": ["productivity", "GetMotivated"],
    "coach": ["getdisciplined", "Fitness", "Entrepreneur"],
    "relationship": ["relationship_advice", "dating_advice"],
    "tech": ["technology", "programming"],
    "beauty": ["SkincareAddiction", "MakeupAddiction"],
    "food": ["Cooking", "MealPrepSunday"],
}

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "the",
    "to",
    "with",
    "your",
}

_SPAM_TERMS = (
    "onlyfans",
    "telegram",
    "leaked",
    "nsfw",
    "nude",
    "porn",
    "escort",
    "casino",
    "crypto giveaway",
)

_LOW_SIGNAL_TITLE_TERMS = (
    "daily discussion",
    "daily simple questions",
    "daily thread",
    "general discussion",
    "gym story saturday",
    "moronic monday",
    "newbie tuesday",
    "physique phriday",
    "rant wednesday",
    "simple questions",
    "victory sunday",
    "megathread",
    "weekly stupid questions",
    "weekly thread",
)


def _suggest_from_static_map(niche: str, max_subs: int) -> list[str]:
    niche_lower = niche.lower()
    matched: list[str] = []
    for keyword, subs in _STATIC_NICHE_MAP.items():
        if keyword in niche_lower:
            for subreddit in subs:
                if subreddit not in matched:
                    matched.append(subreddit)
    return matched[:max_subs]


def _query_variants(niche: str) -> list[str]:
    words = [w for w in re.findall(r"[a-zA-Z0-9]+", niche.lower()) if w not in _STOPWORDS]
    variants = [niche.strip()]
    if len(words) >= 3:
        variants.append(" ".join(words[:3]))
    if len(words) >= 2:
        variants.append(" ".join(words[-2:]))
    cleaned: list[str] = []
    for variant in variants:
        variant = variant.strip()
        if variant and variant not in cleaned:
            cleaned.append(variant)
    return cleaned[:4]


def _parse_attrs(raw_attrs: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for key, value in re.findall(r'([a-zA-Z0-9_-]+)="([^"]*)"', raw_attrs):
        attrs[key] = html.unescape(value)
    return attrs


def _strip_html(raw: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", raw)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def _to_int(value: Any) -> int:
    try:
        return int(float(str(value or "0").replace(",", "")))
    except ValueError:
        return 0


def _absolute_reddit_url(url: str) -> str:
    if url.startswith("http"):
        return url.replace("https://old.reddit.com", "https://www.reddit.com")
    if url.startswith("/"):
        return f"https://www.reddit.com{url}"
    return url


def _dedupe_posts(posts: list[ViralPost]) -> list[ViralPost]:
    seen: set[str] = set()
    deduped: list[ViralPost] = []
    for post in posts:
        key = post.url or f"{post.subreddit}:{post.title}"
        if key not in seen:
            seen.add(key)
            deduped.append(post)
    return deduped


def _rank_posts(posts: list[ViralPost]) -> list[ViralPost]:
    usable = [post for post in posts if has_usable_signal(post) and has_engagement(post)]
    return sorted(usable, key=lambda p: p.viral_score, reverse=True)


def _clean_body(body: str) -> str:
    if body.strip().lower() in {"[removed]", "[deleted]"}:
        return ""
    return body.strip()


def _is_usable_text(text: str) -> bool:
    stripped = str(text or "").strip()
    return bool(stripped and stripped.lower() not in {"[removed]", "[deleted]"})


def _looks_sidebar_text(text: str) -> bool:
    lowered = text.lower()
    return "welcome to r/fitness" in lowered or "rule summary" in lowered


def _looks_spammy(post: ViralPost) -> bool:
    text = f"{post.title} {post.body}".lower()
    return any(term in text for term in _SPAM_TERMS)


def _looks_low_signal_thread(post: ViralPost) -> bool:
    title = post.title.lower()
    return any(term in title for term in _LOW_SIGNAL_TITLE_TERMS)


def has_engagement(post: ViralPost) -> bool:
    return post.score > 0 or post.comment_count > 0


def has_usable_signal(post: ViralPost) -> bool:
    return (
        bool(post.title.strip() or post.body.strip() or post.top_comment.strip())
        and not _looks_spammy(post)
        and not _looks_low_signal_thread(post)
    )
