from __future__ import annotations

import datetime as dt
import re
import asyncio

import discord

from applications import (
    PANEL_IMAGE_FILENAME,
    build_application_embed,
    build_application_receipt_panel_embed,
)
from storage import (
    get_accept_role_id_for_type,
    get_applications_enabled_for_type,
    get_call_category_id,
    get_call_final_meta,
    get_destination_channel_id,
    get_ticket_view_role_ids,
    next_ticket_id,
    set_applications_enabled_for_type,
    set_call_final_meta,
)

_TICKET_TITLE_RE = re.compile(r"^Заявка #(\d+) — (.+)$", re.IGNORECASE)
_APPLICANT_ID_RE = re.compile(r"ID:\s*(\d+)", re.IGNORECASE)


def parse_application_embed(embed: discord.Embed) -> tuple[int, int, str] | None:
    title = embed.title or ""
    m = _TICKET_TITLE_RE.match(title.strip())
    if not m:
        return None
    ticket_id = int(m.group(1))
    application_type = m.group(2).strip()
    applicant_id: int | None = None
    for fld in embed.fields:
        if fld.name == "Заявитель":
            im = _APPLICANT_ID_RE.search(fld.value or "")
            if im:
                applicant_id = int(im.group(1))
                break
    if applicant_id is None:
        return None
    return applicant_id, ticket_id, application_type


RP_QUESTIONS: list[tuple[str, str]] = [
    ("1) Ник | Возраст | Онлайн", "NickName | 16 | 4-6 часов в день"),
    ("2) В каких семьях были", "Например: Killa,Black,Gucci"),
    ("3) Откуда узнали о семье Спортсменов", "Например: Слышал, YouTube, Друзья"),
    ("4) Готовы ли сменить фамилию", "Да/Нет"),
    ("5) Откат стрельбы DM 10500 урона", "Ссылка на YouTube"),
]

VZP_QUESTIONS: list[tuple[str, str]] = [
    ("1) Ник | Возраст | Онлайн", "NickName | 16 | 4-6 часов в день"),
    ("2) В каких семьях были", "Например: Killa,Black,Gucci"),
    ("3) Сколько часов в GTA", "Например: 1000-2000 часов"),
    ("4) Опыт игры", "Например: 2 года"),
    ("5) Откат с ВЗП", "Сылка на YouTube"),
]

CAPT_BIZ_QUESTIONS: list[tuple[str, str]] = [
    ("1) Ник | Возраст", "NickName | 18"),
    ("2) В каких семьях были", "Например: Wise,Pain и тд"),
    ("3) Были ли ЧС если да то за что", "Например: Да/Нет, Читы"),
    ("4) Откаты Capt/Biz(Not archiv)", "Ссылка на YouTube"),
]


class ApplicationModal(discord.ui.Modal):
    def __init__(self, *, application_type: str, questions: list[tuple[str, str]], destination_channel_id: int):
        super().__init__(title=f"Заявка — {application_type}")
        self.application_type = application_type
        self.questions = questions
        self.destination_channel_id = destination_channel_id

        for label, placeholder in questions:
            self.add_item(
                discord.ui.TextInput(
                    label=label[:45],
                    placeholder=placeholder[:100] if placeholder else None,
                    style=discord.TextStyle.paragraph,
                    required=True,
                    max_length=900,
                )
            )

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        answers: dict[str, str] = {}
        for idx, (label, _) in enumerate(self.questions):
            answers[label] = self.children[idx].value  # type: ignore[attr-defined]

        ticket_id = next_ticket_id(guild_id=interaction.guild.id)
        embed = build_application_embed(
            ticket_id=ticket_id,
            application_type=self.application_type,
            applicant=interaction.user,
            answers=answers,
        )

        content = f"Новая заявка: **{self.application_type}** • `#{ticket_id}`"
        destination_id = get_destination_channel_id(guild_id=interaction.guild.id) or self.destination_channel_id
        channel = interaction.client.get_channel(destination_id)
        if channel is None:
            try:
                channel = await interaction.client.fetch_channel(destination_id)
            except discord.NotFound:
                channel = None

        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message(
                "Не смог найти канал для заявок. Проверь выбранный канал и права бота.",
                ephemeral=True,
            )
            return

        await channel.send(
            content=content,
            embed=embed,
            view=ApplicationReviewView(
                applicant_id=interaction.user.id,
                ticket_id=ticket_id,
                application_type=self.application_type,
            ),
        )

        await interaction.response.send_message(
            "Заявка отправлена. Ожидайте решения в личных сообщениях (если открыты).",
            ephemeral=True,
        )

