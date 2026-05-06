from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import discord

from storage import (
    clear_vacation,
    get_vacation_channel_id,
    get_vacation_map,
    get_vacation_role_id,
    set_vacation,
)


VACATION_PANEL_IMAGE_FILENAME = "vacation_panel.png"


def _vacation_image_file() -> discord.File | None:
    p = Path(__file__).resolve().parent / "foto" / VACATION_PANEL_IMAGE_FILENAME
    if p.exists() and p.is_file():
        return discord.File(str(p), filename=VACATION_PANEL_IMAGE_FILENAME)
    return None


def _black_embed(title: str, description: str, *, footer: str | None = None) -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=discord.Color.dark_gray())
    if footer:
        e.set_footer(text=footer)
    return e


def build_vacation_panel_embed(*, with_image: bool = False) -> discord.Embed:
    e = _black_embed(
        "Система отпусков",
        (
            "Устали от игры или есть другие причины взять паузу? Просто заполните анкету.\n\n"
            "- `Взять отпуск` — указать длительность и причину\n"
            "- `Отменить отпуск` — вернуться из отпуска\n"
            "- `Список отпусков` — кто сейчас в отпуске"
        ),
    )
    if with_image:
        e.set_image(url=f"attachment://{VACATION_PANEL_IMAGE_FILENAME}")
    e.set_footer(text="Спортсмены • Отпуск")
    return e


def _plural_ru(n: int, one: str, two: str, many: str) -> str:
    n10 = n % 10
    n100 = n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return two
    return many


def parse_vacation_duration(raw: str) -> tuple[int, str] | None:
    text = raw.strip().lower().replace(" ", "")
    # Примеры: 2д, 7дней, 1д12ч, 12ч, 30м
    m = re.fullmatch(r"(?:(\d{1,2})(?:д|d|day|days))?(?:(\d{1,2})(?:ч|h|hour|hours))?(?:(\d{1,2})(?:м|m|min))?", text)
    if not m:
        return None
    days = int(m.group(1) or 0)
    hours = int(m.group(2) or 0)
    mins = int(m.group(3) or 0)
    total_minutes = days * 24 * 60 + hours * 60 + mins
    if total_minutes <= 0 or total_minutes > 30 * 24 * 60:
        return None

    parts: list[str] = []
    if days:
        parts.append(f"{days} {_plural_ru(days, 'день', 'дня', 'дней')}")
    if hours:
        parts.append(f"{hours} {_plural_ru(hours, 'час', 'часа', 'часов')}")
    if mins:
        parts.append(f"{mins} {_plural_ru(mins, 'минута', 'минуты', 'минут')}")
    return total_minutes, " ".join(parts)


def _fmt_until_local(until_ts: int) -> str:
    return dt.datetime.fromtimestamp(until_ts).strftime("%d.%m.%Y %H:%M")


def _left_text(until_ts: int) -> str:
    now_ts = int(dt.datetime.now().timestamp())
    mins = max(0, until_ts - now_ts) // 60
    days = mins // (24 * 60)
    mins %= 24 * 60
    hours = mins // 60
    mins %= 60
    parts: list[str] = []
    if days:
        parts.append(f"{days} {_plural_ru(days, 'день', 'дня', 'дней')}")
    if hours:
        parts.append(f"{hours} {_plural_ru(hours, 'час', 'часа', 'часов')}")
    if mins and not days:
        parts.append(f"{mins} {_plural_ru(mins, 'минута', 'минуты', 'минут')}")
    return "через " + (" ".join(parts) if parts else "0 минут")


def _active_vacations(guild: discord.Guild) -> list[tuple[int, discord.Member | None, int, str]]:
    now_ts = int(dt.datetime.now().timestamp())
    rows: list[tuple[int, discord.Member | None, int, str]] = []
    vacation_map = get_vacation_map(guild_id=guild.id)
    for user_id, payload in vacation_map.items():
        until_ts = payload.get("until_ts")
        reason = payload.get("reason")
        if not isinstance(until_ts, int) or not isinstance(reason, str):
            clear_vacation(guild_id=guild.id, user_id=user_id)
            continue
        if until_ts <= now_ts:
            clear_vacation(guild_id=guild.id, user_id=user_id)
            continue
        rows.append((user_id, guild.get_member(user_id), until_ts, reason))
    rows.sort(key=lambda x: x[2])
    return rows


