from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import requests


BASE_URL = "https://api.sociavault.com"
TIMEOUT = 45


@dataclass(frozen=True)
class ViralPost:
    url: str
    caption: str
    transcript: str
    like_count: int
    comment_count: int
    play_count: int
    score: int
    source: str
    raw: dict[str, Any]


class SociaVaultError(RuntimeError):
    pass


class SociaVaultClient:
    def __init__(self, api_key: str) -> None:
        self.headers = {"x-api-key": api_key}

    def google_instagram_urls(self, niche: str, region: str = "US") -> list[str]:
        query = f"site:instagram.com/reel/ {niche}"
        payload = self._get("/v1/scrape/google/search", {"query": query, "region": region})
        urls: list[str] = []
        _walk_for_instagram_urls(payload, urls)
        return list(dict.fromkeys(_clean_instagram_url(url) for url in urls if _is_reel_url(url)))

    def post_info(self, url: str) -> ViralPost | None:
        payload = self._get("/v1/scrape/instagram/post-info", {"url": url})
        posts = extract_posts(payload)
        if posts:
            best = max(posts, key=_post_quality_score)
            return viral_post_from_raw(best, source="post-info", fallback_url=url)

        data = payload.get("data")
        if isinstance(data, dict) and looks_like_post(data):
            return viral_post_from_raw(data, source="post-info", fallback_url=url)
        return None

    def transcript(self, url: str) -> str:
        payload = self._get("/v1/scrape/instagram/transcript", {"url": url})
        texts: list[str] = []
        _walk_for_transcript_text(payload, texts)
        return " ".join(texts).strip()

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        response = requests.get(
            f"{BASE_URL}{path}",
            headers=self.headers,
            params=params,
            timeout=TIMEOUT,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SociaVaultError(f"SociaVault returned non-JSON response: {response.status_code}") from exc

        if response.status_code >= 400:
            message = payload.get("error") or payload.get("message") or response.text[:200]
            raise SociaVaultError(f"SociaVault {response.status_code}: {message}")
        return payload if isinstance(payload, dict) else {}


def viral_post_from_raw(
    raw: dict[str, Any],
    source: str,
    fallback_url: str,
    transcript: str = "",
) -> ViralPost:
    like_count = int_or_zero(raw.get("like_count") or raw.get("likes"))
    if not like_count:
        like_count = int_or_zero(_nested_count(raw, ["edge_liked_by", "preview_like_count"]))
    comment_count = int_or_zero(raw.get("comment_count") or raw.get("comments"))
    if not comment_count:
        comment_count = int_or_zero(_nested_count(raw, ["edge_media_to_comment"]))
    play_count = int_or_zero(
        raw.get("play_count")
        or raw.get("ig_play_count")
        or raw.get("view_count")
        or raw.get("video_view_count")
        or raw.get("views")
        or raw.get("playCount")
        or raw.get("viewCount")
        or raw.get("videoPlayCount")
    )
    score = int_or_zero(raw.get("score")) or viral_score(like_count, comment_count, play_count)
    return ViralPost(
        url=post_url(raw) or fallback_url,
        caption=get_caption(raw),
        transcript=transcript,
        like_count=like_count,
        comment_count=comment_count,
        play_count=play_count,
        score=score,
        source=source,
        raw=raw,
    )


def with_transcript(post: ViralPost, transcript: str) -> ViralPost:
    return ViralPost(
        url=post.url,
        caption=post.caption,
        transcript=transcript,
        like_count=post.like_count,
        comment_count=post.comment_count,
        play_count=post.play_count,
        score=post.score,
        source=post.source,
        raw=post.raw,
    )


def extract_posts(payload: Any) -> list[dict[str, Any]]:
    posts: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if looks_like_post(value):
                posts.append(value)
                return
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return posts


def looks_like_post(value: dict[str, Any]) -> bool:
    return bool(post_url(value) or get_caption(value) or _has_any_metric(value))


def viral_score(likes: int, comments: int, plays: int) -> int:
    return plays + (likes * 3) + (comments * 10)


def get_caption(post: dict[str, Any]) -> str:
    caption = post.get("caption")
    if isinstance(caption, dict):
        return str(caption.get("text") or "")
    if caption:
        return str(caption)

    edges = _nested(post, ["edge_media_to_caption", "edges"])
    if isinstance(edges, list) and edges:
        node = edges[0].get("node") if isinstance(edges[0], dict) else None
        if isinstance(node, dict) and node.get("text"):
            return str(node["text"])

    return str(post.get("caption_text") or post.get("text") or post.get("title") or "")


def post_url(post: dict[str, Any]) -> str:
    url = str(post.get("url") or post.get("permalink") or "")
    if _is_post_url(url):
        return _clean_instagram_url(url)
    code = post.get("code") or post.get("shortcode")
    if code:
        return f"https://www.instagram.com/p/{code}/"
    return ""


def int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def has_usable_signal(post: ViralPost) -> bool:
    return bool(post.caption.strip() or post.transcript.strip() or post.score > 0)


def has_engagement(post: ViralPost) -> bool:
    return post.score > 0 or post.like_count > 0 or post.comment_count > 0 or post.play_count > 0


def _has_any_metric(value: dict[str, Any]) -> bool:
    return any(
        int_or_zero(value.get(key))
        for key in (
            "score",
            "like_count",
            "likes",
            "comment_count",
            "comments",
            "play_count",
            "ig_play_count",
            "view_count",
            "video_view_count",
            "views",
            "playCount",
            "viewCount",
            "videoPlayCount",
        )
    ) or bool(_nested_count(value, ["edge_liked_by"]) or _nested_count(value, ["edge_media_to_comment"]))


def _post_quality_score(value: dict[str, Any]) -> int:
    post = viral_post_from_raw(value, source="", fallback_url="")
    return (
        (1000 if has_engagement(post) else 0)
        + (500 if post.caption else 0)
        + (100 if post.url else 0)
        + min(post.score, 10_000_000)
    )


def _nested(value: dict[str, Any], path: list[str]) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _nested_count(value: dict[str, Any], paths: list[str]) -> Any:
    for path in paths:
        current = value.get(path)
        if isinstance(current, dict) and "count" in current:
            return current["count"]
        if current:
            return current
    return None


def _walk_for_instagram_urls(value: Any, urls: list[str]) -> None:
    if isinstance(value, dict):
        for child in value.values():
            _walk_for_instagram_urls(child, urls)
    elif isinstance(value, list):
        for child in value:
            _walk_for_instagram_urls(child, urls)
    elif isinstance(value, str) and "instagram.com/" in value:
        urls.extend(re.findall(r"https?://(?:www\.)?instagram\.com/(?:p|reel)/[A-Za-z0-9_-]+/?(?:\?[^ \"]*)?", value))


def _walk_for_transcript_text(value: Any, texts: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in {"text", "transcript", "caption"} and isinstance(child, str):
                texts.append(child)
            else:
                _walk_for_transcript_text(child, texts)
    elif isinstance(value, list):
        for child in value:
            _walk_for_transcript_text(child, texts)


def _is_post_url(url: str) -> bool:
    return "instagram.com/p/" in url or "instagram.com/reel/" in url


def _is_reel_url(url: str) -> bool:
    return "instagram.com/reel/" in url


def _clean_instagram_url(url: str) -> str:
    match = re.search(r"https?://(?:www\.)?instagram\.com/(p|reel)/([A-Za-z0-9_-]+)", url)
    if not match:
        return url
    return f"https://www.instagram.com/{match.group(1)}/{match.group(2)}/"
