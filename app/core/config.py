from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "bound-fastapi"
    app_version: str = "0.1.0"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/bound"

    # AWS S3
    aws_region: str = "us-east-1"
    s3_bucket_name: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
