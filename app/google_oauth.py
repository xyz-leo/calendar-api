import os
from datetime import datetime, timezone

from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from google.auth.exceptions import RefreshError
from google.auth.transport import requests as google_requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User
from app.security import decrypt_token

GOOGLE_ACCESS_LOST_DETAIL = "Google access expired or was revoked — log in with Google again."

# oauthlib raises a hard exception whenever the granted scope string differs at all
# from what was requested — including harmless reordering/reformatting, which Google
# does routinely. This disables that crash; whether a scope we actually need is
# missing is checked explicitly in auth.py instead, where we can respond with a
# clear error rather than a stack trace.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/calendar.events",
]


def build_flow(code_verifier: str | None = None) -> Flow:
    return Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.google_redirect_uri],
            }
        },
        scopes=SCOPES,
        redirect_uri=settings.google_redirect_uri,
        code_verifier=code_verifier,
    )


def _is_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return True
    # access_token_expires_at is stored as a naive UTC datetime (that's what
    # google-auth's credentials.expiry gives us), so "now" has to be naive UTC
    # too — comparing naive to timezone-aware datetimes raises a TypeError.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return expires_at <= now


def get_user_credentials(user: User, db: Session) -> Credentials:
    """Build a valid, per-user Google API client credential, refreshing it first if needed.

    CalendarService never sees how this credential was obtained or kept alive —
    it only ever receives one that already works.
    """
    try:
        refresh_token = decrypt_token(user.encrypted_refresh_token)
    except InvalidToken:
        # Raised on an empty/blank string too, not just a corrupt one — this is
        # exactly the state logout leaves a user in (encrypted_refresh_token is
        # wiped to ""), so this is the expected, everyday way to reach this path.
        raise HTTPException(status_code=401, detail=GOOGLE_ACCESS_LOST_DETAIL)

    credentials = Credentials(
        token=user.access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=SCOPES,
    )

    if _is_expired(user.access_token_expires_at):
        try:
            credentials.refresh(google_requests.Request())
        except RefreshError:
            # The refresh_token itself is no longer honored by Google — e.g. the
            # 7-day expiry in Testing mode, or the user revoked access directly
            # at myaccount.google.com/permissions.
            raise HTTPException(status_code=401, detail=GOOGLE_ACCESS_LOST_DETAIL)
        user.access_token = credentials.token
        user.access_token_expires_at = credentials.expiry
        db.commit()

    return credentials
