import time
from collections import defaultdict, deque
from datetime import timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import config
from .db import User, get_session, now


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def issue_token(user: User) -> str:
    payload = {'sub': str(user.id), 'tv': user.token_version, 'exp': now() + timedelta(hours=config.TOKEN_TTL_HOURS)}
    return jwt.encode(payload, config.SECRET_KEY, algorithm='HS256')


def current_user(request: Request, db: Session = Depends(get_session)) -> User:
    header = request.headers.get('authorization', '')
    if not header.lower().startswith('bearer '):
        raise HTTPException(401, 'Not logged in')
    try:
        payload = jwt.decode(header[7:], config.SECRET_KEY, algorithms=['HS256'])
    except jwt.PyJWTError:
        raise HTTPException(401, 'Session expired, please log in again')
    user = db.get(User, int(payload['sub']))
    # token_version changes on password reset, which logs out existing sessions.
    if not user or not user.active or user.token_version != payload.get('tv'):
        raise HTTPException(401, 'Session expired, please log in again')
    return user


def writer_user(user: User = Depends(current_user)) -> User:
    if user.role != 'writer':
        raise HTTPException(403, 'Writers only')
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != 'admin':
        raise HTTPException(403, 'Admins only')
    return user


class LoginLimiter:
    """At most `limit` failed logins per client in `window` seconds (per process)."""

    def __init__(self, limit=10, window=900):
        self.limit, self.window = limit, window
        self.failures = defaultdict(deque)

    def check(self, key):
        q = self.failures[key]
        while q and q[0] < time.time() - self.window:
            q.popleft()
        if len(q) >= self.limit:
            raise HTTPException(429, 'Too many failed attempts. Try again in 15 minutes.')

    def fail(self, key):
        self.failures[key].append(time.time())


login_limiter = LoginLimiter()


def ensure_admin(db: Session):
    """Create or update the superadmin from ADMIN_USERNAME / ADMIN_PASSWORD."""
    username = config.ADMIN_USERNAME.strip().lower()  # logins are matched in lower case
    admin = db.query(User).filter_by(username=username).one_or_none()
    if admin is None:
        db.add(User(username=username, password_hash=hash_password(config.ADMIN_PASSWORD),
                    role='admin', display_name='Admin'))
    elif admin.role != 'admin' or not verify_password(config.ADMIN_PASSWORD, admin.password_hash):
        admin.role, admin.active = 'admin', True
        admin.password_hash = hash_password(config.ADMIN_PASSWORD)
        admin.token_version += 1
    db.commit()
