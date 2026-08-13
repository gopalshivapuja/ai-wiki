"""Authentication.

One admin, provisioned from the environment. There is deliberately no signup, no roles, and
no in-app password change — `_ensure_admin` re-syncs from ADMIN_PASSWORD on every boot, so
the environment is the credential store.

The wiki is private: every route requires a token. Reads were once public, but literature
notes reproduce the substance of the sources they summarise, so a public/private split by
document class protected nothing.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from wiki_api.auth_utils import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    decode_token,
    verify_password,
)
from wiki_api.database import ADMIN, User, get_db

router = APIRouter()
security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    email: str
    role: str = ADMIN
    # Spelled out so the frontend never has to know the role vocabulary to decide what to show.
    can_edit: bool = True


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    token = create_access_token(
        {"sub": user.email, "role": user.role or ADMIN},
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return TokenResponse(access_token=token)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if not creds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(creds.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    user = db.query(User).filter(User.email == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Refuse writes to a reader.

    Enforced on the server, not by hiding buttons: the demo account's password is public by
    design, so the API has to be the thing that says no.
    """
    if (user.role or ADMIN) != ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This is a read-only demo account. You can browse, search and ask questions, "
                "but nothing you add here is saved."
            ),
        )
    return user


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    role = user.role or ADMIN
    return UserResponse(email=user.email, role=role, can_edit=role == ADMIN)
