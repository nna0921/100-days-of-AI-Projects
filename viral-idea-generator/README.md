# Viral Post Idea Generator

Streamlit app that finds current high-engagement Reddit posts for a niche, extracts the hook pattern, and adapts that pattern to your offer.

## Reddit Data Source

The app uses `old.reddit.com` HTML because it is current Reddit data and does not require API credentials.

- No Reddit app required
- Current subreddit/search/top pages, not archive data
- Includes score, comment count, post URL, title, and timestamp from page markup
- Less stable than the official API because it parses HTML

PullPush is not used.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Gemini is optional:

```bash
GEMINI_API_KEY=your_gemini_api_key_here
```

Without Gemini, the app uses a local fallback idea generator.

## Run

```bash
.venv/bin/streamlit run app.py
```