def _safe_channel_name(name: str) -> str:
    # Discord: lowercase, letters/digits/underscore (unicode) + hyphen.
    # Разрешаем кириллицу, чтобы было "ник-номер", а не user-2.
    name = name.lower()
    name = re.sub(r"[^\w\-]+", "-", name, flags=re.UNICODE)
    name = re.sub(r"_{1,}", "-", name)  # underscores -> hyphen
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name[:60] or "ник"


def _schedule_channel_delete(channel: discord.abc.GuildChannel, *, delay_s: float = 3.0) -> None:
    async def _delete():
        await asyncio.sleep(delay_s)
        try:
            await channel.delete(reason="Тикет завершён")
        except Exception:
            pass

    asyncio.create_task(_delete())


def _fmt_time_local() -> str:
    # Формат как на скрине: 10.04.2026 19:25
    return dt.datetime.now().strftime("%d.%m.%Y %H:%M")


def _admin_line(member: discord.abc.User) -> str:
    display = member.display_name if isinstance(member, discord.Member) else member.name
    return f"{member.mention} | {display} | {member.id}"


def build_dm_call_embed(*, guild: discord.Guild, channel: discord.TextChannel, admin: discord.Member) -> discord.Embed:
    e = discord.Embed(
        title="— ・ Обзвон",
        description=(
            f"- **Время:**\n{_fmt_time_local()}\n\n"
            f"- **Канал:**\n{channel.mention}\n\n"
            f"- **Администратор:**\n{_admin_line(admin)}\n\n"
            "Если вам неудобно будет пройти обзвон — обратитесь к администратору."
        ),
        color=discord.Color.dark_gray(),
    )
    if guild.icon:
        e.set_thumbnail(url=guild.icon.url)
    e.set_footer(text=_fmt_time_local())
    return e


def build_dm_verdict_embed(
    *,
    guild: discord.Guild,
    admin: discord.Member,
    application_type: str,
    approved: bool,
    reason: str | None = None,
) -> discord.Embed:
    if approved:
        desc = f"Ваша заявка в **{application_type}** была **одобрена**!\nПоздравляем!"
    else:
        desc = f"Ваша заявка в **{application_type}** была **отклонена**."
        if reason:
            desc += f"\n\n**Причина:** {reason}"

    e = discord.Embed(
        title="— ・ Вердикт по заявке",
        description=f"{desc}\n\n**Администратор:**\n{_admin_line(admin)}",
        color=discord.Color.dark_gray(),
    )
    if guild.icon:
        e.set_thumbnail(url=guild.icon.url)
    e.set_footer(text=_fmt_time_local())
    return e


