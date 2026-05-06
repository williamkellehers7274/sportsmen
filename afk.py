from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import discord

from storage import clear_afk, get_afk_map, set_afk


AFK_PANEL_IMAGE_FILENAME = "afk_panel.png"


def _afk_image_file() -> discord.File | None:
    p = Path(__file__).resolve().parent / "foto" / AFK_PANEL_IMAGE_FILENAME
    if p.exists() and p.is_file():
        return discord.File(str(p), filename=AFK_PANEL_IMAGE_FILENAME)
    return None


def build_afk_panel_embed(*, with_image: bool = False) -> discord.Embed:
    embed = discord.Embed(
        title="AFK панель",
        description=(
            "Уход в AFK до 24 часов.\n"
            "Выбери действие в выпадающем списке:\n"
            "- `Уйти в AFK` — укажи время и причину\n"
            "- `Выйти из AFK` — снять статус\n"
            "- `Список AFK` — посмотреть, кто сейчас AFK и до какого времени"
        ),
        color=discord.Color.dark_gray(),
    )
    if with_image:
        embed.set_image(url=f"attachment://{AFK_PANEL_IMAGE_FILENAME}")
    embed.set_footer(text="Спортсмены • AFK")
    return embed


def parse_afk_duration(raw: str) -> int | None:
    text = raw.strip().lower().replace(" ", "")
    # Примеры: 30м, 1ч, 1ч30м, 45m, 2h10m
    m = re.fullmatch(r"(?:(\d{1,2})ч|(\d{1,2})h)?(?:(\d{1,2})м|(\d{1,2})m)?", text)
    if not m:
        return None

    hours = int(m.group(1) or m.group(2) or 0)
    minutes = int(m.group(3) or m.group(4) or 0)
    total_minutes = hours * 60 + minutes
    if total_minutes <= 0 or total_minutes > 24 * 60:
        return None
    return total_minutes


def _fmt_until_local(until_ts: int) -> str:
    return dt.datetime.fromtimestamp(until_ts).strftime("%d.%m.%Y %H:%M")


def _plural_ru(n: int, one: str, two: str, many: str) -> str:
    n10 = n % 10
    n100 = n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return two
    return many


def _left_text(until_ts: int) -> str:
    now_ts = int(dt.datetime.now().timestamp())
    sec = max(0, until_ts - now_ts)
    mins = sec // 60
    hours = mins // 60
    rem_mins = mins % 60
    if hours == 0:
        return f"через {mins} {_plural_ru(mins, 'минуту', 'минуты', 'минут')}"
    if rem_mins == 0:
        return f"через {hours} {_plural_ru(hours, 'час', 'часа', 'часов')}"
    return (
        f"через {hours} {_plural_ru(hours, 'час', 'часа', 'часов')} "
        f"{rem_mins} {_plural_ru(rem_mins, 'минуту', 'минуты', 'минут')}"
    )


def _fmt_duration(minutes: int) -> str:
    hours = minutes // 60
    rem_mins = minutes % 60
    if hours == 0:
        return f"{rem_mins} {_plural_ru(rem_mins, 'минута', 'минуты', 'минут')}"
    if rem_mins == 0:
        return f"{hours} {_plural_ru(hours, 'час', 'часа', 'часов')}"
    return (
        f"{hours} {_plural_ru(hours, 'час', 'часа', 'часов')} "
        f"{rem_mins} {_plural_ru(rem_mins, 'минута', 'минуты', 'минут')}"
    )


def _active_afk(guild: discord.Guild) -> list[tuple[discord.Member | None, int, str]]:
    now_ts = int(dt.datetime.now().timestamp())
    rows: list[tuple[discord.Member | None, int, str]] = []
    afk_map = get_afk_map(guild_id=guild.id)
    for user_id, payload in afk_map.items():
        until_ts = payload.get("until_ts")
        reason = payload.get("reason")
        if not isinstance(until_ts, int) or not isinstance(reason, str):
            clear_afk(guild_id=guild.id, user_id=user_id)
            continue
        if until_ts <= now_ts:
            clear_afk(guild_id=guild.id, user_id=user_id)
            continue
        rows.append((guild.get_member(user_id), until_ts, reason))

    rows.sort(key=lambda x: x[1])
    return rows


