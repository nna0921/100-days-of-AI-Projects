from __future__ import annotations

import json
import os
import re

from sociavault_api import ViralPost


def generate_ideas(
    niche: str,
    offering: str,
    audience: str,
    tone: str,
    reels: list[ViralPost],
) -> list[dict]:
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        ideas = _generate_with_gemini(api_key, niche, offering, audience, tone, reels)
        if ideas:
            return ideas
    return _generate_locally(niche, offering, audience, tone, reels)


def _generate_with_gemini(
    api_key: str,
    niche: str,
    offering: str,
    audience: str,
    tone: str,
    reels: list[ViralPost],
) -> list[dict]:
    try:
        from google import genai
    except ImportError:
        return []

    client = genai.Client(api_key=api_key)
    source_reels = [
        {
            "url": post.url,
            "caption": post.caption,
            "transcript": post.transcript,
            "likes": post.like_count,
            "comments": post.comment_count,
            "plays": post.play_count,
            "score": post.score,
        }
        for post in reels[:2]
    ]
    prompt = f"""
You are a senior Instagram content strategist.

Goal: Analyze viral Instagram reels, extract their reusable content pattern, then create original ideas for the user's offering.

User niche: {niche}
Target audience: {audience}
Offering: {offering}
Tone: {tone}

Viral source reels:
{json.dumps(source_reels, indent=2)}

Return only valid JSON:
{{
  "ideas": [
    {{
      "source_pattern": "the viral structure in plain English",
      "hook": "new original hook for the user's offering",
      "caption": "original Instagram caption",
      "reel_outline": ["shot 1", "shot 2", "shot 3"],
      "cta": "short CTA",
      "why_it_maps": "why this uses the same pattern without copying",
      "source_url": "source reel URL"
    }}
  ]
}}

Rules:
- Create at most 2 ideas.
- Each idea should be a variation based on one of the top source reels.
- Do not copy phrases from the source caption.
- Keep hooks specific and native to Instagram.
- If transcript exists, prioritize the opening spoken/on-screen hook.
- Make the output useful for the user's offering, not just a generic caption.
""".strip()

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
    except Exception:
        return []

    try:
        parsed = json.loads(_extract_json(getattr(response, "text", "") or ""))
    except json.JSONDecodeError:
        return []
    return _normalize_ideas(parsed.get("ideas", []))


def _generate_locally(
    niche: str,
    offering: str,
    audience: str,
    tone: str,
    reels: list[ViralPost],
) -> list[dict]:
    ideas: list[dict] = []
    for index, post in enumerate(reels[:2], start=1):
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
    text = f"{post.caption} {post.transcript}".lower()
    if re.search(r"\b\d+\b", text) or "ways" in text or "mistakes" in text:
        return "Numbered list hook with quick, repeatable takeaways"
    if "story" in text or "from " in text or "first" in text:
        return "Founder-style story arc with a transformation moment"
    if "which" in text or "?" in text:
        return "Question-led engagement hook that invites comments"
    if "when" in text:
        return "Relatable moment hook with a simple payoff"
    return "Aspirational product-led hook with a clear visual promise"


def local_hook(pattern: str, offering: str, audience: str, index: int) -> str:
    templates = [
        "3 signs your current approach is making this harder than it needs to be",
        f"The simple way {audience} can finally make progress without starting over",
        f"Most {audience} do not need more motivation. They need this instead.",
    ]
    if "question" in pattern.lower():
        return f"Which part of {offering} would change your week fastest?"
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
