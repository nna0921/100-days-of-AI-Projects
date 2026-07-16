"""
Probe: does Daraz honor `sort=topsales` on category listing endpoints?

Compares the first-page results returned by the default sort (bestmatch)
vs sort=topsales for the same category. If topsales works, we expect:
  1. A different ordering than the default
  2. Products at the top having higher review counts (proxy for sales)

Run this BEFORE editing main_scraper.py -- if topsales isn't honored, we
fall back to fetch-more-and-sort-by-review-count instead.
"""
import requests
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.daraz.pk/",
}

CATEGORY_SLUG = "wireless-earbuds"  # change to whichever slug you want to probe

# Values worth trying. Daraz's exact naming has varied over time, so try a
# few. The first one that returns a clearly different ordering wins.
SORT_VALUES_TO_TRY = ["topsales", "top_sales", "sales", "salesdesc", "popular"]


def fetch(category_slug, sort_value=None):
    url = f"https://www.daraz.pk/{category_slug}/"
    params = {"ajax": "true", "page": "1"}
    if sort_value:
        params["sort"] = sort_value

    resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError):
        return None
    return data.get("mods", {}).get("listItems", [])


def summarize(label, items):
    if not items:
        print(f"\n[{label}]  no items returned")
        return []
    print(f"\n[{label}]  {len(items)} items — top 5:")
    ids = []
    for item in items[:5]:
        name = (item.get("name") or "?")[:55]
        review_count = item.get("review") or 0
        price = item.get("price") or "?"
        item_url = item.get("itemUrl") or ""
        # First 15 chars of URL slug uniquely identifies the product
        ids.append(item_url[:60])
        print(f"  - {name!r}  ({review_count} reviews, Rs {price})")
    return ids


def main():
    print(f"Category: {CATEGORY_SLUG}")

    print("\n" + "=" * 60)
    print("BASELINE — Daraz default sort (whatever it decides)")
    print("=" * 60)
    default_items = fetch(CATEGORY_SLUG)
    default_top5 = summarize("default", default_items)

    for sort_value in SORT_VALUES_TO_TRY:
        print("\n" + "=" * 60)
        print(f"TRYING — sort={sort_value}")
        print("=" * 60)
        items = fetch(CATEGORY_SLUG, sort_value=sort_value)
        top5 = summarize(f"sort={sort_value}", items)

        if not top5:
            print(f"  -> {sort_value} returned nothing usable, moving on")
            continue

        if top5 == default_top5:
            print(f"  -> {sort_value} returned SAME ordering as default. "
                  f"Either it's ignored, or default already IS this sort. "
                  f"Not conclusive on its own.")
        else:
            print(f"  -> {sort_value} returned a DIFFERENT ordering. "
                  f"This one is being honored by Daraz.")

    print("\n" + "=" * 60)
    print("DONE. Pick the sort value whose top 5 look most like 'bestsellers'")
    print("(highest review counts, not obviously random ordering).")
    print("=" * 60)


if __name__ == "__main__":
    main()
