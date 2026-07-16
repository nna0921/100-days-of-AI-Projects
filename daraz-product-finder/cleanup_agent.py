"""
Cleanup Agent: single Gemini pass that translates Roman-Urdu review text and
fixes typos, so the Insight Agent reads clean English instead of a mix of
scripts/spellings. Reads the raw scraped dataset, writes cleaned_reviews.json
(same product/review structure, each review gets a "cleaned_text" field).
"""
import json
import os
import time

from dotenv import load_dotenv
from google import genai

CATEGORY_SLUG = os.environ.get("DARAZ_CATEGORY", "wireless-earbuds")
_SUFFIX = "" if CATEGORY_SLUG == "wireless-earbuds" else f"_{CATEGORY_SLUG}"

INPUT_FILE = f"output/raw/daraz_reviews_dataset{_SUFFIX}.json"
OUTPUT_DIR = "output/cleaned"
OUTPUT_FILE = f"{OUTPUT_DIR}/cleaned_reviews{_SUFFIX}.json"

GEMINI_MODEL = "gemini-flash-lite-latest"
BATCH_SIZE = 40
MAX_ATTEMPTS = 4
RETRYABLE_MARKERS = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")


def call_gemini(client, prompt):
    schema = {"type": "ARRAY", "items": {"type": "STRING"}}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL, contents=prompt,
                config={"response_mime_type": "application/json",
                        "response_schema": schema},
            )
            return json.loads(resp.text)
        except Exception as e:
            retryable = any(m in str(e) for m in RETRYABLE_MARKERS)
            if retryable and attempt < MAX_ATTEMPTS:
                time.sleep(2 ** attempt)
                continue
            print(f"  WARN: cleanup batch failed ({e}); leaving unchanged")
            return None


def main():
    print(f"Loading {INPUT_FILE}...")
    data = json.load(open(INPUT_FILE, encoding="utf-8"))
    all_reviews = [r for p in data for r in p["reviews"]]
    print(f"  {len(all_reviews)} reviews to clean")

    load_dotenv()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    for i in range(0, len(all_reviews), BATCH_SIZE):
        batch = all_reviews[i:i + BATCH_SIZE]
        texts = [r["text"] for r in batch]
        prompt = (
            "These are customer reviews from Daraz (Pakistani e-commerce), "
            "mixing English, Roman Urdu, and typos. For each review, return "
            "a cleaned English version: translate Roman Urdu to English, fix "
            "typos, keep the original meaning and tone, keep already-correct "
            "English mostly unchanged. Return a JSON array of strings, same "
            "length and order as input.\n\n"
            f"Reviews: {json.dumps(texts, ensure_ascii=False)}"
        )
        cleaned = call_gemini(client, prompt)
        for j, r in enumerate(batch):
            r["cleaned_text"] = (cleaned[j].strip() if cleaned and j < len(cleaned)
                                  else r["text"])
        print(f"  cleaned batch {i // BATCH_SIZE + 1} "
              f"({min(i + BATCH_SIZE, len(all_reviews))}/{len(all_reviews)})")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved cleaned dataset to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
