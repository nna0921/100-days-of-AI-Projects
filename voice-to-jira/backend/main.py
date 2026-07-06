import tempfile
import os
from fastapi import FastAPI, UploadFile
from fastapi.concurrency import run_in_threadpool
from faster_whisper import WhisperModel

app = FastAPI()

model = WhisperModel("base", device="cpu", compute_type="int8")

def transcribe_file(file_path: str) -> str:
    segments, _ = model.transcribe(file_path)
    return " ".join(seg.text for seg in segments)

@app.post("/api/transcribe")
async def transcribe(audio: UploadFile):
    suffix = os.path.splitext(audio.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await audio.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        transcript = await run_in_threadpool(transcribe_file, tmp_path)
    finally:
        os.remove(tmp_path)

    return {"transcript": transcript}