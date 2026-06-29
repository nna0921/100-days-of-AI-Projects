from jose import jwt, JWTError
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret")
ALGORITHM = "HS256"

def create_token(email: str, role: str, name: str) -> str:
    payload = {
        "sub": email,
        "role": role,
        "name": name,
        "exp": datetime.utcnow() + timedelta(hours=8)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None