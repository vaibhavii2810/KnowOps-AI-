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
    vercel: str = ""  # Vercel sets this to "1" on every Preview/Production deployment; empty locally (D-055)
    n8n_escalation_webhook_url: str = ""
    rate_limit_ask_per_minute: int = 10
    rate_limit_agent_per_minute: int = 5
    rate_limit_login_per_minute: int = 5
    rate_limit_login_per_hour: int = 30
    log_level: str = "INFO"  # Phase 12.1: DEBUG, INFO, WARNING or ERROR (D-042)
    metrics_enabled: bool = True  # Phase 12.4: count every API request for GET /metrics (D-046)
    gemini_timeout_seconds: float = 25.0  # per Gemini request; also each call's retry budget (D-045)

    class Config:
        env_file = ".env"

settings = Settings()


class InsecureDefaultSecret(RuntimeError):
    """Raised by ensure_secrets_are_configured() when deployed with a default secret still in place."""


def ensure_secrets_are_configured(s: "Settings" = None) -> None:
    """
    Refuse to run when deployed (`s.vercel` set — Vercel sets this automatically on every Preview/Production
    build, D-055) with `JWT_SECRET` or `APP_PASSWORD` still at their insecure defaults (D-007; bug #9 in the
    external report, D-063). D-007 named exactly this as its own revisit condition: "production should refuse
    to start without real secrets." Off Vercel this is a no-op — the defaults exist specifically so a
    contributor needs no `.env` to run the app locally, and that stays true.
    """
    s = s or settings
    if not s.vercel:
        return
    insecure = [name for name, value, default in (
        ("JWT_SECRET", s.jwt_secret, "dev-secret"),
        ("APP_PASSWORD", s.app_password, "admin"),
    ) if value == default]
    if insecure:
        raise InsecureDefaultSecret(
            f"Refusing to start: insecure default value still in place for: {', '.join(insecure)}. "
            "Set a real value for every Vercel environment (Preview and Production) before deploying."
        )
