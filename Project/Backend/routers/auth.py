from fastapi import APIRouter, Depends, HTTPException, Query
from ..core.database import transaction
from ..core.security import create_access_token, hash_password, verify_password
from ..core.config import get_settings
from ..schemas.common import LoginRequest, SignupRequest
from jose import jwt

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/signup")
def signup(payload: SignupRequest):
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT comp_id FROM company WHERE lower(email)=lower(%s)", (payload.email,))
            if cur.fetchone():
                raise HTTPException(409, "An account with that email already exists")
            cur.execute("""INSERT INTO company(company_name,email,password_hash,is_verified)
                           VALUES(%s,%s,%s,TRUE) RETURNING comp_id""",
                        (payload.company_name, payload.email, hash_password(payload.password)))
            comp_id = cur.fetchone()[0]
    return {"comp_id": comp_id, "email": payload.email, "is_verified": True,
            "message": "Account created. You can now log in."}


@router.get("/verify-email")
def verify_email(token: str = Query(...)):
    try:
        claims = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
        comp_id = int(claims["comp_id"])
    except Exception as exc:
        raise HTTPException(400, "Invalid or expired verification token") from exc
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE company SET is_verified=TRUE WHERE comp_id=%s", (comp_id,))
    return {"verified": True}


@router.post("/login")
def login(payload: LoginRequest):
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT comp_id,email,password_hash,company_name,is_verified FROM company WHERE lower(email)=lower(%s)",
                        (payload.email,))
            row = cur.fetchone()
    if not row or not verify_password(payload.password, row[2]):
        raise HTTPException(401, "Invalid email or password")
    if not row[4]:
        raise HTTPException(403, "Email address is not verified")
    return {"token": create_access_token(row[0], row[1]),
            "user": {"comp_id": row[0], "email": row[1], "name": row[3]}}
