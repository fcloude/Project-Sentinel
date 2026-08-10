import os
from dotenv import load_dotenv
from src.config.settings import Settings

load_dotenv()


def load_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Project Sentinel"),
        app_version=os.getenv("APP_VERSION", "0.0.1"),
        debug=os.getenv("DEBUG", "False") == "True",
        camera_index=int(os.getenv("CAMERA_INDEX", "0")),
        database_path=os.getenv("DATABASE_PATH", "data/database/sentinel.db"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
    )