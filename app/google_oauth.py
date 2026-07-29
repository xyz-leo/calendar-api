import os

from google_auth_oauthlib.flow import Flow

from app.config import settings

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
