from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    debug: bool
    camera_index: int
    database_path: str
    log_level: str
    telegram_bot_token: str