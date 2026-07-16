"""
Shared, framework-free analysis functions over the pipeline's JSON output.
Kept separate from app.py so the numbers (popularity score, market
structure) have one implementation, testable and importable without
pulling in Streamlit.
"""
import glob
import os
import re
from datetime import datetime

import numpy as np


def discover_categories(raw_dir="output/raw"):
    categories = {}
    for path in glob.glob(f"{raw_dir}/daraz_reviews_dataset*.json"):
        m = re.fullmatch(r"daraz_reviews_dataset(?:_(.+))?\.json", os.path.basename(path))
        if m:
            categories[m.group(1) or "wireless-earbuds"] = path
    return categories


def seller_diversity(dataset):
    """'Many listings, few sellers' signal -- groups products by seller_name
    and sums review_count per seller. A category where a handful of sellers
    hold most of the review volume is a dominated market; one where review
    volume is spread across many sellers is fragmented/easier to enter."""
    sellers = {}
    for p in dataset:
        name = p.get("seller_name") or "unknown"
        try:
            reviews = int(p.get("review_count") or 0)
        except (TypeError, ValueError):
            reviews = 0
        s = sellers.setdefault(name, {"seller": name, "products": 0, "total_reviews": 0})
        s["products"] += 1
        s["total_reviews"] += reviews
    rows = sorted(sellers.values(), key=lambda s: -s["total_reviews"])
    num_products = len(dataset)
    num_sellers = len(sellers)
    total_reviews = sum(s["total_reviews"] for s in rows)
    top_seller_share = (rows[0]["total_reviews"] / total_reviews) if rows and total_reviews else 0
    dominated = num_sellers <= max(1, num_products // 2) or top_seller_share >= 0.4
    return rows, num_products, num_sellers, top_seller_share, dominated


def estimated_reviews_per_month(product):
    """Popularity proxy: review_count / months since the earliest-dated
    review we scraped. Honest framing, not a sales estimate -- we only
    sample up to REVIEWS_PER_PRODUCT reviews, so the earliest scraped date
    is our best available proxy for 'how long has this been accumulating
    review_count', not the true listing date."""
    dates = []
    for r in product.get("reviews", []):
        try:
            dates.append(datetime.strptime(r["date"], "%d %b %Y"))
        except (KeyError, ValueError):
            continue
    if not dates:
        return None
    months = max((datetime.now() - min(dates)).days / 30.44, 1 / 30.44)
    try:
        review_count = int(product.get("review_count") or 0)
    except (TypeError, ValueError):
        return None
    return round(review_count / months, 1)


def popularity_score(dataset):
    """Composite popularity signal: review count, review velocity, average
    rating, and rating consistency (variance of individual review ratings),
    each standardized to a z-score across the products in this category
    then combined with fixed weights. Standardizing first matters because
    the raw features live on incomparable scales (review counts in the
    thousands vs. 1-5 ratings) -- z-scoring puts them on the same footing
    before weighting. Lower rating variance (more consistent reviews) is
    treated as a positive signal, so its z-score is negated."""
    review_counts, velocities, avg_ratings, variances = [], [], [], []
    for p in dataset:
        try:
            review_counts.append(float(p.get("review_count") or 0))
        except (TypeError, ValueError):
            review_counts.append(0.0)
        velocities.append(estimated_reviews_per_month(p) or 0.0)
        try:
            avg_ratings.append(float(p.get("rating") or 0))
        except (TypeError, ValueError):
            avg_ratings.append(0.0)
        review_ratings = [r["rating"] for r in p.get("reviews", [])
                           if isinstance(r.get("rating"), (int, float))]
        variances.append(float(np.var(review_ratings)) if len(review_ratings) >= 2 else 0.0)

    def zscore(values):
        arr = np.array(values, dtype=float)
        std = arr.std()
        return np.zeros_like(arr) if std == 0 else (arr - arr.mean()) / std

    composite = (
        0.25 * zscore(review_counts)
        + 0.30 * zscore(velocities)
        + 0.25 * zscore(avg_ratings)
        - 0.20 * zscore(variances)
    )
    return composite
