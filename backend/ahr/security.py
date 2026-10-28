import hashlib
import hmac
import secrets
import time
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from .db import AuthSession, User, get_db


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000)
    return f"pbkdf2:600000:{salt}:{digest.hex()}"


def verify_password(password, encoded):
    _, rounds, salt, expected = encoded.split(":")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
    return hmac.compare_digest(digest.hex(), expected)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(request: Request, db: Session = Depends(get_db)):
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else request.cookies.get("ahr_session", "")
    session = db.get(AuthSession, token_hash(token)) if token else None
    if session is None or session.expires_at <= time.time():
        raise HTTPException(401, "请先登录，或登录已过期")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "账号不可用")
    return user


def require_role(user, *roles):
    if user.role not in roles:
        raise HTTPException(403, "当前身份无权执行此操作")


def public_user(user):
    return {key: getattr(user, key) for key in ("id", "username", "name", "role", "org")}

