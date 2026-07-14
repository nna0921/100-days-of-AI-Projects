"""
Probe script 3: given one product URL, figure out where the review data
actually lives — either embedded in the page HTML as JSON, or behind a
separate review API endpoint.
"""
import requests
import re
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/json",
    "Referer": "https://www.daraz.pk/",
}

PRODUCT_URL = "https://www.daraz.pk/products/led-tws-enc-hifi-53-i675237624.html"


def extract_item_id(product_url: str):
    match = re.search(r"-i(\d+)", product_url)
    return match.group(1) if match else None


def try_embedded_json(product_url: str):
    print("\n--- Attempt A: look for embedded JSON in the product page HTML ---")
    resp = requests.get(product_url, headers=HEADERS, timeout=15)
    print("Status code:", resp.status_code)

    # Daraz often embeds a big JSON blob like: window.pdpData = {...};
    matches = re.findall(r"window\.(\w+)\s*=\s*(\{.*?\});", resp.text, re.DOTALL)
    print(f"Found {len(matches)} embedded window.* JSON blobs")

    for var_name, blob in matches:
        print(f" - window.{var_name} (length {len(blob)} chars)")
        if "review" in blob.lower():
            print(f"   ^ contains the word 'review' — likely candidate")

    # Save full HTML for manual inspection if needed
    with open("product_page.html", "w", encoding="utf-8") as f:
        f.write(resp.text)
    print("\nFull page HTML saved to product_page.html for manual Ctrl+F if needed")

    return matches


def try_review_api(item_id: str):
    print(f"\n--- Attempt B: try known Daraz review API pattern for item {item_id} ---")
    # Common pattern seen across Daraz scraping writeups — may need adjusting
    url = "https://my.daraz.pk/pdp/review/getReviewList"
    params = {"itemId": item_id, "pageSize": 10, "filter": 0, "sort": 0}

    resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
    print("Status code:", resp.status_code)
    print("Content-Type:", resp.headers.get("Content-Type"))

    try:
        data = resp.json()
        print("Got JSON back. Top-level keys:", list(data.keys()))
        print(json.dumps(data, indent=2)[:1000])
        return data
    except json.JSONDecodeError:
        print("Not JSON. First 300 chars:")
        print(resp.text[:300])
        return None


if __name__ == "__main__":
    item_id = extract_item_id(PRODUCT_URL)
    print("Extracted item ID:", item_id)

    try_embedded_json(PRODUCT_URL)
    try_review_api(item_id)
