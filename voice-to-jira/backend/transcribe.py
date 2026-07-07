"""
Wraps faster-whisper as a reusable function. Same model call as the user's
test_transcribe.py -- just returns plain text instead of printing segments,
so it can be called once per audio chunk later without re-loading the model
each time (the model is loaded once, at import time, and reused).
"""

from faster_whisper import WhisperModel

_model = WhisperModel("base", device="cpu", compute_type="int8")


def transcribe_chunk(audio_path: str) -> str:
    """
    Transcribes a single audio file (or short chunk) and returns the full
    text. Language is auto-detected per chunk, so Urdu, English, or a mix
    all work without extra config -- faster-whisper handles it natively.
    """
    segments, info = _model.transcribe(audio_path)
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return text