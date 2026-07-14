"""
Probe script 2a: dump the FULL raw item so we can find where the real
product URL actually lives (productUrl came back null in probe 1).
"""
import requests
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.daraz.pk/",
}

def dump_full_item(category_slug: str):
    url = f"https://www.daraz.pk/{category_slug}/"
    params = {"ajax": "true", "page": "1"}

    resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
    data = resp.json()
    items = data.get("mods", {}).get("listItems", [])

    if not items:
        print("No items found.")
        return

    # Dump the FULL first item, no trimming, so we can see every field
    print(json.dumps(items[0], indent=2))

    # Also save all items to a file so you can grep through them
    with open("raw_listing_sample.json", "w") as f:
        json.dump(items, f, indent=2)
    print(f"\nSaved {len(items)} full items to raw_listing_sample.json")
    print("Open that file and search for anything containing 'http' or '.pk'")
    print("to find the real product-link field name.")

if __name__ == "__main__":
    # Replace with whatever slug worked for you
    dump_full_item("wireless-earbuds")
