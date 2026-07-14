"""
Probe script 4: taxonomy discovery via noun-phrase clustering.

Standalone test of the Piece 2 idea -- extract noun phrases from review
text, filter out logistics/seller noise, embed the phrases locally, and
cluster them to see if meaningful product-aspect groups fall out (e.g.
"battery life", "sound quality", "comfort") before this gets wired into
the real pipeline.

Notes on the logistics filter:
  We now capture grade_items (LOGISTICS_REVIEW / PRODUCT_REVIEW /
  SELLER_REVIEW sub-scores) per review from main_scraper.py. Checked how
  discriminative that is on the current 250-review dataset: 205/250 give
  identical (5,5,5) scores and only 2 have a low PRODUCT_REVIEW score, so
  the numeric sub-scores alone barely move the needle on this sample --
  most logistics/seller pollution ("delivery", "seller", "daraz", "rider")
  shows up as an aside *inside* otherwise glowing 5/5/5 reviews, not as a
  separate low-scored review. So the real noise reduction lever here is a
  phrase-level stoplist applied after noun-chunk extraction, not a
  review-level grade_items filter. We still drop the couple of reviews
  with no PRODUCT_REVIEW score at all (no signal to cluster on), and we
  keep grade_items in the output per-phrase for Piece 4 to use later as a
  trust/weight signal.
"""
import json
import re
from collections import Counter, defaultdict

import spacy
from sentence_transformers import SentenceTransformer
from sklearn.cluster import AgglomerativeClustering

INPUT_FILE = "daraz_reviews_dataset.json"
OUTPUT_FILE = "taxonomy_probe_output.json"

MIN_PHRASE_COUNT = 2          # drop phrases mentioned only once (likely noise)
DISTANCE_THRESHOLD = 0.35     # cosine distance cutoff for clustering
EMBED_MODEL = "all-MiniLM-L6-v2"

# Phrases containing any of these words are about delivery/seller/platform,
# not the product itself -- drop them so they don't pollute product-aspect
# clusters.
LOGISTICS_STOPWORDS = {
    "delivery", "deliveries", "seller", "sellers", "daraz", "parcel",
    "parcels", "courier", "rider", "shipping", "shipment", "order",
    "orders", "refund", "customer", "shop", "store", "return", "returns",
}

GENERIC_STOPWORDS = {
    "it", "this", "that", "these", "those", "i", "you", "he", "she",
    "we", "they", "everything", "something", "anything", "one", "product",
    "products", "item", "items", "thing", "things",
}


def load_reviews(path):
    data = json.load(open(path, encoding="utf-8"))
    reviews = []
    for product in data:
        for r in product["reviews"]:
            grade_items = r.get("grade_items") or {}
            if grade_items.get("PRODUCT_REVIEW") is None:
                continue  # no product-specific signal to attach this phrase to
            reviews.append({
                "product_name": product["product_name"],
                "text": r["text"],
                "grade_items": grade_items,
            })
    return reviews


def normalize_chunk(chunk):
    # Strip leading determiners/pronouns/possessives so "the sound quality"
    # and "sound quality" collapse to the same phrase.
    tokens = [t for t in chunk if t.pos_ not in ("DET", "PRON")]
    if not tokens:
        return None
    text = " ".join(t.text.lower() for t in tokens).strip()
    text = re.sub(r"[^\w\s]", "", text).strip()
    if not text or len(text) < 3:
        return None
    words = set(text.split())
    if words & LOGISTICS_STOPWORDS:
        return None
    if words <= GENERIC_STOPWORDS:
        return None
    return text


def extract_phrases(reviews, nlp):
    phrase_counts = Counter()
    phrase_sources = defaultdict(list)  # phrase -> list of product names

    docs = nlp.pipe((r["text"] for r in reviews), batch_size=32)
    for review, doc in zip(reviews, docs):
        seen_in_review = set()
        for chunk in doc.noun_chunks:
            phrase = normalize_chunk(chunk)
            if phrase and phrase not in seen_in_review:
                seen_in_review.add(phrase)
                phrase_counts[phrase] += 1
                phrase_sources[phrase].append(review["product_name"])

    return phrase_counts, phrase_sources


def cluster_phrases(phrases, model):
    embeddings = model.encode(phrases, normalize_embeddings=True)
    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=DISTANCE_THRESHOLD,
        metric="cosine",
        linkage="average",
    )
    labels = clustering.fit_predict(embeddings)
    return labels


def main():
    print(f"Loading reviews from {INPUT_FILE}...")
    reviews = load_reviews(INPUT_FILE)
    print(f"  {len(reviews)} reviews have a PRODUCT_REVIEW score, proceeding with those")

    print("Loading spaCy model (en_core_web_sm)...")
    nlp = spacy.load("en_core_web_sm")

    print("Extracting and filtering noun phrases...")
    phrase_counts, phrase_sources = extract_phrases(reviews, nlp)
    print(f"  {len(phrase_counts)} distinct phrases before frequency filter")

    frequent_phrases = [p for p, c in phrase_counts.items() if c >= MIN_PHRASE_COUNT]
    print(f"  {len(frequent_phrases)} phrases mentioned >= {MIN_PHRASE_COUNT} times")

    if not frequent_phrases:
        print("No phrases survived filtering -- nothing to cluster. Exiting.")
        return

    print(f"Loading embedding model ({EMBED_MODEL})...")
    model = SentenceTransformer(EMBED_MODEL)

    print("Clustering...")
    labels = cluster_phrases(frequent_phrases, model)

    clusters = defaultdict(list)
    for phrase, label in zip(frequent_phrases, labels):
        clusters[int(label)].append(phrase)

    # Rank clusters by total mentions, and within each cluster rank phrases
    # by frequency so the most common phrase reads as the cluster label.
    cluster_output = []
    for label, members in clusters.items():
        members_sorted = sorted(members, key=lambda p: phrase_counts[p], reverse=True)
        total_mentions = sum(phrase_counts[p] for p in members)
        distinct_products = set()
        for p in members:
            distinct_products.update(phrase_sources[p])
        cluster_output.append({
            "cluster_id": label,
            "label_guess": members_sorted[0],
            "phrases": [{"phrase": p, "count": phrase_counts[p]} for p in members_sorted],
            "total_mentions": total_mentions,
            "num_products": len(distinct_products),
        })

    cluster_output.sort(key=lambda c: c["total_mentions"], reverse=True)

    print(f"\n{len(cluster_output)} clusters found. Top 15 by mentions:\n")
    for c in cluster_output[:15]:
        phrase_preview = ", ".join(p["phrase"] for p in c["phrases"][:6])
        print(f"  [{c['total_mentions']:>3} mentions, {c['num_products']} products] "
              f"{c['label_guess']!r}  <- {phrase_preview}")

    singleton_clusters = sum(1 for c in cluster_output if len(c["phrases"]) == 1)
    print(f"\n{singleton_clusters}/{len(cluster_output)} clusters are singletons (likely noise)")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(cluster_output, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(cluster_output)} clusters to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
