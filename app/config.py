from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = ""
    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_embed_model: str = "gemini-embedding-001"
    embed_dim: int = 768
    jwt_secret: str = "dev-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    app_username: str = "admin"
    app_password: str = "admin"
    cron_secret: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
