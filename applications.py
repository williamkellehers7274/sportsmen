from __future__ import annotations

import datetime as dt

import discord


PANEL_IMAGE_FILENAME = "panel.png"


def build_panel_embed(*, with_image: bool = False) -> discord.Embed:
    embed = discord.Embed(
        description=(
            "👋 **Путь в семью начинается здесь!**\n"
            "\n"
            "・Отсюда подают заявку в Семью или в RP. Выберите тип заявки в меню ниже.\n"
            "\n"
            "> **Подать заявку можно только при открытом наборе. Если не выходит - набор закрыт.**\n"
            "Внимательно прочтите сообщение ниже.\n"
            "\n"
            "・**Выберите тип заявки**"
        ),
        color=discord.Color.dark_gray(),
    )
    if with_image:
        embed.set_image(url=f"attachment://{PANEL_IMAGE_FILENAME}")
    return embed


def build_application_embed(
    *,
    ticket_id: int,
    application_type: str,
    applicant: discord.abc.User,
    answers: dict[str, str],
    status: str = "⏳ На рассмотрении",
) -> discord.Embed:
    embed = discord.Embed(
        title=f"Заявка #{ticket_id} — {application_type}",
        # Чёрная "палочка" слева (темный цвет)
        color=discord.Color.dark_gray(),
        timestamp=dt.datetime.now(dt.timezone.utc),
    )
    embed.add_field(name="Статус", value=f"**{status}**", inline=False)
    embed.add_field(name="Заявитель", value=f"{applicant.mention}\n`{applicant}`\n`ID: {applicant.id}`", inline=False)

    for q, a in answers.items():
        embed.add_field(name=q, value=(a[:1024] if a else "—"), inline=False)

    embed.set_footer(text="Отправлено через Embed v2")
    if getattr(applicant, "display_avatar", None):
        embed.set_thumbnail(url=applicant.display_avatar.url)
    return embed


def build_application_receipt_panel_embed(
    *,
    guild: discord.abc.Guild,
    status_by_type: dict[str, bool],
    bot_user: discord.abc.User | None = None,
) -> discord.Embed:
    """
    Панель управления приёмом заявок (кнопки обновляют то же сообщение).
    status_by_type: ключи RP, VZP, CAPT_BIZ → включён ли приём.
    """
    order: tuple[tuple[str, str], ...] = (
        ("RP", "РП"),
        ("VZP", "VZP (ВЗП)"),
        ("CAPT_BIZ", "Capt / Biz"),
    )

    embed = discord.Embed(
        title="— ・ Приём заявок",
        description=(
            "**Включите или выключите** нужные направления.\n"
            "Кнопки ниже **обновляют это сообщение** — статус всегда актуальный.\n\n"
            "───────────────"
        ),
        color=discord.Color.dark_gray(),
        timestamp=dt.datetime.now(dt.timezone.utc),
    )

    for key, title in order:
        on = bool(status_by_type.get(key, True))
        val = "🟢 **Вкл** — набор открыт" if on else "🔴 **Выкл** — набор закрыт"
        embed.add_field(name=title, value=val, inline=True)

    embed.set_footer(text="Панель модерации · только администраторы")
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    if bot_user is not None:
        embed.set_author(
            name=bot_user.display_name,
            icon_url=bot_user.display_avatar.url,
        )
    return embed

