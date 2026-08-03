from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    database_url: str
    jwt_secret: str
    token_encryption_key: str
    # "<count>/<period>" strings the `limits` library parses, e.g. "60/minute".
    # Defaulted (not required) so an existing .env with no opinion on this still
    # works unchanged — see docs/api-reference.md for the full syntax.
    rate_limit: str = "60/minute"
    auth_rate_limit: str = "10/minute"


settings = Settings()
