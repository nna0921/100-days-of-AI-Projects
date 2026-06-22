# %%
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai
from google.genai import types
from dotenv import load_dotenv
import os

load_dotenv()
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# %%
video_id = "7IeFVWJXp7E"
video_url = f"https://www.youtube.com/watch?v={video_id}"

ytt_api = YouTubeTranscriptApi()
fetched_transcript = ytt_api.fetch(video_id)
transcript_text = " ".join(snippet.text for snippet in fetched_transcript)

print(f"Transcript length: {len(transcript_text)} characters")
print(transcript_text[:500])

# %%
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

print(response.text)
# %%
