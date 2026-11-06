from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = ""
    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-flash-lite-latest"
    gemini_embed_model: str = "gemini-embedding-001"
    embed_dim: int = 768
    jwt_secret: str = "dev-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    app_username: str = "admin"
    app_password: str = "admin"
    cron_secret: str = ""
    n8n_escalation_webhook_url: str = ""
    rate_limit_ask_per_minute: int = 10
    rate_limit_agent_per_minute: int = 5
    rate_limit_login_per_minute: int = 5
    rate_limit_login_per_hour: int = 30
    log_level: str = "INFO"  # Phase 12.1: DEBUG, INFO, WARNING or ERROR (D-042)
    gemini_timeout_seconds: float = 25.0  # per Gemini request; also each call's retry budget (D-045)

    class Config:
        env_file = ".env"

settings = Settings()
