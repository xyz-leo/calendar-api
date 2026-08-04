import secrets

import jwt as pyjwt
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.google_oauth import build_flow
from app.models import User
from app.rate_limit import limiter
from app.security import JWT_LIFETIME, create_access_token, decode_access_token, encrypt_token

router = APIRouter()

STATE_COOKIE = "oauth_state"
CODE_VERIFIER_COOKIE = "oauth_code_verifier"
# Set only when /auth/login was asked to hand the token back via a local loopback
# redirect instead of a cookie (the TUI's login flow) — see /auth/callback below.
LOOPBACK_PORT_COOKIE = "oauth_loopback_port"
# Holds the JWT itself for the same-origin web client (app/static/index.html, served at
# GET /). HttpOnly so page JS can never read it — see /auth/callback and get_current_user.
SESSION_COOKIE = "session"


@router.get("/auth/login")
@limiter.limit(settings.auth_rate_limit)
def login(
    request: Request, port: int | None = Query(default=None, ge=1024, le=65535)
) -> RedirectResponse:
    flow = build_flow()
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    response = RedirectResponse(authorization_url)
    response.set_cookie(STATE_COOKIE, state, max_age=300, httponly=True)
    # PKCE: the verifier is generated inside authorization_url() above and lives only on
    # this Flow instance. The callback request builds a separate Flow, so it must be
    # handed the same verifier explicitly, the same way `state` is passed via cookie.
    response.set_cookie(
        CODE_VERIFIER_COOKIE, flow.code_verifier, max_age=300, httponly=True
    )
    # A CLI/TUI client (no way to receive the JSON response below directly) passes its
    # own local loopback port here; /auth/callback redirects the token there instead of
    # returning it. Bounds are enforced by Query() above, not re-checked later — by the
    # time /auth/callback reads this back it's from a cookie this server set, never from
    # anything in that request itself.
    if port is not None:
        response.set_cookie(LOOPBACK_PORT_COOKIE, str(port), max_age=300, httponly=True)
    return response


@router.get("/auth/callback")
@limiter.limit(settings.auth_rate_limit)
def callback(
    request: Request, code: str, state: str, db: Session = Depends(get_db)
) -> Response:
    if not secrets.compare_digest(request.cookies.get(STATE_COOKIE, ""), state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    code_verifier = request.cookies.get(CODE_VERIFIER_COOKIE)
    if not code_verifier:
        raise HTTPException(status_code=400, detail="Missing OAuth code verifier")

    flow = build_flow(code_verifier=code_verifier)
    flow.fetch_token(code=code)
    credentials = flow.credentials

    if not credentials.has_scopes(["https://www.googleapis.com/auth/calendar.events"]):
        raise HTTPException(
            status_code=400,
            detail=(
                "Calendar access was not granted. Check that "
                "'https://www.googleapis.com/auth/calendar.events' is listed under "
                "your Google Cloud project's OAuth consent screen scopes, then try "
                "logging in again."
            ),
        )

    claims = google_id_token.verify_oauth2_token(
        credentials.id_token,
        google_requests.Request(),
        settings.google_client_id,
        # Zero tolerance by default — even a sub-second clock difference between
        # this container and Google's servers rejects an otherwise-valid token
        # with "used too early"/"expired" (seen in practice: 1 second off was
        # enough). A small margin is standard practice for exactly this.
        clock_skew_in_seconds=10,
    )
    google_id = claims["sub"]
    email = claims["email"]

    user = db.query(User).filter_by(google_id=google_id).first()
    if user is None:
        user = User(google_id=google_id, email=email, encrypted_refresh_token="")
        db.add(user)

    user.email = email
    if credentials.refresh_token:
        user.encrypted_refresh_token = encrypt_token(credentials.refresh_token)
    user.access_token = credentials.token
    user.access_token_expires_at = credentials.expiry
    db.commit()
    db.refresh(user)

    access_token = create_access_token(user.id, user.session_version)

    # Loopback handoff for a CLI/TUI client (see /auth/login): the port came from our
    # own cookie, never from this request, and the host/scheme/path below are fixed
    # string literals — no caller input ever reaches them, so this can't become an
    # open redirect. Putting the token in a 127.0.0.1-only URL's query string is the
    # standard RFC 8252 "loopback interface redirection" tradeoff (same approach
    # gcloud/gh use for native-app logins) — it never leaves the machine.
    loopback_port = request.cookies.get(LOOPBACK_PORT_COOKIE)
    if loopback_port is not None:
        response = RedirectResponse(f"http://127.0.0.1:{int(loopback_port)}/callback?token={access_token}")
    else:
        # The browser case (app/static/index.html, served at GET / — same origin as
        # this API). The JWT never touches the URL or a JS-readable store: it's set
        # as an HttpOnly cookie and the browser carries it automatically from here on.
        # SameSite=Strict is what makes that safe against CSRF (the cookie is never
        # attached to a request that didn't originate from this same site); Secure
        # keeps it off plain HTTP. No CORS is involved — this is same-origin only.
        response = RedirectResponse("/")
        response.set_cookie(
            SESSION_COOKIE,
            access_token,
            max_age=int(JWT_LIFETIME.total_seconds()),
            httponly=True,
            # Reflects the scheme the browser actually used (via Caddy's
            # X-Forwarded-Proto in prod — see the Dockerfile's --proxy-headers flag),
            # not hardcoded True: local dev serves plain http://localhost:8088, where
            # a hardcoded Secure flag would silently stop the browser from ever
            # storing the cookie at all.
            secure=request.url.scheme == "https",
            samesite="strict",
            path="/",
        )
    response.delete_cookie(STATE_COOKIE)
    response.delete_cookie(CODE_VERIFIER_COOKIE)
    response.delete_cookie(LOOPBACK_PORT_COOKIE)
    return response


def get_current_user(
    authorization: str | None = Header(None),
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    # Two independent transports for the exact same JWT: the Authorization header
    # (TUI, calctl.sh, any non-browser client) and the HttpOnly session cookie (the
    # web client, app/static/index.html — its own JS never sees the token, the
    # browser just attaches this automatically on same-origin requests). Header
    # wins if a caller somehow sent both.
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
    elif session:
        token = session
    else:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    try:
        payload = decode_access_token(token)
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    # The token was signed with the session_version that was current at login time.
    # If it no longer matches the user's current value, the session was logged out
    # since this token was issued — reject it even though the signature is genuine.
    if payload.get("sv") != user.session_version:
        raise HTTPException(status_code=401, detail="Session has been logged out")

    return user


@router.post("/auth/logout")
def logout(
    response: Response, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    current_user.session_version += 1
    current_user.encrypted_refresh_token = ""
    current_user.access_token = ""
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"detail": "Logged out. This token and any other active session are now invalid."}


@router.get("/me")
def me(current_user: User = Depends(get_current_user)) -> dict:
    return {"id": current_user.id, "email": current_user.email}
