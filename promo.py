from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import discord

from storage import add_user_points, get_promo_channel_id


PROMO_PANEL_IMAGE_FILENAME = "promo_panel.png"


def _fmt_time_local() -> str:
    return dt.datetime.now().strftime("%d.%m.%Y %H:%M")


def _promo_image_file() -> discord.File | None:
    p = Path(__file__).resolve().parent / "foto" / PROMO_PANEL_IMAGE_FILENAME
    if p.exists() and p.is_file():
        return discord.File(str(p), filename=PROMO_PANEL_IMAGE_FILENAME)
    return None


def build_promo_panel_embed(*, with_image: bool = False) -> discord.Embed:
    e = discord.Embed(
        title="Промокод",
        description=(
            "Можете подать за промик тут.\n\n"
            "Нажмите **Подать промокод**, приложите ссылку на фото/скрин (например, imgur/discord/ютуб), "
            "после чего заявка улетит на проверку.\n\n"
            "Решение: **Принять / Отказать**.\n"
            "При принятии начислим **+100** монет."
        ),
        color=discord.Color.dark_gray(),
    )
    if with_image:
        e.set_image(url=f"attachment://{PROMO_PANEL_IMAGE_FILENAME}")
    e.set_footer(text="Спортсмены • Промокоды")
    return e


def _build_promo_sent_embed() -> discord.Embed:
    return discord.Embed(
        description="— ・ **Готово**\n\nПромокод отправлен на проверку. Ожидайте результат в ЛС от бота.",
        color=discord.Color.dark_gray(),
    )


def _build_promo_verdict_embed(
    *,
    guild: discord.Guild,
    admin: discord.Member,
    approved: bool,
    reason: str | None = None,
    reward: int = 100,
    balance: float | None = None,
) -> discord.Embed:
    if approved:
        desc = "Ваш промокод был **принят**!\nПоздравляем!"
        desc += f"\n\n**Начислено:** {reward} монет"
        if balance is not None:
            desc += f"\n**Баланс:** {balance:.2f}"
    else:
        desc = "Ваш промокод был **отклонён**."
        if reason:
            desc += f"\n\n**Причина:** {reason}"

    e = discord.Embed(
        title="— ・ Вердикт по промокоду",
        description=f"{desc}\n\n**Администратор:**\n{admin.mention} | {admin.display_name} | {admin.id}",
        color=discord.Color.dark_gray(),
        timestamp=dt.datetime.now(dt.timezone.utc),
    )
    if guild.icon:
        e.set_thumbnail(url=guild.icon.url)
    e.set_footer(text=_fmt_time_local())
    return e


class PromoSubmitModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Промокод — заявка")
        self.photo = discord.ui.TextInput(
            label="Ссылка на фото/скрин",
            placeholder="Вставьте ссылку на фото/скрин с промокодом",
            style=discord.TextStyle.short,
            required=True,
            max_length=500,
        )
        self.add_item(self.photo)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        review_channel_id = get_promo_channel_id(guild_id=interaction.guild.id)
        if not review_channel_id:
            await interaction.response.send_message(
                "Промокоды не настроены. Администрации нужно сделать `/привязка-промо`.",
                ephemeral=True,
            )
            return

        review_channel = interaction.guild.get_channel(review_channel_id)
        if review_channel is None:
            try:
                review_channel = await interaction.guild.fetch_channel(review_channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                review_channel = None
        if not isinstance(review_channel, discord.TextChannel):
            await interaction.response.send_message(
                "Не удалось найти канал проверки промокодов. Обратитесь к администрации.",
                ephemeral=True,
            )
            return

        url = self.photo.value.strip()
        # небольшая защита от мусора (не блокируем, просто нормализуем пробелы)
        url = re.sub(r"\s+", "", url)

        review_embed = discord.Embed(
            title="— ・ Промокод на проверку",
            description=(f"**Пользователь:** {interaction.user.mention}\n" f"**Ссылка:** {url}"),
            color=discord.Color.dark_gray(),
            timestamp=dt.datetime.now(dt.timezone.utc),
        )
        review_embed.add_field(name="Статус", value="**⏳ На проверке**", inline=False)
        review_embed.add_field(name="Награда", value="**100** монет", inline=False)
        review_embed.add_field(name="ID пользователя", value=str(interaction.user.id), inline=False)
        review_embed.add_field(name="Ссылка", value=url[:1024] or "—", inline=False)
        review_embed.set_footer(text="promo")

        try:
            review_msg = await review_channel.send(embed=review_embed, view=PromoReviewView())
        except discord.Forbidden:
            await interaction.response.send_message(
                "Не смог отправить заявку в канал проверки (нет прав).",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            await interaction.response.send_message(
                "Не смог отправить заявку в канал проверки (ошибка Discord).",
                ephemeral=True,
            )
            return
        try:
            await interaction.user.send(
                embed=discord.Embed(
                    title="— ・ Заявка по промокоду отправлена",
                    description=(
                        "Ваша заявка отправлена на проверку.\n\n"
                        f"**Ссылка:** {url}\n"
                        f"**Статус:** ⏳ На проверке\n\n"
                        f"[Перейти к заявке]({review_msg.jump_url})"
                    ),
                    color=discord.Color.dark_gray(),
                    timestamp=dt.datetime.now(dt.timezone.utc),
                )
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

        await interaction.response.send_message(embed=_build_promo_sent_embed(), ephemeral=True)


class PromoPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Подать промокод", style=discord.ButtonStyle.success, custom_id="promo_submit")
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(PromoSubmitModal())


class PromoRejectReasonModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Причина отказа")
        self.reason = discord.ui.TextInput(
            label="Укажите причину отказа",
            placeholder="Например: не видно промокод / невалидно / уже использован",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=600,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Только администрация может отклонять промокоды.", ephemeral=True)
            return
        if not interaction.message.embeds:
            await interaction.response.send_message("Не удалось прочитать данные заявки.", ephemeral=True)
            return

        e = interaction.message.embeds[0]
        user_id: int | None = None
        for fld in e.fields:
            if fld.name == "ID пользователя":
                try:
                    user_id = int(str(fld.value).strip())
                except ValueError:
                    user_id = None
                break

        if e.fields:
            e.set_field_at(0, name="Статус", value=f"**❌ Отказано**\nПричина: {self.reason.value}", inline=False)
        else:
            e.add_field(name="Статус", value=f"**❌ Отказано**\nПричина: {self.reason.value}", inline=False)
        await interaction.message.edit(embed=e, view=None)

        if user_id is not None:
            user = interaction.guild.get_member(user_id)
            if user is None:
                try:
                    user = await interaction.guild.fetch_member(user_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    user = None
            if user is not None:
                try:
                    await user.send(
                        embed=_build_promo_verdict_embed(
                            guild=interaction.guild,
                            admin=interaction.user,
                            approved=False,
                            reason=self.reason.value,
                        )
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

        await interaction.response.send_message("Промокод отклонён.", ephemeral=True)


class PromoReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success, custom_id="promo_review_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Только администрация может принимать промокоды.", ephemeral=True)
            return
        if not interaction.message.embeds:
            await interaction.response.send_message("Не удалось прочитать данные заявки.", ephemeral=True)
            return

        e = interaction.message.embeds[0]
        user_id: int | None = None
        reward: int = 100
        for fld in e.fields:
            if fld.name == "ID пользователя":
                try:
                    user_id = int(str(fld.value).strip())
                except ValueError:
                    user_id = None
            if fld.name == "Награда":
                m = re.search(r"\d+", str(fld.value))
                reward = int(m.group(0)) if m else reward

        if user_id is None:
            await interaction.response.send_message("Не найден ID пользователя.", ephemeral=True)
            return

        new_balance = add_user_points(guild_id=interaction.guild.id, user_id=user_id, delta=float(reward))
        if e.fields:
            e.set_field_at(
                0,
                name="Статус",
                value=f"**✅ Принято**\nПроверил: {interaction.user.mention}\nНачислено: {reward}",
                inline=False,
            )
        else:
            e.add_field(
                name="Статус",
                value=f"**✅ Принято**\nПроверил: {interaction.user.mention}\nНачислено: {reward}",
                inline=False,
            )
        await interaction.message.edit(embed=e, view=None)

        user = interaction.guild.get_member(user_id)
        if user is None:
            try:
                user = await interaction.guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                user = None
        if user is not None:
            try:
                await user.send(
                    embed=_build_promo_verdict_embed(
                        guild=interaction.guild,
                        admin=interaction.user,
                        approved=True,
                        reward=reward,
                        balance=new_balance,
                    )
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

        await interaction.response.send_message("Промокод принят. Монеты начислены.", ephemeral=True)

    @discord.ui.button(label="Отказать", style=discord.ButtonStyle.danger, custom_id="promo_review_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Только администрация может отклонять промокоды.", ephemeral=True)
            return
        await interaction.response.send_modal(PromoRejectReasonModal())


__all__ = [
    "PROMO_PANEL_IMAGE_FILENAME",
    "_promo_image_file",
    "build_promo_panel_embed",
    "PromoPanelView",
    "PromoReviewView",
]

