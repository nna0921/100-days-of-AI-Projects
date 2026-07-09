from __future__ import annotations

import argparse
import json
import os
from typing import Any

import requests
from dotenv import load_dotenv


BASE_URL = "https://api.sociavault.com"
TIMEOUT = 45

OPENAPI_INSTAGRAM_ENDPOINTS = {
    "/v1/scrape/instagram/comments",
    "/v1/scrape/instagram/highlight-detail",
    "/v1/scrape/instagram/highlights",
    "/v1/scrape/instagram/post-info",
    "/v1/scrape/instagram/posts",
    "/v1/scrape/instagram/profile",
    "/v1/scrape/instagram/reels",
    "/v1/scrape/instagram/reels-by-song",
    "/v1/scrape/instagram/transcript",
}

LIKELY_HASHTAG_PATHS = [
    "/v1/scrape/instagram/hashtag",
    "/v1/scrape/instagram/hashtags",
    "/v1/scrape/instagram/search",
    "/v1/scrape/instagram/posts/hashtag",
]


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Isolated SociaVault endpoint tests before building the app."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    posts = subparsers.add_parser("posts", help="Fetch profile posts by handle.")
    posts.add_argument("--handle", required=True)
    posts.add_argument("--next-max-id")
    posts.add_argument("--raw", action="store_true")

    profile = subparsers.add_parser("profile", help="Fetch profile data by handle.")
    profile.add_argument("--handle", required=True)
    profile.add_argument("--raw", action="store_true")

    reels = subparsers.add_parser("reels", help="Fetch reels by handle or user id.")
    reels.add_argument("--handle")
    reels.add_argument("--user-id")
    reels.add_argument("--max-id")
    reels.add_argument("--raw", action="store_true")

    post_info = subparsers.add_parser("post-info", help="Fetch one post/reel by URL.")
    post_info.add_argument("--url", required=True)
    post_info.add_argument("--raw", action="store_true")

    transcript = subparsers.add_parser("transcript", help="Fetch transcript for a post/reel URL.")
    transcript.add_argument("--url", required=True)
    transcript.add_argument("--raw", action="store_true")

    hashtag = subparsers.add_parser(
        "hashtag-probe",
        help="Probe undocumented likely Instagram hashtag/search paths.",
    )
    hashtag.add_argument("--tag", required=True)
    hashtag.add_argument("--raw", action="store_true")

    google = subparsers.add_parser(
        "google-discovery",
        help="Use SociaVault Google Search as fallback discovery for Instagram URLs.",
    )
    google.add_argument("--niche", required=True)
    google.add_argument("--region", default="US")
    google.add_argument("--raw", action="store_true")

    args = parser.parse_args()
    api_key = os.getenv("SOCIAVAULT_API_KEY")
    if not api_key:
        raise SystemExit(
            "Missing SOCIAVAULT_API_KEY. Add it to .env or export it before running."
        )

    client = SociaVaultClient(api_key)

    if args.command == "posts":
        params = {"handle": args.handle, "trim": "true"}
        if args.next_max_id:
            params["next_max_id"] = args.next_max_id
        response = client.get("/v1/scrape/instagram/posts", params)
        report_response("instagram posts", response, raw=args.raw)
        summarize_posts(response)
    elif args.command == "profile":
        response = client.get(
            "/v1/scrape/instagram/profile",
            {"handle": args.handle, "trim": "true"},
        )
        report_response("instagram profile", response, raw=args.raw)
    elif args.command == "reels":
        if not args.handle and not args.user_id:
            raise SystemExit("Pass --handle or --user-id.")
        params = {"trim": "true"}
        if args.handle:
            params["handle"] = args.handle
        if args.user_id:
            params["user_id"] = args.user_id
        if args.max_id:
            params["max_id"] = args.max_id
        response = client.get("/v1/scrape/instagram/reels", params)
        report_response("instagram reels", response, raw=args.raw)
        summarize_posts(response)
    elif args.command == "post-info":
        response = client.get(
            "/v1/scrape/instagram/post-info",
            {"url": args.url, "trim": "true"},
        )
        report_response("instagram post-info", response, raw=args.raw)
        summarize_single_post(response)
    elif args.command == "transcript":
        response = client.get("/v1/scrape/instagram/transcript", {"url": args.url})
        report_response("instagram transcript", response, raw=args.raw)
    elif args.command == "hashtag-probe":
        print("OpenAPI does not list an Instagram hashtag endpoint.")
        print("Published Instagram endpoints:")
        for endpoint in sorted(OPENAPI_INSTAGRAM_ENDPOINTS):
            print(f"- {endpoint}")
        print("\nProbing likely undocumented paths. These may return 404.")
        for path in LIKELY_HASHTAG_PATHS:
            params = {"tag": args.tag}
            if path.endswith("/search"):
                params = {"query": args.tag}
            response = client.get(path, params)
            report_response(path, response, raw=args.raw)
            summarize_posts(response)
    elif args.command == "google-discovery":
        query = f"site:instagram.com/p/ OR site:instagram.com/reel/ {args.niche}"
        response = client.get(
            "/v1/scrape/google/search",
            {"query": query, "region": args.region},
        )
        report_response("google discovery", response, raw=args.raw)
        summarize_google_instagram_urls(response)


