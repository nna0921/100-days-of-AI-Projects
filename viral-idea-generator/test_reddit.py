from reddit_api import RedditClient, RedditError, suggest_subreddits

def main():
    niche = "fitness coach busy dads"
    subs = suggest_subreddits(niche)
    print("Suggested subreddits:", subs)

    client = RedditClient()
    try:
        posts = client.find_viral_posts(niche, subreddits=subs, time_filter="month", limit=15)
    except RedditError as exc:
        print("ERROR:", exc)
        return

    print(f"\nFound {len(posts)} posts\n")
    for p in posts[:5]:
        print(f"[{p.viral_score}] r/{p.subreddit} — {p.title}")
        print(f"  score={p.score} comments={p.comment_count}")
        print(f"  {p.url}\n")

if __name__ == "__main__":
    main()