from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "bound-fastapi"
    app_version: str = "0.1.0"
    debug: bool = False

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
