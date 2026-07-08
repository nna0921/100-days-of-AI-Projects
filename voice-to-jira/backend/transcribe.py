from faster_whisper import WhisperModel

_model = WhisperModel("base", device="cpu", compute_type="int8")


def transcribe_chunk(audio_path: str) -> str:
    segments, info = _model.transcribe(audio_path)
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return text