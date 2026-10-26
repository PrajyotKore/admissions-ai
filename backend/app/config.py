from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./dev.db"
    secret_key: str = "dev-only-change-me"
    access_token_minutes: int = 60 * 8
    password_reset_minutes: int = 30
    environment: str = "development"  # development | production
    cors_origins: str = "http://localhost:3000"
    # Voice provider: "mock" unless real credentials + compliance are configured
    voice_provider: str = "mock"
    webhook_secret: str = "dev-webhook-secret"
    webhook_max_age_seconds: int = 300


settings = Settings()
