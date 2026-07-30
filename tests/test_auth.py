from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.auth import get_current_user, logout
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
