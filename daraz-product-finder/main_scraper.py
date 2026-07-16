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
import os

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.daraz.pk/",
}

# Category is env-configurable so the pipeline can run against a different
# Daraz category without touching code. Defaults to the original category
# this project was built and validated against, and -- critically -- the
# default filenames below stay byte-identical to before this was added, so
# existing runs/artifacts (and the Streamlit app reading them) are
# unaffected unless DARAZ_CATEGORY is explicitly overridden.
CATEGORY_SLUG = os.environ.get("DARAZ_CATEGORY", "wireless-earbuds")
_SUFFIX = "" if CATEGORY_SLUG == "wireless-earbuds" else f"_{CATEGORY_SLUG}"

NUM_PRODUCTS = 15
REVIEWS_PER_PRODUCT = 50  # Let's try 50 to see if it caps out
OUTPUT_DIR = "output/raw"
OUTPUT_FILE = f"{OUTPUT_DIR}/daraz_reviews_dataset{_SUFFIX}.json"

# Daraz silently ignores sort=topsales/top_sales/sales/salesdesc/popular on
# the category listing endpoint (probed directly -- all five returned an
# identical top-5 to the unsorted default, and the default ordering didn't
# correlate with review_count either). So instead of asking Daraz to sort,
# we fetch candidates and sort by review_count ourselves.
#
# get_products() runs three steps in order: (1) fetch -- page through the
# listing endpoint until the RAW pool (before any filtering) reaches
# MIN_RAW_POOL, or Daraz runs out of results; (2) filter -- drop off-category
# filler from that raw pool; (3) rank -- sort what's left by review_count
# and keep the top `limit`. Sizing the fetch off the raw count (not the
# post-filter count) means a strict relevance filter on a page-1-only fetch
# can't silently shrink the final candidate pool below what's actually
# available across more pages.
MIN_RAW_POOL = 40
FETCH_MULTIPLIER = 3  # raw pool target also scales with limit for large limit values
MAX_LISTING_PAGES = 6


def fetch_listing_page(category_slug, page):
    url = f"https://www.daraz.pk/{category_slug}/"
    params = {"ajax": "true", "page": str(page)}
    resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
    try:
        data = resp.json()
    except ValueError:
        return None
    return data.get("mods", {}).get("listItems", [])


def parse_listing_item(item):
    item_url = item.get("itemUrl")
    if not item_url:
        return None
    full_url = "https:" + item_url if item_url.startswith("//") else item_url
    # The actual item ID is always the -i<digits> segment right before
    # ".html". Product slugs can contain earlier "-i<digits>" false
    # matches (e.g. a model name like "I7" in the title becomes "-i7-"
    # in the slug), so anchor to the ".html" suffix instead of taking
    # the first match.
    match = re.search(r"-i(\d+)\.html", full_url)
    if not match:
        return None
    return {
        "name": item.get("name"),
        "item_id": match.group(1),
        "url": full_url,
        "rating": item.get("ratingScore"),
        "price": item.get("price"),
        "original_price": item.get("originalPrice"),
        "discount": item.get("discount"),
        "review_count": item.get("review"),
        "seller_name": item.get("sellerName"),
        "seller_id": item.get("sellerId"),
        "description": item.get("description"),
    }


def get_products(category_slug: str, limit: int):
    # Daraz sometimes backfills a thin or mismatched category page with
    # unrelated "trending" filler -- e.g. baby-toddler-strollers returning
    # a wall of handheld fans and air coolers alongside genuine strollers
    # (confirmed by direct probe: ~half the page was fan/cooler listings).
    # Drop anything whose name shares no token with the category slug.
    slug_tokens = [t.rstrip("s") for t in category_slug.lower().split("-") if len(t) >= 3]

    def is_relevant(p):
        name = (p.get("name") or "").lower()
        return any(t in name for t in slug_tokens)

    def review_count(p):
        try:
            return int(p.get("review_count") or 0)
        except (TypeError, ValueError):
            return 0

    raw_pool_target = max(MIN_RAW_POOL, limit * FETCH_MULTIPLIER)
    seen_ids = set()
    all_products = []
    pages_fetched = 0

    # Step 1: fetch -- keep paging until the RAW pool hits raw_pool_target
    # or Daraz has nothing left to give.
    for page in range(1, MAX_LISTING_PAGES + 1):
        items = fetch_listing_page(category_slug, page)
        if items is None:
            if page == 1:
                raise RuntimeError(
                    f"Daraz didn't return product data for category slug "
                    f"'{category_slug}' -- this usually means '{category_slug}' isn't "
                    f"a real Daraz category URL. Browse daraz.pk, find the category "
                    f"you want, and copy the exact slug from its URL, e.g. "
                    f"daraz.pk/wireless-earbuds/ -> 'wireless-earbuds'."
                ) from None
            break  # later pages 404ing/non-JSON just means we ran past the end
        if not items:
            break  # Daraz ran out of results for this category
        pages_fetched += 1

        new_count = 0
        for item in items:
            parsed = parse_listing_item(item)
            if not parsed or parsed["item_id"] in seen_ids:
                continue
            seen_ids.add(parsed["item_id"])
            all_products.append(parsed)
            new_count += 1

        if len(all_products) >= raw_pool_target or new_count == 0:
            break
        time.sleep(random.uniform(1, 2))  # polite delay between listing-page requests

    # Step 2: filter -- drop off-category filler from the raw pool.
    relevant = [p for p in all_products if is_relevant(p)]
    dropped = len(all_products) - len(relevant)
    candidates = relevant if relevant else all_products

    # Step 3: rank -- sort survivors by review_count and keep the top `limit`.
    candidates.sort(key=review_count, reverse=True)
    kept = candidates[:limit]

    filler_note = f", {dropped} dropped as off-category filler" if dropped else ""
    shortfall_note = (f" -- WARNING: category only has {len(kept)}, fewer than the requested {limit}"
                       if len(kept) < limit else "")
    print(f"Fetched {len(all_products)} raw products across {pages_fetched} page(s)"
          f"{filler_note}, {len(candidates)} relevant candidates, kept top {len(kept)}{shortfall_note}")
    return kept


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
        content = (r.get("reviewContent") or "").strip()
        if content:
            reviews.append({
                "text": content,
                "date": r.get("reviewTime"),
                "review_id": r.get("reviewRateId"),
                "rating": r.get("rating"),
                "grade_items": r.get("gradeItems"),
                "is_purchased": r.get("isPurchased"),
                "sku_info": r.get("skuInfo"),
                "up_votes": r.get("upVotes"),
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
            "price": product["price"],
            "original_price": product["original_price"],
            "discount": product["discount"],
            "review_count": product["review_count"],
            "seller_name": product["seller_name"],
            "seller_id": product["seller_id"],
            "description": product["description"],
            "reviews": reviews,
        })

        # Be polite -- random delay between requests so we don't look like a bot hammer
        delay = random.uniform(1, 2)
        time.sleep(delay)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    total_reviews = sum(len(p["reviews"]) for p in dataset)
    print(f"\nDone. Saved {len(dataset)} products, {total_reviews} total reviews to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
