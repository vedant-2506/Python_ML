import hashlib
import secrets
from datetime import datetime, timedelta, timezone
import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from .config import get_settings
from .database import connection

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(comp_id: int, email: str) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(comp_id), "email": email, "iat": now,
                       "exp": now + timedelta(minutes=s.jwt_expire_minutes)}, s.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc


def current_company(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    claims = decode_access_token(credentials.credentials)
    try:
        comp_id = int(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid authentication token") from exc
    return {"comp_id": comp_id, "email": claims.get("email", "")}


def new_exam_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).hexdigest()


def exam_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
