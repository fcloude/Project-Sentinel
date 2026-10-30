import os

from dotenv import load_dotenv

from src.config.settings import Settings

load_dotenv()


def _flag(name: str, default: str = "False") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def load_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Project Sentinel"),
        app_version=os.getenv("APP_VERSION", "0.0.1"),
        debug=_flag("DEBUG"),
        camera_index=int(os.getenv("CAMERA_INDEX", "0")),
        database_path=os.getenv("DATABASE_PATH", "data/database/sentinel.db"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        cookie_secure=_flag("COOKIE_SECURE"),
        allow_file_sources=_flag("ALLOW_FILE_SOURCES"),
    )
