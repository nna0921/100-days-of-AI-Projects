"""
Probe script 1: confirm we can pull a Daraz category listing as clean JSON.
Run this first, standalone, before touching anything else.
"""
import requests
import json
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.daraz.pk/",
}

def probe_category(category_slug: str):
    """
    category_slug examples: 'wireless-earbuds', 'smartphones'
    Find the real slug by browsing daraz.pk and copying the URL path.
    """
    url = f"https://www.daraz.pk/{category_slug}/"
    params = {"ajax": "true", "page": "1"}

    resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
    print("Status code:", resp.status_code)
    print("Content-Type:", resp.headers.get("Content-Type"))

    try:
        data = resp.json()
    except json.JSONDecodeError:
        print("FAILED — did not get JSON back. First 500 chars of response:")
        print(resp.text[:500])
        return None

    items = data.get("mods", {}).get("listItems", [])
    print(f"SUCCESS — got {len(items)} items back")

    if items:
        sample = items[0]
        print("\nSample item keys:", list(sample.keys()))
        print("\nSample item (trimmed):")
        print(json.dumps({
            "name": sample.get("name"),
            "productUrl": sample.get("productUrl"),
            "ratingScore": sample.get("ratingScore"),
            "review": sample.get("review"),
        }, indent=2))

    return data

if __name__ == "__main__":
    for slug in ["wireless-earphones-headsets", "wireless-earbuds", "smartphones", "laptops", "wireless-earphones", "earbuds", "bluetooth-earphones"]:
        print(f"\n{'='*50}\nTrying slug: {slug}\n{'='*50}")
        result = probe_category(slug)
        if result and result.get("mods", {}).get("listItems"):
            break
        time.sleep(2)
