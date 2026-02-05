from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "bound-fastapi"
    app_version: str = "0.1.0"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/bound"

    # JWT Auth
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    email_verification_token_expire_hours: int = 24

    # CORS
    frontend_url: str = "http://localhost:3000"

    # Cookies
    cookie_domain: str | None = None
    cookie_secure: bool = False

    # Email (Resend)
    resend_api_key: str = ""
    resend_from_email: str = ""
    resend_from_name: str = "bound"

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""
    google_oauth_scopes: str = "openid email profile"

    # AWS S3
    aws_region: str = "us-east-1"
    s3_bucket_name: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_session_token: str = ""

    # TTS Configuration
    max_audio_duration_seconds: int = 3600
    max_audio_file_size_mb: int = 500

    model_config = {"env_file": ".env.local", "extra": "ignore"}


settings = Settings()
