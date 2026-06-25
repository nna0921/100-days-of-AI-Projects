from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from backend.auth import create_token, decode_token
from backend.roles import USERS, ROLE_PERMISSIONS
from backend.rag import get_rag_response

app = FastAPI(title="FinSolve RBAC Chatbot")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

class ChatRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    role: str

def get_current_user(token: str = Depends(oauth2_scheme)):
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload

@app.post("/auth/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = USERS.get(form_data.username)
    if not user or user["password"] != form_data.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(form_data.username, user["role"], user["name"])
    return {"access_token": token, "token_type": "bearer"}

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, current_user: dict = Depends(get_current_user)):
    role = current_user["role"]
    allowed_departments = ROLE_PERMISSIONS[role]
    result = get_rag_response(request.query, allowed_departments)
    return ChatResponse(
        answer=result["answer"],
        sources=result["sources"],
        role=role
    )

@app.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):
    return {"email": current_user["sub"], "role": current_user["role"], "name": current_user["name"]}