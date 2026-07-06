from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


ENV_PATH = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ENV_PATH), extra="ignore")

    divergence_model: str = "orca-mini:latest"
    github_token: str
    target_repo: str
    local_repo_path: str
    webhook_secret: str = "dev-secret"
    autofix_threshold: float = 0.85
    alert_threshold: float = 0.50


settings = Settings()