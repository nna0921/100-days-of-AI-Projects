import os
import json
import tempfile
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.concurrency import run_in_threadpool

from transcribe import transcribe_chunk
from agent import TicketSession

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(BASE_DIR, "..", "index.html")

@app.get("/")
async def get_index():
    return FileResponse(INDEX_PATH)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session = TicketSession()
    try:
        while True:
            data = await websocket.receive()
            text_input = None
            
            if "bytes" in data:
                audio_bytes = data["bytes"]
                with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
                    tmp.write(audio_bytes)
                    tmp_path = tmp.name
                
                try:
                    transcript = await run_in_threadpool(transcribe_chunk, tmp_path)
                finally:
                    os.remove(tmp_path)
                
                text_input = transcript
                await websocket.send_json({"type": "transcript", "text": transcript})
                
            elif "text" in data:
                msg = json.loads(data["text"])
                if msg.get("type") == "text":
                    text_input = msg["text"]

            if text_input:
                try:
                    # Run the synchronous agent logic in a separate thread
                    reply = await run_in_threadpool(session.send, text_input)
                    
                    # Send the agent's reply and the current draft state back to the UI
                    await websocket.send_json({
                        "type": "agent",
                        "text": reply,
                        "draft": session.draft,
                        "ticket_created": session.ticket_created
                    })
                except Exception as e:
                    # Send a structured error to the frontend instead of disconnecting
                    await websocket.send_json({"type": "error", "text": f"Error: {str(e)}"})

    except WebSocketDisconnect:
        pass