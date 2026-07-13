"""
Main scraper for Project 08 - AI Product Recommendation Engine.
Pulls a batch of products from a Daraz category, then pulls reviews for
each product, and saves everything to a single JSON file the rest of
the pipeline (taxonomy discovery, agent pipeline) will read from.

This is a ONE-TIME data pull -- run it once, cache the output, and build
the rest of the project against the saved file so you're not hitting
Daraz repeatedly.
"""
import requests
import re
import json
import time
import random

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.daraz.pk/",
}

CATEGORY_SLUG = "wireless-earbuds"
NUM_PRODUCTS = 5          # keep this small for the 3-day build
REVIEWS_PER_PRODUCT = 50  # Let's try 50 to see if it caps out
OUTPUT_FILE = "daraz_reviews_dataset.json"


def get_products(category_slug: str, limit: int):
    url = f"https://www.daraz.pk/{category_slug}/"
    params = {"ajax": "true", "page": "1"}
    resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
    data = resp.json()
    items = data.get("mods", {}).get("listItems", [])

    products = []
    for item in items:
        item_url = item.get("itemUrl")
        if not item_url:
            continue
        full_url = "https:" + item_url if item_url.startswith("//") else item_url
        match = re.search(r"-i(\d+)", full_url)
        if not match:
            continue
        products.append({
            "name": item.get("name"),
            "item_id": match.group(1),
            "url": full_url,
            "rating": item.get("ratingScore"),
        })
        if len(products) >= limit:
            break

    print(f"Collected {len(products)} products with valid IDs")
    return products


def get_reviews(item_id: str, page_size: int):
    url = "https://my.daraz.pk/pdp/review/getReviewList"
    params = {"itemId": item_id, "pageSize": page_size, "filter": 0, "sort": 0}

    resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
    try:
        data = resp.json()
    except json.JSONDecodeError:
        print(f"  Failed to parse reviews for item {item_id}")
        return []

    items = data.get("model", {}).get("items", [])
    reviews = []
    for r in items:
        content = r.get("reviewContent", "").strip()
        if content:
            reviews.append({
                "text": content,
                "date": r.get("reviewTime"),
                "review_id": r.get("reviewRateId"),
            })
    return reviews


def main():
    print(f"Fetching product list for category: {CATEGORY_SLUG}")
    products = get_products(CATEGORY_SLUG, NUM_PRODUCTS)

    dataset = []
    for i, product in enumerate(products, 1):
        print(f"\n[{i}/{len(products)}] Fetching reviews for: {product['name'][:60]}...")
        reviews = get_reviews(product["item_id"], REVIEWS_PER_PRODUCT)
        print(f"  Got {len(reviews)} reviews")

        dataset.append({
            "product_name": product["name"],
            "product_url": product["url"],
            "item_id": product["item_id"],
            "rating": product["rating"],
            "reviews": reviews,
        })

        # Be polite -- random delay between requests so we don't look like a bot hammer
        delay = random.uniform(2, 4)
        time.sleep(delay)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    total_reviews = sum(len(p["reviews"]) for p in dataset)
    print(f"\nDone. Saved {len(dataset)} products, {total_reviews} total reviews to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
