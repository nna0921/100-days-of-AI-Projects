from __future__ import annotations

import json
import os
import re

from reddit_api import ViralPost

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
DEFAULT_GEMINI_FALLBACK_MODELS = ["gemini-3.1-flash-lite"]


class IdeaGenerationError(RuntimeError):
    pass


def generate_ideas(
    niche: str,
    offering: str,
    audience: str,
    tone: str,
    posts: list[ViralPost],
    allow_local_fallback: bool = True,
) -> list[dict]:
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        ideas = _generate_with_gemini(api_key, niche, offering, audience, tone, posts)
        if ideas:
            return ideas
        if not allow_local_fallback:
            raise IdeaGenerationError("Gemini returned no usable ideas.")
    elif not allow_local_fallback:
        raise IdeaGenerationError("GEMINI_API_KEY is missing, so AI write-up generation cannot run.")
    return _generate_locally(niche, offering, audience, tone, posts)


def _generate_with_gemini(
    api_key: str,
    niche: str,
    offering: str,
    audience: str,
    tone: str,
    posts: list[ViralPost],
) -> list[dict]:
    try:
        from google import genai
    except ImportError:
        return []

    try:
        from google.genai import types
    except ImportError:
        types = None

    timeout_ms = int(os.getenv("GEMINI_TIMEOUT_MS", "20000"))
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=timeout_ms) if types else None,
    )
    source_posts = [
        {
            "url": post.url,
            "subreddit": post.subreddit,
            "title": post.title,
            "body": post.body,
            "top_comment": post.top_comment,
            "score": post.score,
            "comments": post.comment_count,
            "viral_score": post.viral_score,
        }
        for post in posts[:2]
    ]

    prompt = f"""
You are a senior Instagram content strategist.
Goal: Analyze viral Reddit posts, extract their reusable hook/narrative pattern
(the thing that made people upvote and comment), then create original Instagram
reel/post ideas for the user's offering, adapted to Instagram's short-form format.

User niche: {niche}
Target audience: {audience}
Offering: {offering}
Tone: {tone}

Viral source posts (from Reddit, used only as pattern inspiration, not to be copied):
{json.dumps(source_posts, indent=2)}

Return only valid JSON:
{{
  "ideas": [
    {{
      "source_pattern": "the viral structure in plain English",
      "hook": "new original hook for the user's offering, native to Instagram",
      "caption": "original Instagram caption",
      "reel_outline": ["shot 1", "shot 2", "shot 3"],
      "cta": "short CTA",
      "why_it_maps": "why this uses the same pattern without copying",
      "source_url": "source reddit post URL"
    }}
  ]
}}

Rules:
- Create at most 2 ideas.
- Each idea should be a variation based on one of the top source posts.
- Do not copy phrases from the source title/body/comment.
- Translate the Reddit-native structure (long text, discussion thread) into an
  Instagram-native structure (visual hook in first 2 seconds, short spoken/on-screen text).
- Keep hooks specific, not generic.
- Make the output useful for the user's offering, not just a generic caption.
""".strip()

    errors: list[str] = []
    for model in _gemini_model_candidates():
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            break
        except Exception as exc:
            errors.append(f"{model}: {exc}")
    else:
        raise IdeaGenerationError("Gemini generation failed. " + " | ".join(errors))

    try:
        parsed = json.loads(_extract_json(getattr(response, "text", "") or ""))
    except json.JSONDecodeError as exc:
        raise IdeaGenerationError("Gemini returned non-JSON output. Try again.") from exc
    return _normalize_ideas(parsed.get("ideas", []))


def _gemini_model_candidates() -> list[str]:
    configured = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
    fallback = os.getenv("GEMINI_FALLBACK_MODELS", ",".join(DEFAULT_GEMINI_FALLBACK_MODELS))
    models = [configured]
    models.extend(model.strip() for model in fallback.split(",") if model.strip())

    deduped: list[str] = []
    for model in models:
        if model not in deduped:
            deduped.append(model)
    return deduped


def _generate_locally(
    niche: str,
    offering: str,
    audience: str,
    tone: str,
    posts: list[ViralPost],
) -> list[dict]:
    ideas: list[dict] = []
    for index, post in enumerate(posts[:2], start=1):
        pattern = infer_pattern(post)
        hook = local_hook(pattern, offering, audience, index)
        ideas.append(
            {
                "source_pattern": pattern,
                "hook": hook,
                "caption": (
                    f"{hook}\n\n"
                    f"If you are {audience}, this is the shift: {offering} is not about doing more. "
                    f"It is about making the next step obvious, repeatable, and easy to start.\n\n"
                    f"Save this before you plan your next move."
                ),
                "reel_outline": [
                    "Open with the hook as on-screen text in the first 2 seconds.",
                    "Show the common mistake or desire the audience already recognizes.",
                    f"Bridge to {offering} as the cleaner solution.",
                    "End with one simple action or question.",
                ],
                "cta": "Comment 'PLAN' and I will send the next step.",
                "why_it_maps": (
                    f"It keeps the viral structure ({pattern.lower()}) but changes the topic, promise, "
                    f"and proof point for {niche}."
                ),
                "source_url": post.url,
            }
        )
    return ideas


def infer_pattern(post: ViralPost) -> str:
    text = f"{post.title} {post.body} {post.top_comment}".lower()
    if re.search(r"\b\d+\b", text) or "ways" in text or "mistakes" in text or "tips" in text:
        return "Numbered list hook with quick, repeatable takeaways"
    if "update" in text or "story" in text or "happened to me" in text or "i was" in text:
        return "Founder/personal-story arc with a transformation moment"
    if "?" in post.title or "am i" in text or "which" in text:
        return "Question-led engagement hook that invites comments"
    if "unpopular opinion" in text or "hot take" in text:
        return "Contrarian take that challenges a common assumption"
    return "Relatable moment hook with a simple payoff"


def local_hook(pattern: str, offering: str, audience: str, index: int) -> str:
    templates = [
        "3 signs your current approach is making this harder than it needs to be",
        f"The simple way {audience} can finally make progress without starting over",
        f"Most {audience} do not need more motivation. They need this instead.",
    ]
    if "question" in pattern.lower():
        return f"Which part of {offering} would change your week fastest?"
    if "contrarian" in pattern.lower():
        return f"Unpopular opinion: most advice about {offering.split(' for ')[0].lower()} is backwards"
    return templates[(index - 1) % len(templates)]


def _extract_json(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return text.strip()


def _normalize_ideas(raw_ideas: list[dict]) -> list[dict]:
    ideas = []
    for item in raw_ideas[:2]:
        ideas.append(
            {
                "source_pattern": item.get("source_pattern", ""),
                "hook": item.get("hook", ""),
                "caption": item.get("caption", ""),
                "reel_outline": item.get("reel_outline") or [],
                "cta": item.get("cta", ""),
                "why_it_maps": item.get("why_it_maps", ""),
                "source_url": item.get("source_url", ""),
            }
        )
    return ideas
