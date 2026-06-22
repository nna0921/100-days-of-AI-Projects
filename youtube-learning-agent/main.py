from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
from google import genai
from google.genai import types
from dotenv import load_dotenv
import os
import re

load_dotenv()

app = FastAPI()
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


class ProcessRequest(BaseModel):
    video_url: str
    sender_email: str | None = None

class ProcessResponse(BaseModel):
    video_id: str
    video_url: str
    transcript_preview: str | None
    notes: str
    cached: bool = False


def extract_video_id(url: str) -> str:
    match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
    if not match:
        raise ValueError(f"Could not extract video ID from: {url}")
    return match.group(1)

def get_transcript(video_id: str) -> str | None:
    try:
        ytt_api = YouTubeTranscriptApi()
        fetched = ytt_api.fetch(video_id)
        return " ".join(snippet.text for snippet in fetched)
    except (TranscriptsDisabled, NoTranscriptFound):
        return None

def generate_study_material(video_url: str) -> str:
    prompt = """You are a study assistant. Based on this video, produce:
1. STRUCTURED NOTES — organized under topic headings
2. SUMMARY — 3-5 sentences
3. QUIZ — 5 questions with an answer key
4. FLASHCARDS — 5 question/answer pairs"""

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=types.Content(parts=[
            types.Part(text=prompt),
            types.Part(file_data=types.FileData(file_uri=video_url)),
        ])
    )
    return response.text


@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/process", response_model=ProcessResponse)
def process_video(req: ProcessRequest):
    try:
        video_id = extract_video_id(req.video_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    transcript = get_transcript(video_id)

    try:
        notes = generate_study_material(req.video_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini error: {str(e)}")

    return ProcessResponse(
        video_id=video_id,
        video_url=req.video_url,
        transcript_preview=transcript[:300] if transcript else None,
        notes=notes,
        cached=False
    )