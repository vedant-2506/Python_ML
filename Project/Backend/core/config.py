from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    env: str = "dev"
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "rankresume"
    db_user: str = "root"
    db_password: str = "root"
    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 480
    frontend_origin: str = "http://localhost:5500"
    frontend_base_url: str = "http://localhost:5500"
    exam_link_expiry_hours: int = 72
    max_upload_mb: int = 1024
    max_zip_files: int = 2000
    max_zip_uncompressed_mb: int = 4096
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False
    mail_from_address: str = "exam@rankresume.com"
    mail_from_name: str = "RankResume Exams"
    gemini_api_key: str = ""
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_prefix="",
        extra="ignore",
        case_sensitive=False,
    )

    def export_legacy_env(self) -> None:
        import os
        values = {
            "RANKRESUME_DB_HOST": self.db_host, "RANKRESUME_DB_PORT": str(self.db_port),
            "RANKRESUME_DB_NAME": self.db_name, "RANKRESUME_DB_USER": self.db_user,
            "RANKRESUME_DB_PASSWORD": self.db_password,
            "GEMINI_API_KEY": self.gemini_api_key, "GROQ_API_KEY": self.groq_api_key,
            "GROQ_MODEL": self.groq_model,
        }
        for key, value in values.items():
            os.environ.setdefault(key, value)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.export_legacy_env()
    return settings
