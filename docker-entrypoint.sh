#!/bin/sh
set -e

SECRETS_FILE=/app/data/.secrets.env

if [ ! -f "$SECRETS_FILE" ]; then
    {
        echo "JWT_SECRET=$(uv run python -c 'import secrets; print(secrets.token_hex(32))')"
        echo "TOKEN_ENCRYPTION_KEY=$(uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
    } > "$SECRETS_FILE"
fi

set -a
. "$SECRETS_FILE"
set +a

exec "$@"
