from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    club_chat_id: int | None
    database_path: str
    timezone: str
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise ValueError("BOT_TOKEN is required. Copy .env.example to .env and set it.")
        admins = frozenset(int(value.strip()) for value in os.getenv("ADMIN_IDS", "").split(",") if value.strip())
        chat_value = os.getenv("CLUB_CHAT_ID", "").strip()
        return cls(token, admins, int(chat_value) if chat_value else None,
                   os.getenv("DATABASE_PATH", "data/typhoon.db"),
                   os.getenv("TIMEZONE", "Europe/Kyiv"), os.getenv("LOG_LEVEL", "INFO").upper())