def build_afk_expired_dm_embed() -> discord.Embed:
    e = discord.Embed(
        title="AFK завершён",
        description="Ваш AFK истёк.",
        color=discord.Color.dark_gray(),
    )
    e.set_footer(text=dt.datetime.now().strftime("%H:%M"))
    return e


async def process_expired_afk_for_guild(guild: discord.Guild) -> None:
    now_ts = int(dt.datetime.now().timestamp())
    afk_map = get_afk_map(guild_id=guild.id)

    for user_id, payload in afk_map.items():
        until_ts = payload.get("until_ts")
        if not isinstance(until_ts, int):
            clear_afk(guild_id=guild.id, user_id=user_id)
            continue
        if until_ts > now_ts:
            continue

        clear_afk(guild_id=guild.id, user_id=user_id)
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.NotFound:
                member = None
            except discord.HTTPException:
                member = None
        if member is not None:
            try:
                await member.send(embed=build_afk_expired_dm_embed())
            except discord.Forbidden:
                pass
            except discord.HTTPException:
                pass


class AFKLeaveModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Уйти в AFK")
        self.afk_for = discord.ui.TextInput(
            label="На сколько",
            placeholder="Пример: 30м, 1ч, 1ч30м",
            required=True,
            max_length=20,
        )
        self.reason = discord.ui.TextInput(
            label="Причина",
            placeholder="Кратко: дела, работа, учеба...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=400,
        )
        self.add_item(self.afk_for)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        minutes = parse_afk_duration(self.afk_for.value)
        if minutes is None:
            await interaction.response.send_message(
                "Неверный формат времени. Используй: `30м`, `1ч`, `1ч30м` (до 24 часов).",
                ephemeral=True,
            )
            return

        until_dt = dt.datetime.now() + dt.timedelta(minutes=minutes)
        until_ts = int(until_dt.timestamp())
        set_afk(guild_id=interaction.guild.id, user_id=interaction.user.id, until_ts=until_ts, reason=self.reason.value.strip())

        e = discord.Embed(
            title="AFK установлен",
            description=(
                f"**Имя:** {interaction.user.mention}\n"
                f"**Насколько:** {_fmt_duration(minutes)}\n"
                f"**Причина:** {self.reason.value.strip()}\n"
                f"**До:** {_fmt_until_local(until_ts)} ({_left_text(until_ts)})"
            ),
            color=discord.Color.dark_gray(),
        )
        e.set_footer(text="AFK статус активен")
        await interaction.response.send_message(embed=e, ephemeral=True)


class AFKActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Выберите действие",
            min_values=1,
            max_values=1,
            custom_id="afk_actions_select",
            options=[
                discord.SelectOption(label="Уйти в AFK", description="Указать время и причину", value="leave"),
                discord.SelectOption(label="Выйти из AFK", description="Завершить AFK досрочно", value="exit"),
                discord.SelectOption(label="Список AFK", description="Кто сейчас в AFK", value="list"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        action = self.values[0]
        if action == "leave":
            await interaction.response.send_modal(AFKLeaveModal())
        elif action == "exit":
            clear_afk(guild_id=interaction.guild.id, user_id=interaction.user.id)
            e = discord.Embed(
                title="AFK снят",
                description="Вы вышли из AFK.",
                color=discord.Color.dark_gray(),
            )
            e.set_footer(text="Статус обновлен")
            await interaction.response.send_message(embed=e, ephemeral=True)
        else:
            rows = _active_afk(interaction.guild)
            if not rows:
                e = discord.Embed(
                    title="Список AFK",
                    description="Сейчас никто не в AFK.",
                    color=discord.Color.dark_gray(),
                )
                await interaction.response.send_message(embed=e, ephemeral=True)
                return

            lines: list[str] = []
            for member, until_ts, reason in rows:
                who = member.mention if member is not None else "Пользователь"
                lines.append(
                    f"{who} — до **{_fmt_until_local(until_ts)}** ({_left_text(until_ts)})\n"
                    f"Причина: {reason}"
                )

            e = discord.Embed(
                title="Список AFK",
                description="\n\n".join(lines),
                color=discord.Color.dark_gray(),
            )
            e.set_footer(text=f"Всего в AFK: {len(rows)}")
            await interaction.response.send_message(embed=e, ephemeral=True)

        if interaction.message is not None:
            try:
                await interaction.message.edit(view=AFKPanelView())
            except (discord.Forbidden, discord.HTTPException):
                pass


class AFKPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(AFKActionSelect())