async def _apply_vacation_roles(guild: discord.Guild, member: discord.Member) -> tuple[list[int], str]:
    bot_member = guild.me
    if bot_member is None or not bot_member.guild_permissions.manage_roles:
        return [], "боту не хватает права Manage Roles"

    removed_role_ids: list[int] = []
    vacation_role_id = get_vacation_role_id(guild_id=guild.id)
    for role in member.roles:
        # @everyone снять нельзя; роль отпуска не трогаем
        if role.is_default() or (vacation_role_id and role.id == vacation_role_id):
            continue
        if role.managed:
            continue
        # Можно снять только роли ниже роли бота
        if role < bot_member.top_role:
            try:
                await member.remove_roles(role, reason="Пользователь ушел в отпуск")
                removed_role_ids.append(role.id)
            except (discord.Forbidden, discord.HTTPException):
                continue

    vacation_role_result = "роль отпуска не настроена"
    if vacation_role_id:
        vrole = guild.get_role(vacation_role_id)
        if vrole is None:
            vacation_role_result = "роль отпуска не найдена"
        elif vrole >= bot_member.top_role:
            vacation_role_result = "роль отпуска выше/равна роли бота"
        elif vrole not in member.roles:
            try:
                await member.add_roles(vrole, reason="Пользователь ушел в отпуск")
                vacation_role_result = f"выдана роль {vrole.mention}"
            except (discord.Forbidden, discord.HTTPException):
                vacation_role_result = "не удалось выдать роль отпуска"
        else:
            vacation_role_result = "роль отпуска уже выдана"

    return removed_role_ids, vacation_role_result


async def _restore_vacation_roles(guild: discord.Guild, member: discord.Member, removed_role_ids: list[int]) -> None:
    bot_member = guild.me
    if bot_member is None or not bot_member.guild_permissions.manage_roles:
        return

    vacation_role_id = get_vacation_role_id(guild_id=guild.id)
    if vacation_role_id:
        vrole = guild.get_role(vacation_role_id)
        if vrole is not None and vrole in member.roles and vrole < bot_member.top_role:
            try:
                await member.remove_roles(vrole, reason="Пользователь вышел из отпуска")
            except (discord.Forbidden, discord.HTTPException):
                pass

    to_restore: list[discord.Role] = []
    for rid in removed_role_ids:
        role = guild.get_role(rid)
        if role is None:
            continue
        if role.managed:
            continue
        if role not in member.roles and role < bot_member.top_role:
            to_restore.append(role)
    for role in to_restore:
        try:
            await member.add_roles(role, reason="Возврат ролей после отпуска")
        except (discord.Forbidden, discord.HTTPException):
            continue


def build_vacation_expired_dm_embed() -> discord.Embed:
    return _black_embed("Отпуск завершён", "Ваш отпуск истёк.")


async def process_expired_vacation_for_guild(guild: discord.Guild) -> None:
    now_ts = int(dt.datetime.now().timestamp())
    vacation_map = get_vacation_map(guild_id=guild.id)
    for user_id, payload in vacation_map.items():
        until_ts = payload.get("until_ts")
        removed_role_ids_raw = payload.get("removed_role_ids", [])
        if not isinstance(until_ts, int):
            clear_vacation(guild_id=guild.id, user_id=user_id)
            continue
        if until_ts > now_ts:
            continue
        clear_vacation(guild_id=guild.id, user_id=user_id)
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.HTTPException):
                member = None
        if member is not None:
            removed_role_ids: list[int] = []
            if isinstance(removed_role_ids_raw, list):
                for x in removed_role_ids_raw:
                    try:
                        removed_role_ids.append(int(x))
                    except (TypeError, ValueError):
                        continue
            await _restore_vacation_roles(guild, member, removed_role_ids)
            try:
                await member.send(embed=build_vacation_expired_dm_embed())
            except (discord.Forbidden, discord.HTTPException):
                pass


class VacationTakeModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Взять отпуск")
        self.duration = discord.ui.TextInput(
            label="На сколько",
            placeholder="Пример: 2д, 7д, 1д12ч",
            required=True,
            max_length=20,
        )
        self.reason = discord.ui.TextInput(
            label="Причина",
            placeholder="Например: учеба, работа, отпуск",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=400,
        )
        self.add_item(self.duration)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(embed=_black_embed("Отпуск", "Команда доступна только на сервере."), ephemeral=True)
            return
        parsed = parse_vacation_duration(self.duration.value)
        if parsed is None:
            await interaction.response.send_message(
                embed=_black_embed("Неверный формат", "Используй: `2д`, `7д`, `1д12ч`, `12ч` (до 30 дней)."),
                ephemeral=True,
            )
            return
        total_minutes, duration_text = parsed
        until_dt = dt.datetime.now() + dt.timedelta(minutes=total_minutes)
        until_ts = int(until_dt.timestamp())
        reason = self.reason.value.strip()
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        removed_role_ids: list[int] = []
        role_result = "роль не изменялась"
        if member is not None:
            removed_role_ids, role_result = await _apply_vacation_roles(interaction.guild, member)

        set_vacation(
            guild_id=interaction.guild.id,
            user_id=interaction.user.id,
            until_ts=until_ts,
            reason=reason,
            duration_text=duration_text,
            removed_role_ids=removed_role_ids,
        )

        destination_id = get_vacation_channel_id(guild_id=interaction.guild.id)
        if destination_id:
            channel = interaction.client.get_channel(destination_id)
            if channel is None:
                try:
                    channel = await interaction.client.fetch_channel(destination_id)
                except (discord.NotFound, discord.HTTPException):
                    channel = None
            if isinstance(channel, (discord.TextChannel, discord.Thread)):
                log_embed = _black_embed(
                    "Новый отпуск",
                    (
                        f"**Имя:** {interaction.user.mention}\n"
                        f"**Насколько:** {duration_text}\n"
                        f"**Причина:** {reason}\n"
                        f"**До:** {_fmt_until_local(until_ts)} ({_left_text(until_ts)})\n"
                        f"**Роли:** {role_result}"
                    ),
                )
                try:
                    await channel.send(embed=log_embed)
                except (discord.Forbidden, discord.HTTPException):
                    pass

        e = _black_embed(
            "— ・ Успешно",
            (
                "Вы успешно взяли отпуск!\n\n"
                f"**Имя:**\n{interaction.user.mention}\n"
                f"**Насколько:**\n{duration_text}\n"
                f"**Причина:**\n{reason}\n"
                f"**До:**\n{_fmt_until_local(until_ts)} ({_left_text(until_ts)})\n"
                f"**Роли:**\n{role_result}"
            ),
        )
        await interaction.response.send_message(embed=e, ephemeral=True)


class VacationActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Выберите действие",
            min_values=1,
            max_values=1,
            custom_id="vacation_actions_select",
            options=[
                discord.SelectOption(label="Взять отпуск", description="Указать длительность и причину", value="take"),
                discord.SelectOption(label="Отменить отпуск", description="Вернуться из отпуска", value="cancel"),
                discord.SelectOption(label="Список отпусков", description="Кто в отпуске", value="list"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(embed=_black_embed("Отпуск", "Команда доступна только на сервере."), ephemeral=True)
            return
        action = self.values[0]
        if action == "take":
            await interaction.response.send_modal(VacationTakeModal())
        elif action == "cancel":
            removed_role_ids: list[int] = []
            payload = get_vacation_map(guild_id=interaction.guild.id).get(interaction.user.id, {})
            raw_removed = payload.get("removed_role_ids", []) if isinstance(payload, dict) else []
            if isinstance(raw_removed, list):
                for x in raw_removed:
                    try:
                        removed_role_ids.append(int(x))
                    except (TypeError, ValueError):
                        continue
            member = interaction.user if isinstance(interaction.user, discord.Member) else None
            if member is not None:
                await _restore_vacation_roles(interaction.guild, member, removed_role_ids)
            clear_vacation(guild_id=interaction.guild.id, user_id=interaction.user.id)
            await interaction.response.send_message(embed=_black_embed("Отпуск снят", "Вы вышли из отпуска."), ephemeral=True)
        else:
            rows = _active_vacations(interaction.guild)
            if not rows:
                await interaction.response.send_message(embed=_black_embed("Список отпусков", "Сейчас никто не в отпуске."), ephemeral=True)
                return
            lines: list[str] = []
            for user_id, member, until_ts, _reason in rows:
                who = member.mention if member is not None else f"<@{user_id}>"
                lines.append(f"{who} — до **{_fmt_until_local(until_ts)}** ({_left_text(until_ts)})")
            e = _black_embed("— ・ Список отпусков", "\n\n".join(lines), footer=f"Всего в отпуске: {len(rows)}")
            await interaction.response.send_message(embed=e, ephemeral=True)

        if interaction.message is not None:
            try:
                await interaction.message.edit(view=VacationPanelView())
            except (discord.Forbidden, discord.HTTPException):
                pass


class VacationPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(VacationActionSelect())

