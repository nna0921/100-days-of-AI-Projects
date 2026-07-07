# Voice-to-Jira agent

A chat-style web UI: click the mic, talk, get transcribed, and the agent
asks follow-up questions until every ticket field is filled -- then it
summarizes and waits for your explicit confirmation before actually
creating the Jira ticket.

## Files

- `ticket_schema.py` -- the required fields + completeness check
- `jira_tool.py` -- `create_jira_ticket()`, built directly from your `test-jira.py`
- `transcribe.py` -- `transcribe_chunk()`, built directly from your `test_transcribe.py`
- `agent.py` -- `TicketSession`, the Gemini conversation loop with the confirmation gate (also runnable standalone as a text-only CLI, see below)
- `main.py` -- FastAPI app: serves the UI and handles the WebSocket
- `static/index.html` -- the chat UI (mic button, message list, live ticket draft panel)

## Setup (all free)

```bash
pip install -r requirements.txt --break-system-packages
cp .env.example .env
# fill in .env with your real Jira + Gemini credentials
```

Get a free Gemini API key at https://aistudio.google.com/apikey -- no card required.

## Run the full app

```bash
uvicorn main:app --reload
```

Then open **http://localhost:8000** in your browser (Chrome or Edge --
`MediaRecorder`'s webm/opus output is best supported there; Firefox works
too). Click the mic, say something like:

> "I need to file a bug, the login page crashes on mobile when you rotate the screen"

Click the mic again to stop and send. The agent's reply appears as a chat
bubble, is spoken aloud via the browser's built-in TTS, and the right-hand
panel fills in the ticket fields live as Gemini extracts them. There's also
a text box below the mic if you want to type instead of talk, for quick
testing without touching audio at all.

Once every field is filled, the agent summarizes and asks you to confirm.
Only after you say something like "yes, go ahead" does it actually create
the Jira ticket -- the draft panel and a system message confirm when that
happens.

## Run just the conversation logic (no voice, no browser)

Useful for testing the field-gathering + confirmation flow in isolation:

```bash
python agent.py
```

## How the confirmation gate works

Gemini has two tools available:
- `update_ticket_fields` -- called silently, every turn, as it learns things
- `create_jira_ticket` -- called only once, at the very end

The model deciding to call `create_jira_ticket` is **not** what creates the
ticket. `agent.py`'s `_handle_function_call` checks
`self.awaiting_confirmation` (which only becomes `True` once every required
field is filled) before actually running the Jira API call. If the model
tries to call it early, the tool call is rejected in code and Gemini is told
why, so it can't accidentally file an incomplete or unconfirmed ticket --
even if a prompt gets confused or a transcription is garbled.

## Free-tier verification (as of mid-2026)

- **Gemini 2.5 Flash**: free, no credit card, ~1,500 requests/day, ~10-15
  requests/minute. A full ticket conversation is usually 4-8 user turns,
  each costing 1-2 API calls (one for the reply, one more per tool-call
  round trip) -- so you're looking at roughly 10-20 calls per ticket, well
  under the daily cap even with heavy testing.
- **faster-whisper**: fully free, runs locally, no API cost or rate limit.
- **Jira REST API**: free on Jira's free plan (up to 10 users).

## Known trade-off worth mentioning in your writeup

Gemini's free tier RPM (10-15/min) means if you fire off tool-call chains
too fast in testing (e.g. spamming turns), you may hit a 429. Not a concern
for a real conversational pace (a human talking takes seconds between
turns), but worth a simple retry-with-backoff wrapper before you demo this
live, in case a request happens to land in a busy moment.

## Known limitations, worth knowing before you demo this

- **Push-to-talk, not continuous streaming.** The mic records one full turn
  at a time (click to start, click to stop, then it sends and transcribes).
  True word-by-word streaming would need a different ASR setup --
  faster-whisper doesn't support incremental streaming, so this chunk-per-turn
  approach is the correct trade-off, not a shortcut.
- **One conversation per browser tab.** `main.py` creates one `TicketSession`
  per WebSocket connection, so refreshing the page starts a fresh ticket.
- **Browser TTS is robotic but free.** If you want nicer-sounding voices
  later, that's a paid add-on (cloud TTS) -- not needed to demo the concept.

## Possible next steps

1. Voice activity detection (auto-stop recording on silence) instead of
   click-to-stop, for a more natural feel.
2. A "start over" / "edit a field" voice command, in case the user wants to
   correct something after the summary.
3. Deploy `main.py` somewhere with a public URL (e.g. free tier of Render or
   Fly.io) if you want a shareable demo link instead of localhost.