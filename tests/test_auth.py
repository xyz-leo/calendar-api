from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import LOOPBACK_PORT_COOKIE, get_current_user, logout
from app.config import settings
from app.main import app
from app.models import User
from app.security import create_access_token


def _make_user(db_session, **overrides) -> User:
    user = User(
        google_id=overrides.get("google_id", "google-123"),
        email=overrides.get("email", "test@example.com"),
        encrypted_refresh_token=overrides.get("encrypted_refresh_token", "fake-ciphertext"),
        access_token=overrides.get("access_token", "fake-access-token"),
        access_token_expires_at=overrides.get(
            "access_token_expires_at", datetime.now(timezone.utc).replace(tzinfo=None)
        ),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_valid_token_resolves_to_the_right_user(db_session):
    user = _make_user(db_session)
    token = create_access_token(user.id, user.session_version)

    resolved = get_current_user(authorization=f"Bearer {token}", db=db_session)

    assert resolved.id == user.id


def test_missing_authorization_header_is_401(db_session):
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=None, db=db_session)
    assert exc_info.value.status_code == 401


def test_malformed_authorization_header_is_401(db_session):
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization="not-a-bearer-token", db=db_session)
    assert exc_info.value.status_code == 401


def test_garbage_token_is_401(db_session):
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization="Bearer not.a.real.jwt", db=db_session)
    assert exc_info.value.status_code == 401


def test_token_for_nonexistent_user_is_401(db_session):
    token = create_access_token(user_id=99999, session_version=0)
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=f"Bearer {token}", db=db_session)
    assert exc_info.value.status_code == 401


def test_logout_bumps_session_version_and_invalidates_old_token(db_session):
    user = _make_user(db_session)
    old_token = create_access_token(user.id, user.session_version)

    logout(current_user=user, db=db_session)

    assert user.session_version == 1
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=f"Bearer {old_token}", db=db_session)
    assert exc_info.value.status_code == 401
    assert "logged out" in exc_info.value.detail.lower()


def test_logout_clears_google_tokens(db_session):
    user = _make_user(db_session)

    logout(current_user=user, db=db_session)

    assert user.encrypted_refresh_token == ""
    assert user.access_token == ""


def test_fresh_token_after_logout_is_valid_again(db_session):
    user = _make_user(db_session)
    logout(current_user=user, db=db_session)

    new_token = create_access_token(user.id, user.session_version)
    resolved = get_current_user(authorization=f"Bearer {new_token}", db=db_session)

    assert resolved.id == user.id


# /auth/login's `port` query param is how a CLI/TUI client asks /auth/callback to
# hand the token back via a local loopback redirect instead of raw JSON. These only
# exercise that validation/cookie-setting boundary — no real Google call happens
# here (flow.authorization_url() is pure local URL construction), so no mocking is
# needed. follow_redirects=False matters: without it, TestClient would actually try
# to follow the redirect to Google's real consent screen.
client = TestClient(app, follow_redirects=False)


def test_login_without_port_does_not_set_loopback_cookie():
    response = client.get("/auth/login")

    assert response.status_code == 307
    assert LOOPBACK_PORT_COOKIE not in response.cookies


def test_login_with_valid_port_sets_loopback_cookie():
    response = client.get("/auth/login", params={"port": 54123})

    assert response.status_code == 307
    assert response.cookies[LOOPBACK_PORT_COOKIE] == "54123"


@pytest.mark.parametrize("port", [80, 1023, 65536, 99999999])
def test_login_with_out_of_range_port_is_422(port):
    response = client.get("/auth/login", params={"port": port})

    assert response.status_code == 422


def test_login_is_rate_limited_past_the_configured_threshold():
    # AUTH_RATE_LIMIT (settings.auth_rate_limit) is the stricter override on
    # /auth/login and /auth/callback specifically — parsed from the config
    # value itself rather than hardcoding "10" so this doesn't silently stop
    # testing anything real if that default is ever tuned.
    limit_count = int(settings.auth_rate_limit.split("/")[0])
    for _ in range(limit_count):
        response = client.get("/auth/login")
        assert response.status_code == 307

    response = client.get("/auth/login")

    assert response.status_code == 429
