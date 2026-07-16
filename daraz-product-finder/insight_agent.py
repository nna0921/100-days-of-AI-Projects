"""
Insight Agent: single Gemini pass over the cleaned reviews that does four
jobs in one call (keeps cost/complexity low -- still one Gemini call per
category):
  1. discovered_aspects -- what shoppers actually talk about (data-driven,
     not a fixed vocabulary -- discovered fresh per category).
  2. per_product_scorecard -- each product scored 1-10 per aspect based on
     review sentiment, with supporting quotes. 0 = not enough mentions to judge.
  3. missing_features -- things shoppers wish existed that no listed product offers.
  4. product_concepts -- 3 new-product ideas nobody in this niche currently sells.
Reads cleaned_reviews.json, writes insights.json (one JSON object).
"""
import json
import os
import time

# The sentiment model is already cached locally (see get_sentiment_pipe) --
# without this, huggingface_hub still does a network HEAD request per run to
# check for updates, which can hang/retry for minutes on a flaky connection
# for zero benefit. Must be set before transformers is imported.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from dotenv import load_dotenv
from google import genai
from transformers import pipeline as hf_pipeline

CATEGORY_SLUG = os.environ.get("DARAZ_CATEGORY", "wireless-earbuds")
CATEGORY_LABEL = CATEGORY_SLUG.replace("-", " ")
_SUFFIX = "" if CATEGORY_SLUG == "wireless-earbuds" else f"_{CATEGORY_SLUG}"

INPUT_FILE = f"output/cleaned/cleaned_reviews{_SUFFIX}.json"
OUTPUT_DIR = "output/insights"
OUTPUT_FILE = f"{OUTPUT_DIR}/insights{_SUFFIX}.json"

GEMINI_MODEL = "gemini-flash-lite-latest"
MAX_ATTEMPTS = 4
RETRYABLE_MARKERS = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")

INSIGHT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "discovered_aspects": {"type": "ARRAY", "items": {"type": "STRING"}},
        "per_product_scorecard": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "product_name": {"type": "STRING"},
                    "aspect_scores": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "aspect": {"type": "STRING"},
                                "score": {"type": "INTEGER"},
                                "quotes": {"type": "ARRAY", "items": {"type": "STRING"}},
                            },
                            "required": ["aspect", "score", "quotes"],
                        },
                    },
                },
                "required": ["product_name", "aspect_scores"],
            },
        },
        "missing_features": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "feature": {"type": "STRING"},
                    "evidence_count": {"type": "INTEGER"},
                    "example_quotes": {"type": "ARRAY", "items": {"type": "STRING"}},
                },
                "required": ["feature", "evidence_count", "example_quotes"],
            },
        },
        "product_concepts": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "concept": {"type": "STRING"},
                    "rationale": {"type": "STRING"},
                },
                "required": ["concept", "rationale"],
            },
        },
    },
    "required": ["discovered_aspects", "per_product_scorecard",
                 "missing_features", "product_concepts"],
}


def call_gemini(client, prompt):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL, contents=prompt,
                config={"response_mime_type": "application/json",
                        "response_schema": INSIGHT_SCHEMA},
            )
            return json.loads(resp.text)
        except Exception as e:
            retryable = any(m in str(e) for m in RETRYABLE_MARKERS)
            if retryable and attempt < MAX_ATTEMPTS:
                time.sleep(2 ** attempt)
                continue
            print(f"  WARN: insight call failed permanently ({e})")
            return None


SENTIMENT_MODEL = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
_sentiment_pipe = None


def get_sentiment_pipe():
    global _sentiment_pipe
    if _sentiment_pipe is None:
        _sentiment_pipe = hf_pipeline("sentiment-analysis", model=SENTIMENT_MODEL)
    return _sentiment_pipe


def check_scorecard_reliability(scorecard):
    """Independent reliability check on the LLM's per-aspect scores: run
    each aspect's supporting quotes through a local multilingual sentiment
    classifier (zero API calls, different model/training data than the
    Gemini judge that produced the score -- real independent verification,
    not the same model checking its own work) and flag cases where a high
    score (>=7) is backed by classifier-negative quotes, or a low score
    (<=4) by classifier-positive quotes, at classifier confidence > 0.6.
    Scores in the 5-6 middle band are skipped as genuinely ambiguous."""
    pipe = get_sentiment_pipe()
    flagged = 0
    for product in scorecard:
        for a in product.get("aspect_scores", []):
            quotes = a.get("quotes") or []
            score = a.get("score", 0)
            if not quotes or score == 0 or 5 <= score <= 6:
                a["sentiment_check"] = None
                continue
            pred = pipe(" ".join(quotes)[:1000])[0]
            label, confidence = pred["label"].lower(), pred["score"]
            expects_positive = score >= 7
            disagreement = confidence > 0.6 and (
                (expects_positive and label == "negative")
                or (not expects_positive and label == "positive")
            )
            a["sentiment_check"] = {
                "label": label, "confidence": round(confidence, 2), "disagreement": disagreement,
            }
            flagged += disagreement
    return flagged


def main():
    print(f"Loading {INPUT_FILE}...")
    data = json.load(open(INPUT_FILE, encoding="utf-8"))

    payload = []
    for product in data:
        for r in product["reviews"]:
            payload.append({
                "product_name": product["product_name"],
                "text": r.get("cleaned_text", r["text"]),
            })
    print(f"  {len(payload)} cleaned reviews across {len(data)} products")

    load_dotenv()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    prompt = (
        f"You are a market analyst reviewing customer reviews of {CATEGORY_LABEL} "
        "sold on Daraz (Pakistani e-commerce), across multiple competing products. "
        "Do four things:\n\n"
        "1. discovered_aspects: 5-8 aspects shoppers actually mention in these "
        "reviews (data-driven -- read the reviews, don't assume a fixed list).\n\n"
        "2. per_product_scorecard: for EACH product_name present in the reviews, "
        "score each discovered aspect 1-10 based on the sentiment expressed "
        "about it in that product's reviews, with 2-3 supporting quotes copied "
        "verbatim. Score 0 (with empty quotes) if that aspect isn't mentioned "
        "enough for that product to judge.\n\n"
        "3. missing_features: things shoppers wish existed or repeatedly "
        "complain are absent, that NO listed product currently offers well. "
        "Ignore generic praise and delivery/seller complaints.\n\n"
        "4. product_concepts: exactly 3 concrete new-product or new-variant "
        "ideas that nobody currently selling in this niche offers, each with a "
        "one-sentence rationale grounded in the review evidence.\n\n"
        f"Reviews: {json.dumps(payload, ensure_ascii=False)}"
    )
    result = call_gemini(client, prompt) or {
        "discovered_aspects": [], "per_product_scorecard": [],
        "missing_features": [], "product_concepts": [],
    }
    result["missing_features"].sort(key=lambda x: -x.get("evidence_count", 0))

    flagged = check_scorecard_reliability(result["per_product_scorecard"])
    print(f"\nSentiment cross-check: {flagged} score/quote disagreements flagged "
          f"(local classifier vs. Gemini score, zero extra API calls)")

    print(f"\nDiscovered aspects: {result['discovered_aspects']}")
    print(f"\n{len(result['missing_features'])} missing features:")
    for f in result["missing_features"][:15]:
        print(f"  [{f['evidence_count']:>3}] {f['feature']}")
    print(f"\n{len(result['product_concepts'])} product concepts:")
    for c in result["product_concepts"]:
        print(f"  - {c['concept']}: {c['rationale']}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\nSaved insights to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
