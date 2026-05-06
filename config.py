from __future__ import annotations

import os

from dotenv import load_dotenv


load_dotenv()


def _get_env_int(name: str, *, required: bool) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        if required:
            raise RuntimeError(f"Missing required env var: {name}")
        return None
    try:
        return int(raw.strip())
    except ValueError as e:
        if not required:
            print(f"[config] warning: env var {name} must be an integer (ignored): {raw!r}")
            return None
        raise RuntimeError(f"Env var {name} must be int, got: {raw!r}") from e


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
if not DISCORD_TOKEN:
    raise RuntimeError("Missing required env var: DISCORD_TOKEN")

APPLICATION_CHANNEL_ID = _get_env_int("APPLICATION_CHANNEL_ID", required=False)
PANEL_CHANNEL_ID = _get_env_int("PANEL_CHANNEL_ID", required=False)
GUILD_ID = _get_env_int("GUILD_ID", required=False)
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "").strip()
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "").strip()

# Telegram MTProto (личный аккаунт / userbot через Telethon) — видит сообщения от других ботов в чате.
TELEGRAM_API_ID = _get_env_int("TELEGRAM_API_ID", required=False)
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()
TELEGRAM_SESSION_NAME = os.getenv("TELEGRAM_SESSION_NAME", "tg_rp_session").strip() or "tg_rp_session"

# Номер можно не указывать — тогда при первой авторизации бот попросит ввести номер прямо в консоли.
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "").strip()

# Опционально: numeric chat id источника. Если не задан — фильтруй строкой TG_CHAT_TITLE_SUBSTRING или не фильтруй вовсе.
TG_SOURCE_CHAT_ID = _get_env_int("TG_SOURCE_CHAT_ID", required=False)

# Если не знаешь точный TG chat id: подстрочное совпадение по названию чата / @username или по тексту сообщения (Milton и т.д.).
TG_CHAT_TITLE_SUBSTRING = os.getenv("TG_CHAT_TITLE_SUBSTRING", "").strip()

# Куда постить итоговое embed в Discord
TG_RP_DISCORD_CHANNEL_ID = _get_env_int("TG_RP_DISCORD_CHANNEL_ID", required=False)

# Обратная совместимость (старое имя переменной)
TG_WAR_DISCORD_CHANNEL_ID = _get_env_int("TG_WAR_DISCORD_CHANNEL_ID", required=False)

# Ожидание второго сообщения с итогом после «забили войну…», секунды (терра может идти 30+ мин; по умолчанию час)
TG_RP_PAIR_OUTCOME_SECONDS = _get_env_int("TG_RP_PAIR_OUTCOME_SECONDS", required=False)

# Подстроки через «|»: сообщение считается «забита война» только если есть хоть одно совпадение (регистр не важен).
# Если пусто — опора только на общий шаблон regex (без перечисления 100 названий территорий).
TG_RP_STRIKE_TRIGGERS = os.getenv("TG_RP_STRIKE_TRIGGERS", "").strip()

# Стереть по названию «куда»: первое сообщение и «Проигрывает за …» связываются без сравнения локаций (очередью в этом чате).
# Если 1/true/on — включается сопоставление по строке между «за» и «во втором сообщении».
TG_RP_PAIR_MATCH_LOCATION = os.getenv("TG_RP_PAIR_MATCH_LOCATION", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

