from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    database_url: str
    jwt_secret: str
    token_encryption_key: str


settings = Settings()