class ApplicationTypeSelect(discord.ui.Select):
    def __init__(self, *, destination_channel_id: int):
        self.destination_channel_id = destination_channel_id
        self._application_map: dict[str, tuple[str, list[tuple[str, str]]]] = {
            "RP": ("RP", RP_QUESTIONS),
            "VZP": ("VZP", VZP_QUESTIONS),
            "CAPT_BIZ": ("Capt/Biz", CAPT_BIZ_QUESTIONS),
        }
        super().__init__(
            placeholder="Подать заявку в Спортсменов",
            min_values=1,
            max_values=1,
            custom_id=f"application_type_select:{destination_channel_id}",
            options=[
                discord.SelectOption(
                    label="Подать Заявку RP",
                    value="RP",
                    description="Нажмите, чтобы заполнить анкету RP",
                    emoji="🔐",
                ),
                discord.SelectOption(
                    label="Подать Заявку VZP",
                    value="VZP",
                    description="Нажмите, чтобы заполнить анкету VZP",
                    emoji="🎯",
                ),
                discord.SelectOption(
                    label="Подать Заявку Capt/Biz",
                    value="CAPT_BIZ",
                    description="Нажмите, чтобы заполнить анкету Capt/Biz",
                    emoji="📑",
                ),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0] if self.values else "RP"
        if interaction.guild is not None:
            if not get_applications_enabled_for_type(guild_id=interaction.guild.id, application_type=selected):
                await interaction.response.send_message(
                    "Прием заявок этого типа сейчас закрыт модерацией.",
                    ephemeral=True,
                )
                return
        application_type, questions = self._application_map.get(selected, ("RP", RP_QUESTIONS))
        await interaction.response.send_modal(
            ApplicationModal(
                application_type=application_type,
                questions=questions,
                destination_channel_id=self.destination_channel_id,
            )
        )


class RejectReasonModal(discord.ui.Modal):
    def __init__(self, *, applicant_id: int, ticket_id: int, application_type: str):
        super().__init__(title=f"Отказать • #{ticket_id}")
        self.applicant_id = applicant_id
        self.ticket_id = ticket_id
        self.application_type = application_type
        self.reason = discord.ui.TextInput(
            label="Причина отказа",
            placeholder="Например: недостаточные откаты / низкий онлайн / нет условий",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=600,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        applicant = interaction.guild.get_member(self.applicant_id)
        if applicant is None:
            try:
                applicant = await interaction.guild.fetch_member(self.applicant_id)
            except discord.NotFound:
                applicant = None

        if applicant is not None and isinstance(interaction.user, discord.Member):
            try:
                await applicant.send(
                    embed=build_dm_verdict_embed(
                        guild=interaction.guild,
                        admin=interaction.user,
                        application_type=self.application_type,
                        approved=False,
                        reason=self.reason.value,
                    )
                )
            except discord.Forbidden:
                pass

        # mark message as decided + disable buttons
        if interaction.message:
            embeds = interaction.message.embeds
            if embeds:
                e = embeds[0]
                # Update status field (first field)
                if e.fields:
                    e.set_field_at(0, name="Статус", value="**❌ Отказано**", inline=False)
                else:
                    e.add_field(name="Статус", value="**❌ Отказано**", inline=False)
                # Убираем кнопки полностью после вердикта
                await interaction.message.edit(embed=e, view=None)

        await interaction.response.send_message("Готово. Отказ отправлен в ЛС (если открыты).", ephemeral=True)


class ApplicationReviewView(discord.ui.View):
    def __init__(
        self,
        *,
        applicant_id: int = 0,
        ticket_id: int = 0,
        application_type: str = "",
        disabled: bool = False,
    ):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.ticket_id = ticket_id
        self.application_type = application_type
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = disabled

    def _resolve_ticket(self, interaction: discord.Interaction) -> tuple[int, int, str] | None:
        if self.applicant_id and self.ticket_id and self.application_type:
            return self.applicant_id, self.ticket_id, self.application_type
        if interaction.message and interaction.message.embeds:
            parsed = parse_application_embed(interaction.message.embeds[0])
            if parsed is not None:
                return parsed
        return None

    @classmethod
    def disabled(cls, applicant_id: int, ticket_id: int, application_type: str) -> "ApplicationReviewView":
        return cls(applicant_id=applicant_id, ticket_id=ticket_id, application_type=application_type, disabled=True)

    @discord.ui.button(label="Обзвон", style=discord.ButtonStyle.success, custom_id="review_call")
    async def review_call(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        resolved = self._resolve_ticket(interaction)
        if resolved is None:
            await interaction.response.send_message(
                "Не удалось прочитать заявку из сообщения.",
                ephemeral=True,
            )
            return
        applicant_id, ticket_id, application_type = resolved

        # Кнопка может выполняться дольше 3 секунд (создание канала/запросы),
        # поэтому сразу подтверждаем interaction, иначе будет "Unknown interaction".
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        applicant = guild.get_member(applicant_id)
        if applicant is None:
            try:
                applicant = await guild.fetch_member(applicant_id)
            except discord.NotFound:
                applicant = None

        base_name = _safe_channel_name(applicant.display_name if applicant else f"user-{applicant_id}")
        ch_name = f"обзвон-{base_name}-{ticket_id}"

        # Куда создавать канал обзвона:
        # 1) если админ привязал категорию — используем её
        # 2) иначе создаём в той же категории, где и канал проверки
        category = None
        bound_category_id = get_call_category_id(guild_id=guild.id)
        if bound_category_id:
            category = guild.get_channel(bound_category_id)
            if category is None:
                try:
                    category = await guild.fetch_channel(bound_category_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    category = None
        if not isinstance(category, discord.CategoryChannel):
            category = interaction.channel.category if isinstance(interaction.channel, discord.TextChannel) else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),  # type: ignore[arg-type]
        }
        if applicant is not None:
            overwrites[applicant] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        # Доп. роли, которым разрешено смотреть тикеты/обзвон
        for rid in get_ticket_view_role_ids(guild_id=guild.id):
            role = guild.get_role(rid)
            if role is not None:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, read_message_history=True)

        try:
            call_channel = await guild.create_text_channel(
                name=ch_name[:100],
                category=category,
                overwrites=overwrites,
                reason=f"Обзвон по заявке #{ticket_id}",
            )
        except discord.Forbidden:
            await interaction.followup.send("Нет прав создавать каналы.", ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.followup.send("Не смог создать канал (ошибка Discord).", ephemeral=True)
            return

        if applicant is not None and isinstance(interaction.user, discord.Member):
            try:
                await applicant.send(
                    embed=build_dm_call_embed(
                        guild=guild,
                        channel=call_channel,
                        admin=interaction.user,
                    )
                )
            except discord.Forbidden:
                pass

        # update application message + disable buttons
        if interaction.message:
            embeds = interaction.message.embeds
            if embeds:
                e = embeds[0]
                if e.fields:
                    e.set_field_at(0, name="Статус", value="**📞 Обзвон**", inline=False)
                else:
                    e.add_field(name="Статус", value="**📞 Обзвон**", inline=False)
                # Убираем кнопки полностью после перевода в обзвон
                await interaction.message.edit(embed=e, view=None)

        # В канал обзвона — копию заявки + "Принять/Отказать"
        original_channel_id = interaction.channel.id if interaction.channel else 0
        original_message_id = interaction.message.id if interaction.message else 0
        try:
            call_msg = await call_channel.send(
                content=f"Заявка `#{ticket_id}` — **{application_type}**",
                embed=interaction.message.embeds[0] if interaction.message and interaction.message.embeds else None,
                view=CallFinalView(
                    applicant_id=applicant_id,
                    ticket_id=ticket_id,
                    application_type=application_type,
                    original_channel_id=original_channel_id,
                    original_message_id=original_message_id,
                ),
            )
            set_call_final_meta(
                message_id=call_msg.id,
                applicant_id=applicant_id,
                ticket_id=ticket_id,
                application_type=application_type,
                original_channel_id=original_channel_id,
                original_message_id=original_message_id,
            )
        except discord.HTTPException:
            pass

        await interaction.followup.send(f"Канал создан: {call_channel.mention}", ephemeral=True)

    @discord.ui.button(label="Отказать", style=discord.ButtonStyle.danger, custom_id="review_reject")
    async def review_reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        resolved = self._resolve_ticket(interaction)
        if resolved is None:
            await interaction.response.send_message(
                "Не удалось прочитать заявку из сообщения.",
                ephemeral=True,
            )
            return
        applicant_id, ticket_id, application_type = resolved
        await interaction.response.send_modal(
            RejectReasonModal(
                applicant_id=applicant_id,
                ticket_id=ticket_id,
                application_type=application_type,
            )
        )


class CallRejectReasonModal(discord.ui.Modal):
    def __init__(
        self,
        *,
        applicant_id: int,
        ticket_id: int,
        application_type: str,
        original_channel_id: int,
        original_message_id: int,
    ):
        super().__init__(title=f"Отказать • #{ticket_id}")
        self.applicant_id = applicant_id
        self.ticket_id = ticket_id
        self.application_type = application_type
        self.original_channel_id = original_channel_id
        self.original_message_id = original_message_id
        self.reason = discord.ui.TextInput(
            label="Причина отказа",
            placeholder="Например: не прошёл обзвон / не соответствует условиям",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=600,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        guild = interaction.guild
        admin = interaction.user if isinstance(interaction.user, discord.Member) else None

        applicant = guild.get_member(self.applicant_id)
        if applicant is None:
            try:
                applicant = await guild.fetch_member(self.applicant_id)
            except discord.NotFound:
                applicant = None

        if applicant is not None and admin is not None:
            try:
                await applicant.send(
                    embed=build_dm_verdict_embed(
                        guild=guild,
                        admin=admin,
                        application_type=self.application_type,
                        approved=False,
                        reason=self.reason.value,
                    )
                )
            except discord.Forbidden:
                pass

        # Обновим сообщение в канале обзвона: статус + убрать кнопки
        if interaction.message and interaction.message.embeds:
            e = interaction.message.embeds[0]
            if e.fields:
                e.set_field_at(0, name="Статус", value="**❌ Отказано**", inline=False)
            else:
                e.add_field(name="Статус", value="**❌ Отказано**", inline=False)
            await interaction.message.edit(embed=e, view=None)

        # И оригинальную заявку тоже обновим (если можем)
        if original_channel_id and original_message_id:
            try:
                ch = guild.get_channel(original_channel_id)
                if isinstance(ch, discord.TextChannel):
                    msg = await ch.fetch_message(original_message_id)
                    if msg.embeds:
                        e2 = msg.embeds[0]
                        if e2.fields:
                            e2.set_field_at(0, name="Статус", value="**❌ Отказано**", inline=False)
                        else:
                            e2.add_field(name="Статус", value="**❌ Отказано**", inline=False)
                        await msg.edit(embed=e2, view=None)
            except Exception:
                pass

        await interaction.response.send_message("Готово. Отказ отправлен в ЛС (если открыты).", ephemeral=True)

        # Закрываем канал обзвона
        if interaction.channel and isinstance(interaction.channel, discord.TextChannel):
            _schedule_channel_delete(interaction.channel)


class CallFinalView(discord.ui.View):
    def __init__(
        self,
        *,
        applicant_id: int = 0,
        ticket_id: int = 0,
        application_type: str = "",
        original_channel_id: int = 0,
        original_message_id: int = 0,
    ):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.ticket_id = ticket_id
        self.application_type = application_type
        self.original_channel_id = original_channel_id
        self.original_message_id = original_message_id

    def _resolve_call(
        self, interaction: discord.Interaction
    ) -> tuple[int, int, str, int, int] | None:
        if self.applicant_id and self.ticket_id and self.application_type:
            return (
                self.applicant_id,
                self.ticket_id,
                self.application_type,
                self.original_channel_id,
                self.original_message_id,
            )
        if interaction.message is not None:
            stored = get_call_final_meta(message_id=interaction.message.id)
            if stored is not None:
                return (
                    int(stored.get("applicant_id", 0)),
                    int(stored.get("ticket_id", 0)),
                    str(stored.get("application_type", "")),
                    int(stored.get("original_channel_id", 0)),
                    int(stored.get("original_message_id", 0)),
                )
            if interaction.message.embeds:
                parsed = parse_application_embed(interaction.message.embeds[0])
                if parsed is not None:
                    applicant_id, ticket_id, application_type = parsed
                    return applicant_id, ticket_id, application_type, 0, 0
        return None

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success, custom_id="call_accept")
    async def call_accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        resolved = self._resolve_call(interaction)
        if resolved is None:
            await interaction.response.send_message(
                "Не удалось прочитать данные заявки.",
                ephemeral=True,
            )
            return
        applicant_id, ticket_id, application_type, original_channel_id, original_message_id = resolved

        guild = interaction.guild
        admin = interaction.user

        applicant = guild.get_member(applicant_id)
        if applicant is None:
            try:
                applicant = await guild.fetch_member(applicant_id)
            except discord.NotFound:
                applicant = None

        # Выдать роль при принятии (если настроена)
        role_result: str | None = None
        if applicant is not None:
            rid = get_accept_role_id_for_type(guild_id=guild.id, application_type=application_type)
            if not rid:
                role_result = "роль не настроена"
            else:
                role = guild.get_role(rid)
                if role is None:
                    role_result = "роль не найдена (удалена?)"
                else:
                    bot_member = guild.me
                    if bot_member is None:
                        role_result = "не смог определить права бота"
                    else:
                        if not bot_member.guild_permissions.manage_roles:
                            role_result = "боту не хватает права **Manage Roles**"
                        elif role >= bot_member.top_role:
                            role_result = "роль выше/равна роли бота (подними роль бота выше)"
                        elif role in applicant.roles:
                            role_result = "роль уже есть у пользователя"
                        else:
                            try:
                                await applicant.add_roles(role, reason=f"Принят по заявке #{ticket_id}")
                                role_result = f"роль выдана: {role.mention}"
                            except discord.Forbidden:
                                role_result = "нет прав выдать роль (иерархия/права)"
                            except discord.HTTPException:
                                role_result = "ошибка Discord при выдаче роли"
        else:
            role_result = "пользователь не найден на сервере"

        if applicant is not None:
            try:
                await applicant.send(
                    embed=build_dm_verdict_embed(
                        guild=guild,
                        admin=admin,
                        application_type=application_type,
                        approved=True,
                    )
                )
            except discord.Forbidden:
                pass

        # Обновим сообщение в канале обзвона: статус + убрать кнопки
        if interaction.message and interaction.message.embeds:
            e = interaction.message.embeds[0]
            if e.fields:
                e.set_field_at(0, name="Статус", value="**✅ Принято**", inline=False)
            else:
                e.add_field(name="Статус", value="**✅ Принято**", inline=False)
            await interaction.message.edit(embed=e, view=None)

        # И оригинальную заявку тоже обновим (если можем)
        if original_channel_id and original_message_id:
            try:
                ch = guild.get_channel(original_channel_id)
                if isinstance(ch, discord.TextChannel):
                    msg = await ch.fetch_message(original_message_id)
                    if msg.embeds:
                        e2 = msg.embeds[0]
                        if e2.fields:
                            e2.set_field_at(0, name="Статус", value="**✅ Принято**", inline=False)
                        else:
                            e2.add_field(name="Статус", value="**✅ Принято**", inline=False)
                        await msg.edit(embed=e2, view=None)
            except Exception:
                pass

        extra = f"\nРоль: {role_result}" if role_result else ""
        await interaction.response.send_message(
            f"Готово. Принятие отправлено в ЛС (если открыты).{extra}",
            ephemeral=True,
        )

        # Закрываем канал обзвона
        if interaction.channel and isinstance(interaction.channel, discord.TextChannel):
            _schedule_channel_delete(interaction.channel)

    @discord.ui.button(label="Отказать", style=discord.ButtonStyle.danger, custom_id="call_reject")
    async def call_reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        resolved = self._resolve_call(interaction)
        if resolved is None:
            await interaction.response.send_message(
                "Не удалось прочитать данные заявки.",
                ephemeral=True,
            )
            return
        applicant_id, ticket_id, application_type, original_channel_id, original_message_id = resolved
        await interaction.response.send_modal(
            CallRejectReasonModal(
                applicant_id=applicant_id,
                ticket_id=ticket_id,
                application_type=application_type,
                original_channel_id=original_channel_id,
                original_message_id=original_message_id,
            )
        )


_PANEL_TEXT = (
    "👋 **Путь в семью начинается здесь!**\n"
    "\n"
    "・Отсюда подают заявку в Семью или в RP. Выберите тип заявки в меню ниже.\n"
    "\n"
    "> **Подать заявку можно только при открытом наборе. Если не выходит - набор закрыт.**\n"
    "Внимательно прочтите сообщение ниже.\n"
    "\n"
    "・**Выберите тип заявки**"
)


class ApplicationPanelView(discord.ui.View):
    def __init__(self, *, destination_channel_id: int):
        super().__init__(timeout=None)
        self.add_item(ApplicationTypeSelect(destination_channel_id=destination_channel_id))


if hasattr(discord.ui, "LayoutView"):
    class ApplicationPanelV2View(discord.ui.LayoutView):  # type: ignore[misc]
        def __init__(self, *, destination_channel_id: int):
            super().__init__(timeout=None)
            # Embed v2: собираем "карточку" через Container с акцент-цветом,
            # чтобы визуально было максимально похоже на обычный embed:
            # большая картинка сверху -> текст -> выпадающее меню.
            media_gallery_cls = getattr(discord.ui, "MediaGallery", None)
            media_gallery_item_cls = getattr(discord, "MediaGalleryItem", None)
            container_cls = getattr(discord.ui, "Container", None)
            separator_cls = getattr(discord.ui, "Separator", None)
            text_display_cls = getattr(discord.ui, "TextDisplay", None)
            action_row_cls = getattr(discord.ui, "ActionRow", None)

            # "Карточка" как embed: картинка + текст + селект в одном Container.
            inner: list[discord.ui.Item] = []
            if media_gallery_cls and media_gallery_item_cls:
                inner.append(
                    media_gallery_cls(
                        media_gallery_item_cls(
                            f"attachment://{PANEL_IMAGE_FILENAME}",
                            description="Баннер панели заявок",
                        )
                    )
                )
                if separator_cls:
                    inner.append(separator_cls())
            if text_display_cls:
                inner.append(text_display_cls(_PANEL_TEXT))
            if separator_cls:
                inner.append(separator_cls())
            # В Embed v2 интерактивы (селекты/кнопки) должны лежать внутри ActionRow.
            # Иначе Discord API возвращает 400 Invalid Form Body.
            if action_row_cls:
                inner.append(
                    action_row_cls(
                        ApplicationTypeSelect(destination_channel_id=destination_channel_id)
                    )
                )
            else:
                inner.append(ApplicationTypeSelect(destination_channel_id=destination_channel_id))

            if container_cls:
                self.add_item(container_cls(*inner, accent_color=discord.Color.dark_gray()))
            else:
                for it in inner:
                    self.add_item(it)
else:
    ApplicationPanelV2View = None


_APP_RECV_ROWS: tuple[tuple[str, str], ...] = (
    ("RP", "РП"),
    ("VZP", "VZP"),
    ("CAPT_BIZ", "Capt/Biz"),
)


def application_receipt_status_map(guild_id: int) -> dict[str, bool]:
    return {
        key: get_applications_enabled_for_type(guild_id=guild_id, application_type=key)
        for key, _ in _APP_RECV_ROWS
    }


class _AppRecvToggleButton(discord.ui.Button):
    def __init__(self, *, app_key: str, label_short: str, enable: bool, row: int) -> None:
        suffix = "Вкл" if enable else "Выкл"
        custom_id = f"apprecv:{app_key}:{'1' if enable else '0'}"
        style = discord.ButtonStyle.success if enable else discord.ButtonStyle.danger
        super().__init__(label=f"{label_short} — {suffix}", style=style, custom_id=custom_id, row=row)
        self.app_key = app_key
        self.enable = enable

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Доступно только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Нужны права **администратора**.", ephemeral=True)
            return

        set_applications_enabled_for_type(
            guild_id=interaction.guild.id,
            application_type=self.app_key,
            enabled=self.enable,
        )

        if interaction.message is None:
            await interaction.response.send_message("Не удалось обновить сообщение.", ephemeral=True)
            return

        new_embed = build_application_receipt_panel_embed(
            guild=interaction.guild,
            status_by_type=application_receipt_status_map(interaction.guild.id),
            bot_user=interaction.client.user,
        )
        await interaction.response.edit_message(embed=new_embed, view=ApplicationReceiptPanelView())


class ApplicationReceiptPanelView(discord.ui.View):
    """Постоянные кнопки (custom_id `apprecv:<тип>:0|1`) — зарегистрируйте через bot.add_view."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        for row, (app_key, label_short) in enumerate(_APP_RECV_ROWS):
            self.add_item(_AppRecvToggleButton(app_key=app_key, label_short=label_short, enable=True, row=row))
            self.add_item(_AppRecvToggleButton(app_key=app_key, label_short=label_short, enable=False, row=row))

