from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import settings

ALGO = "HS256"


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def _encode(payload: dict, minutes: int) -> str:
    payload = {**payload, "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes)}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGO)


def make_access_token(user_id: str, token_version: int) -> str:
    return _encode({"sub": user_id, "ver": token_version, "typ": "access"}, settings.access_token_minutes)


def make_reset_token(user_id: str, token_version: int) -> str:
    return _encode({"sub": user_id, "ver": token_version, "typ": "reset"}, settings.password_reset_minutes)


def decode_token(token: str, typ: str) -> dict | None:
    try:
        data = jwt.decode(token, settings.secret_key, algorithms=[ALGO])
    except jwt.PyJWTError:
        return None
    return data if data.get("typ") == typ else None
