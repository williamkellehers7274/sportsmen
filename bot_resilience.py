from __future__ import annotations

import logging
import discord
from discord import app_commands

log = logging.getLogger("sportiki-bot")


def _user_error_text() -> str:
    return "Произошла ошибка. Бот продолжает работу — попробуй ещё раз или обратись к администратору."


async def _safe_reply(interaction: discord.Interaction, text: str) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except (discord.NotFound, discord.HTTPException):
        pass


def install_bot_handlers(bot: discord.Client) -> None:
    @bot.event
    async def on_error(event_method: str, /, *args, **kwargs) -> None:
        log.exception("Необработанная ошибка в событии %s", event_method)

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        log.exception("Ошибка slash-команды: %s", getattr(interaction.command, "name", "?"))
        await _safe_reply(interaction, _user_error_text())

def run_bot_with_restart(bot: discord.Client, token: str, *, max_backoff_s: float = 120.0) -> None:
    """Запуск с автопереподключением при падении процесса run (не при Ctrl+C)."""
    delay = 5.0
    while True:
        try:
            bot.run(token)
            break
        except KeyboardInterrupt:
            log.info("Остановка по KeyboardInterrupt")
            break
        except SystemExit:
            raise
        except Exception:
            log.exception("Бот упал, перезапуск через %.0f с", delay)
            import time

            time.sleep(delay)
            delay = min(delay * 2, max_backoff_s)