class SociaVaultClient:
    def __init__(self, api_key: str) -> None:
        self.headers = {"x-api-key": api_key}

    def get(self, path: str, params: dict[str, str]) -> requests.Response:
        return requests.get(
            f"{BASE_URL}{path}",
            headers=self.headers,
            params=params,
            timeout=TIMEOUT,
        )


def report_response(label: str, response: requests.Response, raw: bool = False) -> None:
    print(f"\n=== {label} ===")
    print("url:", response.url.replace(os.getenv("SOCIAVAULT_API_KEY", ""), "[redacted]"))
    print("status:", response.status_code)
    try:
        payload = response.json()
    except ValueError:
        print("body:", response.text[:500])
        return

    print("success:", payload.get("success"))
    print("credits_used:", payload.get("credits_used") or payload.get("creditsUsed"))
    print("top_level_keys:", sorted(payload.keys()))

    data = payload.get("data")
    if isinstance(data, dict):
        print("data_keys:", sorted(data.keys())[:40])
        print("more_available:", data.get("more_available"))
        print("next_max_id:", data.get("next_max_id") or data.get("max_id"))

    if raw:
        print(json.dumps(payload, indent=2)[:12000])


def summarize_posts(response: requests.Response) -> None:
    payload = safe_json(response)
    posts = extract_posts(payload)
    if not posts:
        print("post_summary: no post-like items found")
        return

    ranked = sorted(posts, key=viral_score, reverse=True)
    print(f"post_summary: {len(posts)} post-like items")
    for index, post in enumerate(ranked[:5], start=1):
        caption = get_caption(post)
        print(
            f"{index}. score={viral_score(post)} "
            f"likes={post.get('like_count') or post.get('likes') or 0} "
            f"comments={post.get('comment_count') or post.get('comments') or 0} "
            f"plays={post.get('play_count') or post.get('ig_play_count') or 0} "
            f"url={post_url(post)}"
        )
        if caption:
            print("   caption:", one_line(caption)[:220])


def summarize_single_post(response: requests.Response) -> None:
    payload = safe_json(response)
    data = payload.get("data", payload)
    post = data.get("media") if isinstance(data, dict) else None
    if not isinstance(post, dict):
        post = data if isinstance(data, dict) else {}
    if not post:
        print("single_post_summary: no post object found")
        return
    print("single_post_summary:")
    print("  url:", post_url(post))
    print("  caption:", one_line(get_caption(post))[:300])
    print("  like_count:", post.get("like_count"))
    print("  comment_count:", post.get("comment_count"))
    print("  play_count:", post.get("play_count") or post.get("ig_play_count"))


def summarize_google_instagram_urls(response: requests.Response) -> None:
    payload = safe_json(response)
    urls = []
    walk_for_urls(payload, urls)
    instagram_urls = [
        url for url in dict.fromkeys(urls)
        if "instagram.com/p/" in url or "instagram.com/reel/" in url
    ]
    print(f"instagram_url_summary: {len(instagram_urls)} URLs found")
    for url in instagram_urls[:10]:
        print("-", url)


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
    return any(key in value for key in ("caption", "caption_text", "code")) and any(
        key in value
        for key in ("like_count", "comment_count", "play_count", "ig_play_count", "media_type")
    )


def viral_score(post: dict[str, Any]) -> int:
    likes = int_or_zero(post.get("like_count") or post.get("likes"))
    comments = int_or_zero(post.get("comment_count") or post.get("comments"))
    plays = int_or_zero(post.get("play_count") or post.get("ig_play_count"))
    return plays + (likes * 3) + (comments * 10)


def get_caption(post: dict[str, Any]) -> str:
    caption = post.get("caption")
    if isinstance(caption, dict):
        return str(caption.get("text") or "")
    return str(caption or post.get("caption_text") or "")


def post_url(post: dict[str, Any]) -> str:
    code = post.get("code") or post.get("shortcode")
    if code:
        return f"https://www.instagram.com/p/{code}/"
    return str(post.get("url") or post.get("permalink") or "")


def walk_for_urls(value: Any, urls: list[str]) -> None:
    if isinstance(value, dict):
        for child in value.values():
            walk_for_urls(child, urls)
    elif isinstance(value, list):
        for child in value:
            walk_for_urls(child, urls)
    elif isinstance(value, str) and "instagram.com/" in value:
        urls.append(value)


def safe_json(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def one_line(value: str) -> str:
    return " ".join(value.split())


if __name__ == "__main__":
    main()
