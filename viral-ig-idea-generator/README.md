# Viral IG Idea Generator

Streamlit app for finding public Instagram reels and generating idea variations for a user's offer.

## What Works

The app is built around the SociaVault endpoints we verified:

- `google/search` for niche discovery using `site:instagram.com/reel/`
- `instagram/post-info` for resolving candidate URLs
- `instagram/transcript` for reel hook extraction

There is no published SociaVault Instagram hashtag endpoint, so the app does not depend on hashtags.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Add your keys:

```bash
SOCIAVAULT_API_KEY=your_sociavault_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
```

Gemini is optional. Without it, the app uses a local fallback generator.

## Run

```bash
.venv/bin/streamlit run app.py
```

## Credit Strategy

Niche search mode costs roughly:

```text
1 credit for Google discovery
+ 1 credit per resolved Instagram reel URL
+ 1 credit per selected reel transcript
```

The app caps resolved URLs by default so a demo does not burn all free credits.
