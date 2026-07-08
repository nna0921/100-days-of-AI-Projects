import os
import json
import tempfile
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.concurrency import run_in_threadpool

from transcribe import transcribe_chunk
from agent import TicketSession
import oauth

app = FastAPI()

# Get the directory of the current file (backend) and find index.html in the parent
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(BASE_DIR, "..", "index.html")

@app.get("/")
async def get_index():
    return FileResponse(INDEX_PATH)

@app.get("/auth/jira/login")
async def jira_login():
    url, state = oauth.build_authorize_url()
    response = RedirectResponse(url)
    response.set_cookie("jira_state", state, httponly=True, max_age=600)
    return response

@app.get("/auth/jira/callback")
async def jira_callback(request: Request):
    error = request.query_params.get("error")
    if error:
        return RedirectResponse(f"/?jira_error={error}")

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    cookie_state = request.cookies.get("jira_state")

    if not state or not cookie_state or state != cookie_state or not oauth.verify_state(state):
        print(f"--- OAUTH STATE ERROR ---")
        print(f"URL State: {state}")
        print(f"Cookie State: {cookie_state}")
        print(f"In pending states? {state in oauth._PENDING_STATES if hasattr(oauth, '_PENDING_STATES') else 'unknown'}")
        return RedirectResponse("/?jira_error=invalid_state")

    try:
        session_id = oauth.start_connection(code)
        response = RedirectResponse("/")
        response.set_cookie("jira_session", session_id, httponly=True, max_age=86400*30)
        return response
    except Exception as e:
        return RedirectResponse(f"/?jira_error={e}")

@app.get("/auth/jira/status")
async def jira_status(request: Request):
    session_id = request.cookies.get("jira_session")
    site_name = oauth.get_site_name(session_id)
    if site_name:
        return {"connected": True, "site_name": site_name}
    return {"connected": False}

@app.post("/auth/jira/disconnect")
async def jira_disconnect():
    response = Response()
    response.delete_cookie("jira_session")
    return response

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = websocket.cookies.get("jira_session")
    try:
        jira_conn = oauth.get_connection(session_id)
    except Exception:
        jira_conn = None
    session = TicketSession(jira_conn=jira_conn)
    try:
        while True:
            data = await websocket.receive()
            text_input = None

            if "bytes" in data:
                audio_bytes = data["bytes"]
                # Save audio blob to a temporary file
                with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
                    tmp.write(audio_bytes)
                    tmp_path = tmp.name

                try:
                    # Run the CPU-bound transcription in a separate thread
                    transcript = await run_in_threadpool(transcribe_chunk, tmp_path)
                finally:
                    os.remove(tmp_path)

                text_input = transcript
                # Send the transcript back so the user sees what was heard
                await websocket.send_json({"type": "transcript", "text": transcript})

            elif "text" in data:
                msg = json.loads(data["text"])
                if msg.get("type") == "text":
                    text_input = msg["text"]

            if text_input:
                # Run the synchronous agent logic in a separate thread
                reply = await run_in_threadpool(session.send, text_input)

                # Send the agent's reply and the current draft state back to the UI
                await websocket.send_json({
                    "type": "agent",
                    "text": reply,
                    "draft": session.draft,
                    "ticket_created": session.ticket_created,
                    "ticket_url": session.ticket_url
                })

    except (WebSocketDisconnect, RuntimeError):
        # Handle the client disconnecting gracefully (e.g. closing the tab or navigating away to login)
        pass