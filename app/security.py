from datetime import datetime, timedelta, timezone

import jwt
from cryptography.fernet import Fernet

from app.config import settings

JWT_ALGORITHM = "HS256"
JWT_LIFETIME = timedelta(hours=24)

_fernet = Fernet(settings.token_encryption_key.encode())


def create_access_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + JWT_LIFETIME,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])


def encrypt_token(plain_text: str) -> str:
    return _fernet.encrypt(plain_text.encode()).decode()


def decrypt_token(cipher_text: str) -> str:
    return _fernet.decrypt(cipher_text.encode()).decode()
