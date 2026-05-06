from __future__ import annotations

from pathlib import Path
import asyncio
import datetime as dt
import json
import re
import random
import time
import urllib.parse
import urllib.request

import discord
from discord import app_commands

import config
from tg_userbot_rp_bridge import spawn_telegram_userbot_rp_bridge
from afk import AFKPanelView, _afk_image_file, build_afk_panel_embed, process_expired_afk_for_guild
from applications import (
    PANEL_IMAGE_FILENAME,
    build_application_receipt_panel_embed,
    build_panel_embed,
)
from promo import PromoPanelView, PromoReviewView, _promo_image_file, build_promo_panel_embed
from vacation import (
    VacationPanelView,
    _vacation_image_file,
    build_vacation_panel_embed,
    process_expired_vacation_for_guild,
)
from storage import (
    add_pending_report,
    add_user_points,
    get_afk_panel_message_id,
    get_applications_enabled_for_type,
    get_destination_channel_id,
    get_call_category_id,
    get_contracts_panel_message_id,
    get_attack_def_cooldown_config,
    get_attack_def_cooldown_until,
    get_attack_def_panel_message_id,
    get_role_ping_notify_binding,
    get_temp_voice_owner_id,
    get_voice_lobby_channel_id,
    get_voice_hub_panel_message_id,
    get_panel_message_id,
    get_pending_reports,
    get_points_map,
    get_logs_channel_id,
    get_report_types,
    get_reports_channel_id,
    get_reports_panel_message_id,
    get_portfolio_category_id,
    get_portfolio_profile,
    get_rank_role_id,
    get_tier_role_id,
    get_portfolio_channel_owner_id,
    get_shop_orders_channel_id,
    get_shop_panel_message_id,
    get_shop_items,
    get_stream_announce_channel_id,
    get_giveaway_notify_role_ids,
    get_giveaway_states_for_guild,
    get_stream_announce_twitch_map,
    get_twitch_live_state_by_guild,
    get_stream_announce_user_ids,
    get_ticket_view_role_ids,
    get_user_points,
    get_promo_channel_id,
    get_promo_panel_message_id,
    add_pending_shop_order,
    get_pending_shop_orders,
    remove_pending_shop_order,
    get_vacation_remove_role_ids,
    get_vacation_role_id,
    get_vacation_panel_message_id,
    remove_pending_report,
    set_user_points,
    set_afk_panel_message_id,
    set_applications_enabled_for_type,
    set_accept_role_id,
    set_destination_channel_id,
    set_call_category_id,
    set_contracts_panel_message_id,
    set_attack_def_cooldown_config,
    set_attack_def_cooldown_until,
    set_attack_def_panel_message_id,
    set_role_ping_notify_binding,
    set_temp_voice_owner_id,
    set_voice_lobby_channel_id,
    set_voice_hub_panel_message_id,
    set_panel_message_id,
    set_logs_channel_id,
    set_report_types,
    set_reports_channel_id,
    set_reports_panel_message_id,
    set_portfolio_category_id,
    set_portfolio_profile,
    set_rank_role_id,
    set_tier_role_id,
    set_portfolio_channel_owner_id,
    set_shop_orders_channel_id,
    set_shop_panel_message_id,
    set_shop_items,
    set_stream_announce_channel_id,
    set_giveaway_notify_role_ids,
    set_giveaway_state,
    set_stream_announce_twitch_map,
    set_twitch_live_state_by_guild,
    set_stream_announce_user_ids,
    set_ticket_view_role_ids,
    set_promo_channel_id,
    set_promo_panel_message_id,
    set_vacation_channel_id,
    set_vacation_remove_role_ids,
    set_vacation_role_id,
    set_vacation_panel_message_id,
    remove_temp_voice_owner_id,
    get_daily_menu_message_ids,
    set_daily_menu_message_ids,
)
from ui import (
    ApplicationPanelView,
    ApplicationPanelV2View,
    ApplicationReceiptPanelView,
    application_receipt_status_map,
)

EMBED_COLOR = discord.Color.from_rgb(0, 0, 0)
# Единый цвет всех embed'ов (чёрная полоса слева).
discord.Color.dark_gray = classmethod(lambda cls: EMBED_COLOR)  # type: ignore[assignment]


_RU_LAT_MAP: dict[str, str] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def _slugify_event_key(name: str) -> str:
    s = (name or "").strip().lower()
    if not s:
        return ""
    out_chars: list[str] = []
    for ch in s:
        if "a" <= ch <= "z" or "0" <= ch <= "9" or ch == "_":
            out_chars.append(ch)
        elif ch in {" ", "-", ".", "/"}:
            out_chars.append("_")
        else:
            mapped = _RU_LAT_MAP.get(ch)
            if mapped is not None:
                out_chars.append(mapped)
            else:
                out_chars.append("_")
    key = "".join(out_chars)
    key = re.sub(r"_+", "_", key).strip("_")[:32]
    return key


def _normalize_twitch_login(raw: str) -> str:
    login = (raw or "").strip().lower()
    login = re.sub(r"^https?://(www\.)?twitch\.tv/", "", login)
    login = login.split("/")[0].strip().lower()
    login = "".join(ch for ch in login if ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch == "_")
    if len(login) < 3:
        return ""
    return login[:25]


def _sync_http_json(*, url: str, method: str = "GET", headers: dict[str, str] | None = None, body: dict | None = None) -> dict:
    req_headers = {"User-Agent": "bot-carti/1.0"}
    if headers:
        req_headers.update(headers)
    data_bytes = None
    if body is not None:
        data_bytes = urllib.parse.urlencode(body).encode("utf-8")
    req = urllib.request.Request(url=url, method=method, headers=req_headers, data=data_bytes)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw or "{}")


async def _events_key_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    if interaction.guild is None:
        return []
    cur = (current or "").strip().lower()
    m = _get_report_types_for_guild(interaction.guild.id)
    items: list[tuple[str, str, int]] = []
    for key, v in m.items():
        label = str(v.get("label", "Ивент"))
        reward = int(v.get("reward", 0) or 0)
        items.append((key, label, reward))
    items.sort(key=lambda x: (x[1].casefold(), x[0]))
    res: list[app_commands.Choice[str]] = []
    for key, label, reward in items:
        hay = f"{key} {label}".lower()
        if cur and cur not in hay:
            continue
        res.append(app_commands.Choice(name=f"{label} ({reward}) — {key}"[:100], value=key))
        if len(res) >= 25:
            break
    return res


class EventsManageEventSelect(discord.ui.Select):
    def __init__(self, *, guild_id: int):
        m = _get_report_types_for_guild(guild_id)
        items: list[tuple[str, str, int]] = []
        for key, v in m.items():
            items.append((str(key), str(v.get("label", "Ивент")), int(v.get("reward", 0) or 0)))
        items.sort(key=lambda x: (x[1].casefold(), x[0]))
        if items:
            options = [
                discord.SelectOption(
                    label=label[:100],
                    value=key[:100],
                    description=f"{reward} балл."[:100],
                )
                for key, label, reward in items[:25]
            ]
            disabled = False
        else:
            options = [discord.SelectOption(label="Список пуст", value="__none__", description="Сначала добавьте ивент")]
            disabled = True
        super().__init__(
            placeholder="Выберите ивент",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="events_manage_event_select",
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if isinstance(self.view, EventsManageView):
            self.view.selected_key = self.values[0]
        try:
            await interaction.response.defer(ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            return
        try:
            await interaction.message.edit(view=self.view)
        except (discord.Forbidden, discord.HTTPException):
            pass
        await interaction.followup.send("Ивент выбран.", ephemeral=True)


class EventsManageActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Выберите действие",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Добавить", value="add"),
                discord.SelectOption(label="Изменить", value="update"),
                discord.SelectOption(label="Удалить", value="remove"),
            ],
            custom_id="events_manage_action_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Только администрация может настраивать ивенты.", ephemeral=True)
            return
        if not isinstance(self.view, EventsManageView):
            await interaction.response.send_message("Не удалось прочитать состояние панели.", ephemeral=True)
            return

        action = self.values[0]
        if action == "add":
            await interaction.response.send_modal(EventsAddModal())
            return

        key = (self.view.selected_key or "").strip().lower()
        if not key:
            await interaction.response.send_message("Сначала выбери ивент в первом списке.", ephemeral=True)
            return

        current_map = _get_report_types_for_guild(interaction.guild.id)
        cur = current_map.get(key)
        if not cur:
            await interaction.response.send_message("Ивент не найден (возможно уже удалён).", ephemeral=True)
            return

        if action == "update":
            await interaction.response.send_modal(
                EventsEditModal(
                    event_key=key,
                    current_label=str(cur.get("label", "")),
                    current_desc=str(cur.get("desc", "")),
                    current_reward=int(cur.get("reward", 0) or 0),
                )
            )
            return

        if action == "remove":
            removed_label = str(cur.get("label", key))
            new_list: list[dict[str, str | int]] = [
                {"key": k, "label": str(v["label"]), "desc": str(v.get("desc", "")), "reward": int(v["reward"])}
                for k, v in current_map.items()
                if str(k) != key
            ]
            set_report_types(guild_id=interaction.guild.id, types=new_list)
            updated_panel = await _refresh_reports_panel_message(guild=interaction.guild)
            try:
                await interaction.message.edit(view=EventsManageView(guild_id=interaction.guild.id))
            except (discord.Forbidden, discord.HTTPException):
                pass
            await interaction.response.send_message(
                f"Готово. Ивент удалён: **{removed_label}** (`{key}`)"
                + (" Панель отчётов обновлена автоматически." if updated_panel else " Запусти `/панель-отчетов` один раз."),
                ephemeral=True,
            )
            return

        await interaction.response.send_message("Неизвестное действие.", ephemeral=True)


class EventsEditModal(discord.ui.Modal):
    def __init__(
        self,
        *,
        event_key: str,
        current_label: str,
        current_desc: str,
        current_reward: int,
    ):
        self.event_key = event_key
        self.current_reward = int(current_reward)
        super().__init__(title=f"Ивент • {current_label or event_key}"[:45])
        self.new_label = discord.ui.TextInput(
            label="Название (пусто = оставить)",
            placeholder=current_label[:100] or "Название",
            style=discord.TextStyle.short,
            required=False,
            max_length=100,
        )
        self.new_desc = discord.ui.TextInput(
            label="Описание (пусто = оставить)",
            placeholder=(current_desc[:100] or "Короткое описание")[:100],
            style=discord.TextStyle.short,
            required=False,
            max_length=100,
        )
        self.new_reward = discord.ui.TextInput(
            label="Баллы (пусто = оставить)",
            placeholder=str(int(current_reward)),
            style=discord.TextStyle.short,
            required=False,
            max_length=12,
        )
        self.add_item(self.new_label)
        self.add_item(self.new_desc)
        self.add_item(self.new_reward)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Только администрация может настраивать ивенты.", ephemeral=True)
            return

        current_map = _get_report_types_for_guild(interaction.guild.id)
        cur = current_map.get(self.event_key)
        if not cur:
            await interaction.response.send_message("Ивент не найден (возможно уже удалён).", ephemeral=True)
            return

        label = (self.new_label.value or "").strip() or str(cur.get("label", "Ивент"))
        desc = (self.new_desc.value or "").strip() or str(cur.get("desc", "")).strip()
        reward = int(cur.get("reward", 0) or 0)
        raw_reward = (self.new_reward.value or "").strip()
        if raw_reward:
            m = re.search(r"-?\d+", raw_reward)
            if not m:
                await interaction.response.send_message("В поле `Баллы` укажи число.", ephemeral=True)
                return
            reward = int(m.group(0))
        if reward <= 0:
            await interaction.response.send_message("Баллы должны быть > 0.", ephemeral=True)
            return
        if not desc:
            desc = f"{int(reward)} коин(а)"

        new_list: list[dict[str, str | int]] = []
        for k, v in current_map.items():
            if str(k) == self.event_key:
                new_list.append(
                    {"key": self.event_key, "label": label[:100], "desc": desc[:100], "reward": int(reward)}
                )
            else:
                new_list.append(
                    {"key": str(k), "label": str(v["label"]), "desc": str(v.get("desc", "")), "reward": int(v["reward"])}
                )
        set_report_types(guild_id=interaction.guild.id, types=new_list)
        updated_panel = await _refresh_reports_panel_message(guild=interaction.guild)
        await interaction.response.send_message(
            f"Готово. Ивент обновлён: **{label}** (`{self.event_key}`)"
            + (" Панель отчётов обновлена автоматически." if updated_panel else " Запусти `/панель-отчетов` один раз."),
            ephemeral=True,
        )


class EventsAddModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Добавить ивент")
        self.new_label = discord.ui.TextInput(
            label="Название",
            placeholder="Например: Рейд на босса",
            style=discord.TextStyle.short,
            required=True,
            max_length=100,
        )
        self.new_reward = discord.ui.TextInput(
            label="Баллы",
            placeholder="Например: 10",
            style=discord.TextStyle.short,
            required=True,
            max_length=12,
        )
        self.new_desc = discord.ui.TextInput(
            label="Описание (необязательно)",
            placeholder="Короткое описание в списке",
            style=discord.TextStyle.short,
            required=False,
            max_length=100,
        )
        self.add_item(self.new_label)
        self.add_item(self.new_reward)
        self.add_item(self.new_desc)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Только администрация может настраивать ивенты.", ephemeral=True)
            return

        label = (self.new_label.value or "").strip()
        if not label:
            await interaction.response.send_message("Укажи название ивента.", ephemeral=True)
            return

        m = re.search(r"-?\d+", (self.new_reward.value or "").strip())
        if not m:
            await interaction.response.send_message("В поле `Баллы` укажи число.", ephemeral=True)
            return
        reward = int(m.group(0))
        if reward <= 0:
            await interaction.response.send_message("Баллы должны быть > 0.", ephemeral=True)
            return

        current_map = _get_report_types_for_guild(interaction.guild.id)
        base_key = _slugify_event_key(label) or f"evt_{int(dt.datetime.now().timestamp())}"
        key = base_key
        n = 2
        while key in current_map and n < 99:
            suffix = f"_{n}"
            key = (base_key[: (32 - len(suffix))] + suffix)[:32]
            n += 1

        desc = (self.new_desc.value or "").strip() or f"{int(reward)} коин(а)"
        new_list: list[dict[str, str | int]] = [
            {"key": str(k), "label": str(v["label"]), "desc": str(v.get("desc", "")), "reward": int(v["reward"])}
            for k, v in current_map.items()
        ]
        new_list.append({"key": key, "label": label[:100], "desc": desc[:100], "reward": int(reward)})
        set_report_types(guild_id=interaction.guild.id, types=new_list)
        updated_panel = await _refresh_reports_panel_message(guild=interaction.guild)
        await interaction.response.send_message(
            f"Готово. Ивент добавлен: **{label[:100]}** (`{key}`)"
            + (" Панель отчётов обновлена автоматически." if updated_panel else " Запусти `/панель-отчетов` один раз."),
            ephemeral=True,
        )


class EventsManageView(discord.ui.View):
    def __init__(self, *, guild_id: int):
        super().__init__(timeout=900)
        self.selected_key: str | None = None
        self.add_item(EventsManageEventSelect(guild_id=guild_id))
        self.add_item(EventsManageActionSelect())


async def _shop_item_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    if interaction.guild is None:
        return []
    cur = (current or "").strip().lower()
    items = _get_shop_items_for_guild(interaction.guild.id)
    # name, price
    res: list[app_commands.Choice[str]] = []
    for name, price in items:
        hay = f"{name} {price}".lower()
        if cur and cur not in hay:
            continue
        res.append(app_commands.Choice(name=f"{name} — {price}"[:100], value=name))
        if len(res) >= 25:
            break
    return res


class Bot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.presences = True
        intents.message_content = True
        intents.voice_states = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self._twitch_access_token: str | None = None
        self._twitch_token_expire_ts: float = 0.0
        self._twitch_live_state_by_guild: dict[int, set[int]] = {}

    async def setup_hook(self) -> None:
        # Restore runtime states that should survive bot restarts.
        self._twitch_live_state_by_guild = get_twitch_live_state_by_guild()
        _DAILY_MENU_MESSAGE_ID_BY_USER.update(get_daily_menu_message_ids())
        for guild in list(self.guilds):
            stored = get_giveaway_states_for_guild(guild_id=guild.id)
            for message_id, payload in stored.items():
                state = GiveawayState.from_payload(payload)
                if state is None:
                    continue
                GIVEAWAYS[_giveaway_key(guild_id=guild.id, message_id=message_id)] = state

        # Persistent view fallback for panels created with env-configured destination
        if config.APPLICATION_CHANNEL_ID:
            self.add_view(ApplicationPanelView(destination_channel_id=config.APPLICATION_CHANNEL_ID))
        self.add_view(AFKPanelView())
        self.add_view(VacationPanelView())
        self.add_view(VzpMapView())
        self.add_view(ShopPanelView())
        self.add_view(ShopOrderReviewView())
        self.add_view(ReportPanelView())
        self.add_view(ReportVzhPanelView())
        self.add_view(ReportMpPanelView())
        self.add_view(ReportReviewView())
        self.add_view(PromoPanelView())
        self.add_view(PromoReviewView())
        self.add_view(PortfolioPanelView())
        self.add_view(GiveawayView())
        self.add_view(AttackDefCooldownView())
        self.add_view(ContractsPanelView())
        self.add_view(ContractReviewView())
        self.add_view(ApplicationReceiptPanelView())
        self.add_view(PrivateVoiceHubView())

        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

        self.loop.create_task(self._afk_expire_loop())
        self.loop.create_task(self._twitch_stream_watch_loop())
        self.loop.create_task(self._daily_message_loop())
        self.loop.create_task(self._attack_def_expire_loop())
        spawn_telegram_userbot_rp_bridge(self)

    async def _daily_message_loop(self) -> None:
        # Ежедневные сообщения: несколько вариантов (канал/время/текст) через /ежедневка.
        from storage import (
            get_daily_message_entries,
            get_daily_message_sent_map,
            set_daily_message_sent_for_entry,
        )

        await self.wait_until_ready()
        while not self.is_closed():
            try:
                now = dt.datetime.now(MSK_TZ)
                today = now.strftime("%Y-%m-%d")
                for guild in list(self.guilds):
                    entries = get_daily_message_entries(guild_id=guild.id)
                    if not entries:
                        continue
                    sent_map = get_daily_message_sent_map(guild_id=guild.id)
                    for item in entries:
                        entry_id = int(item.get("id", 0))
                        channel_id = int(item.get("channel_id", 0))
                        hour = int(item.get("hour", -1))
                        minute = int(item.get("minute", -1))
                        text = str(item.get("text", "")).strip()
                        if not entry_id or not channel_id or not text:
                            continue
                        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                            continue
                        if sent_map.get(entry_id) == today:
                            continue
                        if (now.hour, now.minute) < (hour, minute):
                            continue

                        ch = guild.get_channel(channel_id)
                        if ch is None:
                            try:
                                ch = await guild.fetch_channel(channel_id)
                            except Exception:
                                ch = None
                        if isinstance(ch, (discord.TextChannel, discord.Thread)):
                            try:
                                await ch.send(text, allowed_mentions=discord.AllowedMentions(roles=True, users=True))
                                set_daily_message_sent_for_entry(guild_id=guild.id, entry_id=entry_id, ymd=today)
                            except Exception:
                                pass
            except Exception:
                pass
            await asyncio.sleep(30)

    async def _get_twitch_access_token(self, *, force_refresh: bool = False) -> str | None:
        if not config.TWITCH_CLIENT_ID or not config.TWITCH_CLIENT_SECRET:
            return None
        now = time.time()
        if not force_refresh and self._twitch_access_token and now < (self._twitch_token_expire_ts - 60):
            return self._twitch_access_token
        try:
            payload = await asyncio.to_thread(
                _sync_http_json,
                url="https://id.twitch.tv/oauth2/token",
                method="POST",
                body={
                    "client_id": config.TWITCH_CLIENT_ID,
                    "client_secret": config.TWITCH_CLIENT_SECRET,
                    "grant_type": "client_credentials",
                },
            )
            token = str(payload.get("access_token", "")).strip()
            expires = int(payload.get("expires_in", 0) or 0)
            if not token or expires <= 0:
                return None
            self._twitch_access_token = token
            self._twitch_token_expire_ts = now + float(expires)
            return token
        except Exception:
            return None

    async def _fetch_live_twitch_logins(self, logins: list[str]) -> set[str]:
        if not logins:
            return set()
        token = await self._get_twitch_access_token()
        if not token:
            return set()

        query = "&".join(f"user_login={urllib.parse.quote(login)}" for login in logins[:100])
        url = f"https://api.twitch.tv/helix/streams?{query}"
        headers = {
            "Client-Id": config.TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {token}",
        }
        for attempt in range(2):
            try:
                data = await asyncio.to_thread(_sync_http_json, url=url, headers=headers)
                out: set[str] = set()
                for item in data.get("data", []) or []:
                    login = str(item.get("user_login", "")).strip().lower()
                    if login:
                        out.add(login)
                return out
            except Exception:
                if attempt == 0:
                    fresh = await self._get_twitch_access_token(force_refresh=True)
                    if not fresh:
                        break
                    headers["Authorization"] = f"Bearer {fresh}"
                    continue
                break
        return set()

    async def _twitch_stream_watch_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            if not config.TWITCH_CLIENT_ID or not config.TWITCH_CLIENT_SECRET:
                await asyncio.sleep(30)
                continue

            for guild in self.guilds:
                channel_id = get_stream_announce_channel_id(guild_id=guild.id)
                if channel_id is None:
                    self._twitch_live_state_by_guild[guild.id] = set()
                    set_twitch_live_state_by_guild(state=self._twitch_live_state_by_guild)
                    continue

                allowed_ids = set(get_stream_announce_user_ids(guild_id=guild.id))
                twitch_map = get_stream_announce_twitch_map(guild_id=guild.id)
                tracked = [(uid, twitch_map.get(uid, "")) for uid in allowed_ids]
                tracked = [(uid, login) for uid, login in tracked if login]
                if not tracked:
                    self._twitch_live_state_by_guild[guild.id] = set()
                    set_twitch_live_state_by_guild(state=self._twitch_live_state_by_guild)
                    continue

                live_logins = await self._fetch_live_twitch_logins([login for _, login in tracked])
                current_live_ids = {uid for uid, login in tracked if login in live_logins}
                prev_live_ids = self._twitch_live_state_by_guild.get(guild.id)
                if prev_live_ids is None:
                    self._twitch_live_state_by_guild[guild.id] = set(current_live_ids)
                    set_twitch_live_state_by_guild(state=self._twitch_live_state_by_guild)
                    continue

                started_now = current_live_ids - prev_live_ids
                if started_now:
                    channel = guild.get_channel(channel_id)
                    if channel is None:
                        try:
                            channel = await guild.fetch_channel(channel_id)
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            channel = None
                    if isinstance(channel, discord.TextChannel):
                        for uid in started_now:
                            login = twitch_map.get(uid, "")
                            if not login:
                                continue
                            text = f"@everyone 🔴 <@{uid}> запустил стрим! Заходи смотреть: https://twitch.tv/{login}"
                            try:
                                await channel.send(text, allowed_mentions=discord.AllowedMentions(everyone=True, users=True))
                            except (discord.Forbidden, discord.HTTPException):
                                pass
                self._twitch_live_state_by_guild[guild.id] = set(current_live_ids)
                set_twitch_live_state_by_guild(state=self._twitch_live_state_by_guild)
            await asyncio.sleep(45)

    async def _afk_expire_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            for guild in self.guilds:
                try:
                    await process_expired_afk_for_guild(guild)
                except Exception:
                    pass
                try:
                    await process_expired_vacation_for_guild(guild)
                except Exception:
                    pass
            await asyncio.sleep(30)

    async def _attack_def_expire_loop(self) -> None:
        """Auto-refresh ATT/DEFF panel when cooldown expires."""
        await self.wait_until_ready()
        while not self.is_closed():
            now_ts = int(time.time())
            for guild in self.guilds:
                try:
                    until = get_attack_def_cooldown_until(guild_id=guild.id)
                except Exception:
                    continue

                att_until = int(until.get("att_until_ts", 0) or 0)
                deff_until = int(until.get("deff_until_ts", 0) or 0)

                # When timer reaches zero, normalize value to 0 and refresh panel text.
                changed = False
                if att_until > 0 and att_until <= now_ts:
                    att_until = 0
                    changed = True
                if deff_until > 0 and deff_until <= now_ts:
                    deff_until = 0
                    changed = True

                if not changed:
                    continue

                try:
                    set_attack_def_cooldown_until(
                        guild_id=guild.id,
                        att_until_ts=att_until,
                        deff_until_ts=deff_until,
                    )
                except Exception:
                    continue

                try:
                    await _refresh_attack_def_panel_message(guild=guild)
                except Exception:
                    pass
            await asyncio.sleep(5)


bot = Bot()


def _extract_target(raw: str | None) -> int | None:
    if not raw:
        return None
    m = re.search(r"\d+", raw)
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None


def _format_member_list(guild: discord.Guild, ids: set[int]) -> str:
    if not ids:
        return "—"
    chunks: list[str] = []
    for uid in ids:
        member = guild.get_member(uid)
        chunks.append(member.mention if member is not None else f"<@{uid}>")
    return "\n".join(chunks[:25])


class SborView(discord.ui.View):
    def __init__(self, *, author_id: int, main_target: int | None, sub_target: int | None):
        super().__init__(timeout=None)
        self.author_id = author_id
        self.main_target = main_target
        self.sub_target = sub_target
        self.main_ids: set[int] = set()
        self.sub_ids: set[int] = set()
        self.published_channel_id: int | None = None
        self.published_message_id: int | None = None
        self.is_published: bool = False

    def _apply_to_embed(self, embed: discord.Embed, guild: discord.Guild) -> discord.Embed:
        main_title = f"Участники ({len(self.main_ids)}/{self.main_target})" if self.main_target else f"Участники ({len(self.main_ids)})"
        sub_title = f"Замены ({len(self.sub_ids)}/{self.sub_target})" if self.sub_target else f"Замены ({len(self.sub_ids)})"
        if len(embed.fields) >= 2:
            embed.set_field_at(0, name=main_title, value=_format_member_list(guild, self.main_ids), inline=False)
            embed.set_field_at(1, name=sub_title, value=_format_member_list(guild, self.sub_ids), inline=False)
        return embed

    async def _refresh_message(self, interaction: discord.Interaction) -> None:
        if interaction.message is None or interaction.guild is None:
            return
        embeds = interaction.message.embeds
        if not embeds:
            return
        e = self._apply_to_embed(embeds[0], interaction.guild)
        await interaction.message.edit(embed=e, view=self)
        await self._update_published_message(guild=interaction.guild, source_embed=e)

    async def _update_published_message(self, *, guild: discord.Guild, source_embed: discord.Embed) -> None:
        if not self.published_channel_id or not self.published_message_id:
            return
        ch = guild.get_channel(self.published_channel_id)
        if not isinstance(ch, discord.TextChannel):
            return
        try:
            msg = await ch.fetch_message(self.published_message_id)
            pub_embed = self.build_publish_embed(guild=guild, source_embed=source_embed)
            await msg.edit(embed=pub_embed)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    def _set_signup_buttons_disabled(self, disabled: bool) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id in {
                "sbor_join_main",
                "sbor_join_sub",
                "sbor_leave",
            }:
                child.disabled = disabled

    def _can_moderate(self, user: discord.abc.User) -> bool:
        if user.id == self.author_id:
            return True
        if isinstance(user, discord.Member):
            return user.guild_permissions.manage_messages or user.guild_permissions.administrator
        return False

    def _member_select_options(self, guild: discord.Guild) -> list[discord.SelectOption]:
        ids = list(self.main_ids | self.sub_ids)
        options: list[discord.SelectOption] = []
        for uid in ids[:25]:
            member = guild.get_member(uid)
            label = member.display_name if member is not None else str(uid)
            in_main = uid in self.main_ids
            role = "основа" if in_main else "замена"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(uid),
                    description=f"Сейчас: {role}",
                )
            )
        return options

    def _moderate_member(self, user_id: int, action: str) -> str:
        if action == "main":
            self.sub_ids.discard(user_id)
            self.main_ids.add(user_id)
            return "Пользователь перемещён в основу."
        if action == "sub":
            self.main_ids.discard(user_id)
            self.sub_ids.add(user_id)
            return "Пользователь перемещён в замены."
        if action == "remove":
            removed = user_id in self.main_ids or user_id in self.sub_ids
            self.main_ids.discard(user_id)
            self.sub_ids.discard(user_id)
            return "Пользователь удалён из списка." if removed else "Пользователя не было в списке."
        return "Неизвестное действие."

    def build_publish_embed(self, *, guild: discord.Guild, source_embed: discord.Embed) -> discord.Embed:
        out = discord.Embed(
            title=f"{source_embed.title or 'Сбор'} — опубликованный список",
            description=source_embed.description or "—",
            color=discord.Color.dark_gray(),
            timestamp=dt.datetime.now(dt.timezone.utc),
        )
        out.add_field(
            name=f"Основа ({len(self.main_ids)})",
            value=_format_member_list(guild, self.main_ids),
            inline=False,
        )
        out.add_field(
            name=f"Замены ({len(self.sub_ids)})",
            value=_format_member_list(guild, self.sub_ids),
            inline=False,
        )
        out.set_footer(text="Опубликовано модератором")
        return out

    @discord.ui.button(label="В основу", style=discord.ButtonStyle.success, custom_id="sbor_join_main")
    async def join_main(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.is_published:
            await interaction.response.send_message("Список уже опубликован. Запись закрыта, доступна только модерация.", ephemeral=True)
            return
        uid = interaction.user.id
        self.sub_ids.discard(uid)
        self.main_ids.add(uid)
        await self._refresh_message(interaction)
        await interaction.response.send_message("Ты записан в основу.", ephemeral=True)

    @discord.ui.button(label="На замену", style=discord.ButtonStyle.secondary, custom_id="sbor_join_sub")
    async def join_sub(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.is_published:
            await interaction.response.send_message("Список уже опубликован. Запись закрыта, доступна только модерация.", ephemeral=True)
            return
        uid = interaction.user.id
        self.main_ids.discard(uid)
        self.sub_ids.add(uid)
        await self._refresh_message(interaction)
        await interaction.response.send_message("Ты записан на замену.", ephemeral=True)

    @discord.ui.button(label="Выйти", style=discord.ButtonStyle.danger, custom_id="sbor_leave")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.is_published:
            await interaction.response.send_message("Список уже опубликован. Запись закрыта, доступна только модерация.", ephemeral=True)
            return
        uid = interaction.user.id
        self.main_ids.discard(uid)
        self.sub_ids.discard(uid)
        await self._refresh_message(interaction)
        await interaction.response.send_message("Ты убран из списка.", ephemeral=True)

    @discord.ui.button(label="Модерация", style=discord.ButtonStyle.primary, custom_id="sbor_moderate")
    async def moderate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or interaction.channel is None or interaction.message is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not self._can_moderate(interaction.user):
            await interaction.response.send_message(
                "Только организатор сбора или администратор может модерировать список.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "Панель модерации:",
            ephemeral=True,
            view=SborModerationPanelView(
                sbor_view=self,
                source_channel_id=interaction.channel.id,
                source_message_id=interaction.message.id,
                guild=interaction.guild,
            ),
        )


class SborMemberSelect(discord.ui.Select):
    def __init__(self, *, panel: "SborModerationPanelView", guild: discord.Guild):
        self.panel = panel
        options = panel.sbor_view._member_select_options(guild)
        if not options:
            options = [discord.SelectOption(label="Список пуст", value="none", description="Некого модерировать")]
        super().__init__(
            placeholder="Выбери участника",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="sbor_mod_member_select",
            disabled=(len(panel.sbor_view.main_ids | panel.sbor_view.sub_ids) == 0),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.panel.selected_user_id = None if self.values[0] == "none" else int(self.values[0])
        await interaction.response.send_message("Участник выбран.", ephemeral=True)


class SborActionSelect(discord.ui.Select):
    def __init__(self, *, panel: "SborModerationPanelView"):
        self.panel = panel
        super().__init__(
            placeholder="Выбери действие",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Переместить в основу", value="main"),
                discord.SelectOption(label="Переместить в замены", value="sub"),
                discord.SelectOption(label="Удалить из списка", value="remove"),
                discord.SelectOption(label="Опубликовать список", value="publish"),
            ],
            custom_id="sbor_mod_action_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not self.panel.sbor_view._can_moderate(interaction.user):
            await interaction.response.send_message("У тебя нет прав на модерацию.", ephemeral=True)
            return

        action = self.values[0]
        if action == "publish":
            source_msg = await self.panel._fetch_source_message(interaction.guild)
            if source_msg is None:
                await interaction.response.send_message("Не удалось найти исходное сообщение сбора.", ephemeral=True)
                return
            source_embed = source_msg.embeds[0] if source_msg.embeds else discord.Embed(title="Сбор")
            pub_embed = self.panel.sbor_view.build_publish_embed(guild=interaction.guild, source_embed=source_embed)
            view_ref = self.panel.sbor_view
            if view_ref.published_channel_id and view_ref.published_message_id:
                ch = interaction.guild.get_channel(view_ref.published_channel_id)
                if isinstance(ch, discord.TextChannel):
                    try:
                        old_pub = await ch.fetch_message(view_ref.published_message_id)
                        await old_pub.edit(embed=pub_embed)
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        new_pub = await interaction.channel.send(embed=pub_embed)
                        view_ref.published_channel_id = new_pub.channel.id
                        view_ref.published_message_id = new_pub.id
                else:
                    new_pub = await interaction.channel.send(embed=pub_embed)
                    view_ref.published_channel_id = new_pub.channel.id
                    view_ref.published_message_id = new_pub.id
            else:
                new_pub = await interaction.channel.send(embed=pub_embed)
                view_ref.published_channel_id = new_pub.channel.id
                view_ref.published_message_id = new_pub.id

            view_ref.is_published = True
            view_ref._set_signup_buttons_disabled(True)
            await source_msg.edit(view=view_ref)
            await interaction.response.send_message("Список опубликован. Запись закрыта, доступна только модерация.", ephemeral=True)
            return

        if self.panel.selected_user_id is None:
            await interaction.response.send_message("Сначала выбери участника в первом выпадающем списке.", ephemeral=True)
            return

        result_text = self.panel.sbor_view._moderate_member(user_id=self.panel.selected_user_id, action=action)
        source_msg = await self.panel._fetch_source_message(interaction.guild)
        if source_msg is not None and source_msg.embeds:
            e = self.panel.sbor_view._apply_to_embed(source_msg.embeds[0], interaction.guild)
            await source_msg.edit(embed=e, view=self.panel.sbor_view)
            await self.panel.sbor_view._update_published_message(guild=interaction.guild, source_embed=e)
        await interaction.response.send_message(result_text, ephemeral=True)


class SborModerationPanelView(discord.ui.View):
    def __init__(self, *, sbor_view: SborView, source_channel_id: int, source_message_id: int, guild: discord.Guild):
        super().__init__(timeout=300)
        self.sbor_view = sbor_view
        self.source_channel_id = source_channel_id
        self.source_message_id = source_message_id
        self.selected_user_id: int | None = None
        self.add_item(SborMemberSelect(panel=self, guild=guild))
        self.add_item(SborActionSelect(panel=self))

    async def _fetch_source_message(self, guild: discord.Guild) -> discord.Message | None:
        source_channel = guild.get_channel(self.source_channel_id)
        if not isinstance(source_channel, discord.TextChannel):
            return None
        try:
            return await source_channel.fetch_message(self.source_message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

def _format_sbor_type(t: str, detail: str | None) -> str:
    base = {"vzp": "ВЗП", "biz": "Биз", "capt": "Капт", "content": "Контент"}.get(t, t)
    if t == "content" and detail:
        return f"{base}: {detail}"
    return base


def _parse_sbor_time(raw: str) -> tuple[dt.datetime, str] | None:
    text = raw.strip()
    if not text:
        return None

    # "15" => через 15 минут
    if re.fullmatch(r"\d{1,3}", text):
        mins = int(text)
        if mins <= 0 or mins > 24 * 60:
            return None
        when = dt.datetime.now() + dt.timedelta(minutes=mins)
        return when, f"через {mins} мин"

    # "19:00" or "19 00"
    m = re.fullmatch(r"(\d{1,2})[:\s](\d{2})", text)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    if hh > 23 or mm > 59:
        return None

    now = dt.datetime.now()
    when = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if when <= now:
        when = when + dt.timedelta(days=1)
    return when, when.strftime("%d.%m %H:%M")


VZP_MAP_FILE_MAP: dict[str, list[str]] = {
    "Байкерка": ["1.png"],
    "Большой миррор": ["2.png"],
    "Веспуччи": ["3.png"],
    "Ветряки": ["4.png"],
    "Киностудия": ["5.png"],
    "Лесопилка": ["6.png"],
    "Маленький миррор": ["7.png"],
    "Муравейник": ["8.png"],
    "Мусорка": ["9.png"],
    "Мясо": ["10.png"],
    "Нефть": ["11.png", "11_2.png"],
    "Палетка": ["12.png"],
    "Порт Биз": ["13.png"],
    "Сендик": ["14.png"],
    "Стройка": ["15.png"],
    "Татушка": ["16.png"],
}


def _vzp_photo_paths(map_name: str) -> list[Path]:
    base_dir = Path(__file__).resolve().parent / "foto_vzp"
    return [base_dir / fn for fn in VZP_MAP_FILE_MAP.get(map_name, [])]


def _build_vzp_embed() -> discord.Embed:
    maps_inline = " | ".join(VZP_MAP_FILE_MAP.keys())
    e = discord.Embed(
        title="Все карты VZP",
        description=f"> **{maps_inline}**\n\n> *Выбери карту:*",
        color=discord.Color.dark_gray(),
    )
    e.set_footer(text="VZP • Карты")
    return e


class VzpMapSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=name, value=name) for name in VZP_MAP_FILE_MAP.keys()]
        super().__init__(
            placeholder="Выбирай",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="vzp_map_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        # Быстро подтверждаем interaction, чтобы не ловить "Unknown interaction"
        # при чтении/загрузке файлов.
        try:
            await interaction.response.defer(ephemeral=True, thinking=False)
        except (discord.NotFound, discord.HTTPException):
            return

        map_name = self.values[0]
        paths = _vzp_photo_paths(map_name)
        missing = [str(p.name) for p in paths if not p.exists() or not p.is_file()]
        if missing:
            await interaction.followup.send(
                f"Не нашёл файлы для **{map_name}**: {', '.join(missing)}\nПроверь папку `foto_vzp`.",
                ephemeral=True,
            )
            return

        files = [discord.File(str(p), filename=p.name) for p in paths]
        await interaction.followup.send(
            content=map_name,
            files=files,
            ephemeral=True,
        )


class VzpMapView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(VzpMapSelect())


SHOP_PANEL_IMAGE_FILENAME = "magaz.png"
REPORT_PANEL_IMAGE_FILENAME = "otchet.png"
PORTFOLIO_PANEL_IMAGE_FILENAME = "archive.png"

DEFAULT_SHOP_ITEMS: list[tuple[str, int]] = [
    ("Снять ВАРН", 25),
    ("1.000 Majestic Coins", 100),
    ("100.000$", 100),
    ("1.000 Рублей", 200),
]

REPORT_TYPES: dict[str, dict[str, str | int]] = {
    "airdrop_screen": {"label": "Air Drop скрин", "desc": "Скрин — 1 коин", "reward": 1},
    "airdrop_otkat": {"label": "Air Drop откат", "desc": "Откат — 2 коина", "reward": 2},
    "ceha_screen": {"label": "Цеха/Дилеры скрин", "desc": "Скрин — 1 коин", "reward": 1},
    "ceha_otkat": {"label": "Цеха/Дилеры откат", "desc": "Откат — 2 коина", "reward": 2},
    "postavka_screen": {"label": "Поставка/Крафт скрин", "desc": "Скрин — 1 коин", "reward": 1},
}


MSK_TZ = dt.timezone(dt.timedelta(hours=3), name="MSK")


def _get_report_types_for_guild(guild_id: int) -> dict[str, dict[str, str | int]]:
    stored = get_report_types(guild_id=guild_id)
    if not stored:
        return dict(REPORT_TYPES)
    out: dict[str, dict[str, str | int]] = {}
    for item in stored:
        key = str(item.get("key", "")).strip().lower()
        label = str(item.get("label", "")).strip()
        desc = str(item.get("desc", "")).strip()
        try:
            reward = int(item.get("reward", 0))
        except (TypeError, ValueError):
            continue
        if key and label and reward > 0:
            out[key] = {"label": label, "desc": desc or f"{reward} коин(а)", "reward": reward}
    return out or dict(REPORT_TYPES)


class GiveawayState:
    def __init__(
        self,
        *,
        creator_id: int,
        creator_name: str,
        prize: str,
        channel_id: int,
        max_participants: int,
        winners_count: int,
        ends_at: dt.datetime,
    ):
        self.creator_id = int(creator_id)
        self.creator_name = str(creator_name)
        self.prize = str(prize)
        self.channel_id = int(channel_id)
        self.max_participants = int(max_participants)
        self.winners_count = int(winners_count)
        self.ends_at = ends_at
        self.participants: set[int] = set()
        self.finished = False
        self.winners: list[int] = []

    def to_payload(self) -> dict[str, object]:
        return {
            "creator_id": self.creator_id,
            "creator_name": self.creator_name,
            "prize": self.prize,
            "channel_id": self.channel_id,
            "max_participants": self.max_participants,
            "winners_count": self.winners_count,
            "ends_at_ts": int(self.ends_at.timestamp()),
            "participants": sorted(self.participants),
            "finished": self.finished,
            "winners": list(self.winners),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "GiveawayState | None":
        try:
            state = cls(
                creator_id=int(payload.get("creator_id", 0)),
                creator_name=str(payload.get("creator_name", "")),
                prize=str(payload.get("prize", "")),
                channel_id=int(payload.get("channel_id", 0)),
                max_participants=int(payload.get("max_participants", 0)),
                winners_count=int(payload.get("winners_count", 0)),
                ends_at=dt.datetime.fromtimestamp(int(payload.get("ends_at_ts", 0)), tz=MSK_TZ),
            )
        except (TypeError, ValueError, OSError):
            return None
        if state.creator_id <= 0 or state.channel_id <= 0:
            return None
        if not state.prize or state.max_participants <= 0 or state.winners_count <= 0:
            return None
        raw_participants = payload.get("participants", [])
        if isinstance(raw_participants, list):
            for uid in raw_participants:
                try:
                    state.participants.add(int(uid))
                except (TypeError, ValueError):
                    continue
        raw_winners = payload.get("winners", [])
        if isinstance(raw_winners, list):
            for uid in raw_winners:
                try:
                    state.winners.append(int(uid))
                except (TypeError, ValueError):
                    continue
        state.finished = bool(payload.get("finished", False))
        return state


GIVEAWAYS: dict[tuple[int, int], GiveawayState] = {}


def _giveaway_key(*, guild_id: int, message_id: int) -> tuple[int, int]:
    return int(guild_id), int(message_id)


def _persist_giveaway(*, guild_id: int, message_id: int, state: GiveawayState) -> None:
    key = _giveaway_key(guild_id=guild_id, message_id=message_id)
    GIVEAWAYS[key] = state
    set_giveaway_state(guild_id=guild_id, message_id=message_id, payload=state.to_payload())


def _load_giveaway(*, guild_id: int, message_id: int) -> GiveawayState | None:
    key = _giveaway_key(guild_id=guild_id, message_id=message_id)
    cached = GIVEAWAYS.get(key)
    if cached is not None:
        return cached
    payload = get_giveaway_states_for_guild(guild_id=guild_id).get(int(message_id))
    if not isinstance(payload, dict):
        return None
    loaded = GiveawayState.from_payload(payload)
    if loaded is not None:
        GIVEAWAYS[key] = loaded
    return loaded


def _parse_msk_datetime(raw: str) -> dt.datetime | None:
    text = (raw or "").strip()
    try:
        parsed = dt.datetime.strptime(text, "%d.%m.%Y %H:%M")
    except ValueError:
        return None
    return parsed.replace(tzinfo=MSK_TZ)


def _format_remaining(ends_at: dt.datetime) -> str:
    now = dt.datetime.now(MSK_TZ)
    if now >= ends_at:
        return "завершён"
    delta = ends_at - now
    total_minutes = int(delta.total_seconds() // 60)
    days = total_minutes // (24 * 60)
    hours = (total_minutes % (24 * 60)) // 60
    minutes = total_minutes % 60
    parts: list[str] = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if minutes or not parts:
        parts.append(f"{minutes}м")
    return "через " + " ".join(parts)


def _giveaway_participants_text(*, user_ids: set[int]) -> str:
    if not user_ids:
        return "—"
    lines: list[str] = [f"{idx}. <@{uid}>" for idx, uid in enumerate(sorted(user_ids), start=1)]
    joined = "\n".join(lines)
    if len(joined) <= 1024:
        return joined
    trimmed: list[str] = []
    for idx, uid in enumerate(sorted(user_ids), start=1):
        candidate = "\n".join(trimmed + [f"{idx}. <@{uid}>"])
        if len(candidate) > 980:
            break
        trimmed.append(f"{idx}. <@{uid}>")
    rest = len(user_ids) - len(trimmed)
    suffix = f"\n... и ещё {rest}" if rest > 0 else ""
    return "\n".join(trimmed) + suffix


def _build_giveaway_embed(*, state: GiveawayState) -> discord.Embed:
    participants_count = len(state.participants)
    end_text = f"{state.ends_at.strftime('%d.%m.%Y %H:%M')} МСК"
    status = "Завершён" if state.finished else "Открыт — жми **Участвовать**"
    e = discord.Embed(
        title="🎁 Розыгрыш",
        description=f"**На что розыгрыш**\n{state.prize}",
        color=discord.Color.dark_gray(),
        timestamp=dt.datetime.now(dt.timezone.utc),
    )
    e.add_field(name="Участники", value=f"{participants_count} / {state.max_participants}", inline=True)
    e.add_field(name="Победителей (слотов)", value=str(state.winners_count), inline=True)
    e.add_field(name="До какого (МСК в вводе)", value=f"{end_text}\n{_format_remaining(state.ends_at)}", inline=False)
    e.add_field(name="Список участников", value=_giveaway_participants_text(user_ids=state.participants), inline=False)
    e.add_field(name="Статус", value=status, inline=False)
    if state.winners:
        winners_text = "\n".join(f"{idx}. <@{uid}>" for idx, uid in enumerate(state.winners, start=1))
        e.add_field(name="Победители", value=winners_text, inline=False)
    e.set_footer(text=f"Организатор: {state.creator_name} • {state.creator_id}")
    return e


def _build_giveaway_started_dm_embed(*, state: GiveawayState, jump_url: str) -> discord.Embed:
    end_text = state.ends_at.strftime("%d.%m.%Y %H:%M")
    e = discord.Embed(
        title="🎁 Розыгрыш запущен",
        description=(
            "Твой розыгрыш успешно опубликован.\n\n"
            f"**На что розыгрыш**\n{state.prize}\n\n"
            f"**Победителей:** {state.winners_count}\n"
            f"**Лимит участников:** {state.max_participants}\n"
            f"**До какого:** {end_text} МСК\n\n"
            f"[Перейти к розыгрышу]({jump_url})"
        ),
        color=discord.Color.dark_gray(),
        timestamp=dt.datetime.now(dt.timezone.utc),
    )
    e.set_footer(text="Спортсмены • Уведомление о старте")
    return e


def _build_giveaway_role_dm_embed(
    *,
    guild: discord.Guild,
    role: discord.Role,
    giveaway_message: discord.Message,
    state: GiveawayState,
    author: discord.abc.User,
) -> discord.Embed:
    end_text = state.ends_at.strftime("%d.%m.%Y %H:%M")
    e = discord.Embed(
        title="🎁 Стартовал новый розыгрыш",
        description=(
            f"Ты получил уведомление по роли {role.mention}.\n\n"
            f"**Сервер:** {guild.name}\n"
            f"**Канал:** {giveaway_message.channel.mention}\n"
            f"**Кто запустил:** {author.mention}\n\n"
            f"**Приз:** {state.prize}\n"
            f"**Победителей:** {state.winners_count}\n"
            f"**До какого:** {end_text} МСК\n\n"
            f"[Перейти к розыгрышу]({giveaway_message.jump_url})"
        ),
        color=discord.Color.dark_gray(),
        timestamp=dt.datetime.now(dt.timezone.utc),
    )
    if guild.icon:
        e.set_thumbnail(url=guild.icon.url)
    e.set_footer(text="Спортсмены • Уведомление о старте")
    return e


class GiveawayView(discord.ui.View):
    def __init__(self, *, disabled: bool = False):
        super().__init__(timeout=None)
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = disabled

    @discord.ui.button(label="Участвовать", style=discord.ButtonStyle.success, custom_id="giveaway_join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        state = _load_giveaway(guild_id=interaction.guild.id, message_id=interaction.message.id)
        if state is None:
            await interaction.response.send_message("Данные розыгрыша не найдены. Создай новый розыгрыш.", ephemeral=True)
            return
        if state.finished:
            await interaction.response.send_message("Розыгрыш уже завершён.", ephemeral=True)
            return
        if dt.datetime.now(MSK_TZ) >= state.ends_at:
            await interaction.response.send_message("Время розыгрыша уже вышло.", ephemeral=True)
            return
        if interaction.user.id == state.creator_id:
            await interaction.response.send_message("Организатор не участвует в своём розыгрыше.", ephemeral=True)
            return
        if interaction.user.id in state.participants:
            await interaction.response.send_message("Ты уже участвуешь.", ephemeral=True)
            return
        if len(state.participants) >= state.max_participants:
            await interaction.response.send_message("Лимит участников уже достигнут.", ephemeral=True)
            return

        state.participants.add(interaction.user.id)
        _persist_giveaway(guild_id=interaction.guild.id, message_id=interaction.message.id, state=state)
        await interaction.message.edit(embed=_build_giveaway_embed(state=state), view=GiveawayView())
        await interaction.response.send_message("Ты добавлен в список участников.", ephemeral=True)

    @discord.ui.button(label="Разыграть", style=discord.ButtonStyle.danger, custom_id="giveaway_draw")
    async def draw(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        state = _load_giveaway(guild_id=interaction.guild.id, message_id=interaction.message.id)
        if state is None:
            await interaction.response.send_message("Данные розыгрыша не найдены. Создай новый розыгрыш.", ephemeral=True)
            return
        if interaction.user.id != state.creator_id:
            await interaction.response.send_message("Разыграть может только создатель розыгрыша.", ephemeral=True)
            return
        if state.finished:
            await interaction.response.send_message("Этот розыгрыш уже завершён.", ephemeral=True)
            return

        eligible = [uid for uid in state.participants if uid != state.creator_id]
        if not eligible:
            await interaction.response.send_message("Нет участников для выбора победителей.", ephemeral=True)
            return

        winners_to_pick = min(state.winners_count, len(eligible))
        state.winners = random.sample(eligible, k=winners_to_pick)
        state.finished = True
        _persist_giveaway(guild_id=interaction.guild.id, message_id=interaction.message.id, state=state)

        await interaction.message.edit(embed=_build_giveaway_embed(state=state), view=GiveawayView(disabled=True))
        await interaction.response.send_message("Розыгрыш завершён. Победители выбраны.", ephemeral=True)


class GiveawayCreateModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Новый розыгрыш")
        self.prize = discord.ui.TextInput(
            label="1. На что розыгрыш",
            placeholder="Например: подписка Nitro",
            max_length=200,
            required=True,
        )
        self.max_participants = discord.ui.TextInput(
            label="2. Макс. участников (число)",
            placeholder="50",
            max_length=4,
            required=True,
        )
        self.winners_count = discord.ui.TextInput(
            label="3. Сколько победителей",
            placeholder="1",
            max_length=3,
            required=True,
        )
        self.until_msk = discord.ui.TextInput(
            label="4. До какого (МСК)",
            placeholder="05.04.2026 21:30",
            max_length=16,
            required=True,
        )
        self.add_item(self.prize)
        self.add_item(self.max_participants)
        self.add_item(self.winners_count)
        self.add_item(self.until_msk)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Команда доступна только в текстовом канале сервера.", ephemeral=True)
            return

        try:
            max_participants = int(str(self.max_participants.value).strip())
            winners_count = int(str(self.winners_count.value).strip())
        except ValueError:
            await interaction.response.send_message("Поля участников и победителей должны быть числами.", ephemeral=True)
            return

        if max_participants < 1 or max_participants > 500:
            await interaction.response.send_message("Макс. участников должен быть в диапазоне 1..500.", ephemeral=True)
            return
        if winners_count < 1:
            await interaction.response.send_message("Количество победителей должно быть не меньше 1.", ephemeral=True)
            return
        if winners_count > max_participants:
            await interaction.response.send_message("Победителей не может быть больше, чем макс. участников.", ephemeral=True)
            return

        ends_at = _parse_msk_datetime(str(self.until_msk.value))
        if ends_at is None:
            await interaction.response.send_message("Неверный формат даты. Используй `ДД.ММ.ГГГГ ЧЧ:ММ`.", ephemeral=True)
            return
        if ends_at <= dt.datetime.now(MSK_TZ):
            await interaction.response.send_message("Дата завершения должна быть в будущем.", ephemeral=True)
            return

        # Ниже может занять заметное время (пост в канал + рассылка DM по ролям),
        # поэтому подтверждаем interaction заранее, чтобы он не протух (Unknown interaction).
        await interaction.response.defer(ephemeral=True, thinking=False)

        state = GiveawayState(
            creator_id=interaction.user.id,
            creator_name=interaction.user.display_name,
            prize=str(self.prize.value).strip(),
            channel_id=interaction.channel.id,
            max_participants=max_participants,
            winners_count=winners_count,
            ends_at=ends_at,
        )
        notify_role_ids = get_giveaway_notify_role_ids(guild_id=interaction.guild.id)
        mentions: list[str] = []
        notify_roles: list[discord.Role] = []
        for rid in notify_role_ids:
            role = interaction.guild.get_role(int(rid))
            if role is None:
                continue
            mentions.append(role.mention)
            notify_roles.append(role)

        content = " ".join(mentions) if mentions else None
        msg = await interaction.channel.send(
            content=content,
            embed=_build_giveaway_embed(state=state),
            view=GiveawayView(),
            allowed_mentions=discord.AllowedMentions(roles=True, users=False, everyone=False),
        )
        _persist_giveaway(guild_id=interaction.guild.id, message_id=msg.id, state=state)
        try:
            await interaction.user.send(
                embed=_build_giveaway_started_dm_embed(
                    state=state,
                    jump_url=msg.jump_url,
                )
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

        if notify_roles:
            dm_targets: dict[int, discord.Member] = {}
            for role in notify_roles:
                for member in role.members:
                    if member.bot or member.id == interaction.user.id:
                        continue
                    dm_targets[member.id] = member
            for member in dm_targets.values():
                dm_embed = _build_giveaway_role_dm_embed(
                    guild=interaction.guild,
                    role=next((r for r in notify_roles if r in member.roles), notify_roles[0]),
                    giveaway_message=msg,
                    state=state,
                    author=interaction.user,
                )
                try:
                    await member.send(embed=dm_embed)
                except (discord.Forbidden, discord.HTTPException):
                    pass
        await interaction.followup.send(f"Розыгрыш создан: {msg.jump_url}", ephemeral=True)


def _shop_image_file() -> discord.File | None:
    p = Path(__file__).resolve().parent / "foto" / SHOP_PANEL_IMAGE_FILENAME
    if p.exists() and p.is_file():
        return discord.File(str(p), filename=SHOP_PANEL_IMAGE_FILENAME)
    return None


def _report_image_file() -> discord.File | None:
    p = Path(__file__).resolve().parent / "foto" / REPORT_PANEL_IMAGE_FILENAME
    if p.exists() and p.is_file():
        return discord.File(str(p), filename=REPORT_PANEL_IMAGE_FILENAME)
    return None


def _portfolio_image_file() -> discord.File | None:
    p = Path(__file__).resolve().parent / "foto" / PORTFOLIO_PANEL_IMAGE_FILENAME
    if p.exists() and p.is_file():
        return discord.File(str(p), filename=PORTFOLIO_PANEL_IMAGE_FILENAME)
    return None


def _build_shop_embed(*, with_image: bool = False) -> discord.Embed:
    # Как на нужном скрине магазина: один embed-блок, картинка внутри embed.
    items_lines = "\n\n".join(
        f"**{name} - {price}** <:coin:1369487243715264542>"
        for name, price in DEFAULT_SHOP_ITEMS
    )
    e = discord.Embed(
        description=(
            "— ・ **Магазин товаров**\n\n"
            "• Используйте выпадающий список ниже для выбора товара\n\n"
            "• **Доступные товары:**\n\n"
            f"{items_lines}"
        ),
        color=discord.Color.dark_gray(),
    )
    if with_image:
        e.set_image(url=f"attachment://{SHOP_PANEL_IMAGE_FILENAME}")
    e.set_footer(text="Баланс обновляется автоматически после мероприятий и активности")
    return e


def _get_shop_items_for_guild(guild_id: int) -> list[tuple[str, int]]:
    raw = get_shop_items(guild_id=guild_id)
    if raw:
        return [(str(x["name"]), int(x["price"])) for x in raw]
    return list(DEFAULT_SHOP_ITEMS)


def _build_shop_embed_for_guild(*, guild_id: int, with_image: bool = False) -> discord.Embed:
    items = _get_shop_items_for_guild(guild_id)
    items_lines = "\n\n".join(f"**{name} - {price}** <:coin:1369487243715264542>" for name, price in items)
    e = discord.Embed(
        description=(
            "— ・ **Магазин товаров**\n\n"
            "• Используйте выпадающий список ниже для выбора товара\n\n"
            "• **Доступные товары:**\n\n"
            f"{items_lines}"
        ),
        color=discord.Color.dark_gray(),
    )
    if with_image:
        e.set_image(url=f"attachment://{SHOP_PANEL_IMAGE_FILENAME}")
    e.set_footer(text="Баланс обновляется автоматически после мероприятий и активности")
    return e


async def _refresh_shop_panel_message(*, guild: discord.Guild) -> bool:
    existing = get_shop_panel_message_id(guild_id=guild.id)
    if not existing:
        return False

    channel_id, message_id = existing
    channel = guild.get_channel(channel_id)
    if channel is None:
        try:
            channel = await guild.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False
    if not isinstance(channel, discord.TextChannel):
        return False

    try:
        panel_msg = await channel.fetch_message(message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False

    embed = _build_shop_embed_for_guild(guild_id=guild.id, with_image=False)
    try:
        await panel_msg.edit(embed=embed, view=ShopPanelView(guild_id=guild.id))
    except (discord.Forbidden, discord.HTTPException):
        return False
    return True


async def _refresh_reports_panel_message(*, guild: discord.Guild) -> bool:
    existing = get_reports_panel_message_id(guild_id=guild.id)
    if not existing:
        return False

    channel_id, message_id = existing
    channel = guild.get_channel(channel_id)
    if channel is None:
        try:
            channel = await guild.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False
    if not isinstance(channel, discord.TextChannel):
        return False

    try:
        panel_msg = await channel.fetch_message(message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False

    embed = _build_report_embed(guild_id=guild.id, with_image=False)
    try:
        await panel_msg.edit(embed=embed, view=ReportPanelView(guild_id=guild.id))
    except (discord.Forbidden, discord.HTTPException):
        return False
    return True


def _build_report_embed(*, guild_id: int, with_image: bool = False) -> discord.Embed:
    # Один цельный embed-блок: картинка + текст (как единая "семья").
    e = discord.Embed(
        description=(
            "— ・ **Отчёт о проделанной работе**\n\n"
            "• Выберите тип отчёта из списка ниже. После выбора укажите ссылку на отчёт в модальном окне.\n\n"
            "• Отчёт будет считаться подлинным, если он был отправлен в течение **48 часов**\n\n"
            "• Ссылка должна вести только на 1 отчёт.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "• **Выберите тип отчёта**"
        ),
        color=discord.Color.dark_gray(),
    )
    if with_image:
        e.set_image(url=f"attachment://{REPORT_PANEL_IMAGE_FILENAME}")
    return e


def _build_portfolio_embed(*, with_image: bool = False) -> discord.Embed:
    e = discord.Embed(
        description=(
            "🗂️ **Создание портфеля**\n\n"
            "• В привязанном канале личным слотом оценят ваши откаты и решат — повысить вам ранг или порекомендовать "
            "дополнительную тренировку, указав на допущенные ошибки.\n\n"
            "• В вашем канале также идёт рассмотрение вашего Tier, решение принимают уполномоченные роли.\n\n"
            "• Видеоматериалы желательно заливать на видеохостинги YouTube, Rutube.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "**Создай личный канал → прикрепи откаты → High решит твой Ранг**"
        ),
        color=discord.Color.dark_gray(),
    )
    if with_image:
        e.set_image(url=f"attachment://{PORTFOLIO_PANEL_IMAGE_FILENAME}")
    return e


def _safe_text_channel_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^\w\-]+", "-", name, flags=re.UNICODE)
    name = re.sub(r"_{1,}", "-", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name[:70] or "user"


def _build_portfolio_channel_embed(*, member: discord.Member) -> discord.Embed:
    profile = get_portfolio_profile(guild_id=member.guild.id, user_id=member.id)
    try:
        rank_num = int(profile.get("rank") or 0)
    except (TypeError, ValueError):
        rank_num = 0
    try:
        tier_num = int(profile.get("tier") or 0)
    except (TypeError, ValueError):
        tier_num = 0

    rank_rid = get_rank_role_id(guild_id=member.guild.id, rank=rank_num) if rank_num else None
    tier_rid = get_tier_role_id(guild_id=member.guild.id, tier=tier_num) if tier_num else None

    rank_text = f"<@&{rank_rid}>" if rank_rid else "Нет ранга"
    tier_text = f"<@&{tier_rid}>" if tier_rid else "Нет тира"
    e = discord.Embed(
        description=(
            "## ▰▰ Личные текстовые каналы участника\n\n"
            f"Личный канал участника — {member.mention} | {member.id}\n\n"
            "—\n"
            "▸ Присылайте в текстовый канал видео откатов с МП(желательно геймплей\n"
            "от 10 минут со слышным лобби).\n"
            "▸ Изучайте записи, это важно для участия в мейн-составе на каптах.\n"
            "▸ Ссылка на карту залазов\n"
            "▸ Пожалуйста, прикрепляйте откаты с лучшей стрельбой и демонстрацией\n"
            "понимания игры.\n\n"
            "**Текущий Ранг:**\n"
            f"{rank_text}\n\n"
            "**Текущий Тир:**\n"
            f"{tier_text}"
        ),
        color=discord.Color.dark_gray(),
    )
    return e


class PortfolioChannelActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Взаимодействие с каналом",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Удалить канал", value="delete"),
                discord.SelectOption(label="Повышение ранга", value="rank_up"),
                discord.SelectOption(label="Понижение ранга", value="rank_down"),
            ],
            custom_id="portfolio_channel_action_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Команда доступна только в текстовом канале.", ephemeral=True)
            return

        is_admin = interaction.user.guild_permissions.administrator
        allowed_role_ids = set(get_ticket_view_role_ids(guild_id=interaction.guild.id))
        has_role = any(r.id in allowed_role_ids for r in interaction.user.roles)
        if not (is_admin or has_role):
            await interaction.response.send_message("Нет прав.", ephemeral=True)
            return

        owner_id = get_portfolio_channel_owner_id(guild_id=interaction.guild.id, channel_id=interaction.channel.id)
        if not owner_id:
            await interaction.response.send_message("Это не личный архив-канал.", ephemeral=True)
            return

        owner = interaction.guild.get_member(owner_id)
        if owner is None:
            try:
                owner = await interaction.guild.fetch_member(owner_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                owner = None
        if owner is None:
            await interaction.response.send_message("Не смог найти владельца канала.", ephemeral=True)
            return

        action = self.values[0]
        if action == "delete":
            await interaction.response.send_message("Канал удалится через 3 секунды.", ephemeral=True)
            try:
                await asyncio.sleep(3)
                await interaction.channel.delete(reason="Удалено через меню архива")
            except Exception:
                pass
            return

        prof = get_portfolio_profile(guild_id=interaction.guild.id, user_id=owner.id)
        try:
            current_rank = int(prof.get("rank") or 0)
        except (TypeError, ValueError):
            current_rank = 0
        if current_rank <= 0:
            current_rank = 1

        if action == "rank_up":
            new_rank = min(2, current_rank + 1)
        elif action == "rank_down":
            new_rank = max(1, current_rank - 1)
        else:
            await interaction.response.send_message("Неизвестное действие.", ephemeral=True)
            return

        rid = get_rank_role_id(guild_id=interaction.guild.id, rank=new_rank)
        role_result: str | None = None
        if rid:
            role = interaction.guild.get_role(rid)
            if role is None:
                role_result = "роль ранга не найдена (удалена?)"
            else:
                bot_member = interaction.guild.me
                if bot_member is None:
                    role_result = "не смог определить права бота"
                else:
                    if not bot_member.guild_permissions.manage_roles:
                        role_result = "боту не хватает права **Manage Roles**"
                    elif role >= bot_member.top_role:
                        role_result = "роль выше/равна роли бота (подними роль бота выше)"
                    else:
                        to_remove: list[discord.Role] = []
                        for rnk in (1, 2):
                            rr = get_rank_role_id(guild_id=interaction.guild.id, rank=rnk)
                            if not rr or rr == rid:
                                continue
                            r_obj = interaction.guild.get_role(rr)
                            if r_obj and r_obj in owner.roles and r_obj < bot_member.top_role:
                                to_remove.append(r_obj)
                        try:
                            if to_remove:
                                await owner.remove_roles(*to_remove, reason="Смена ранга")
                            if role not in owner.roles:
                                await owner.add_roles(role, reason=f"Смена ранга на {new_rank}")
                            role_result = f"роль выдана: {role.mention}"
                        except discord.Forbidden:
                            role_result = "нет прав выдать/снять роль (иерархия/права)"
                        except discord.HTTPException:
                            role_result = "ошибка Discord при выдаче роли"

        prof["rank"] = int(new_rank)
        set_portfolio_profile(guild_id=interaction.guild.id, user_id=owner.id, profile=prof)

        if interaction.message is not None:
            try:
                await interaction.message.edit(embed=_build_portfolio_channel_embed(member=owner), view=PortfolioChannelView())
            except (discord.Forbidden, discord.HTTPException):
                pass

        extra = f"\nРоль: {role_result}" if role_result else ""
        await interaction.response.send_message(f"Ранг обновлён: **{new_rank}** для {owner.mention}.{extra}", ephemeral=True)


class PortfolioTierSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Выдача тира",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Выдать Тир 1", value="tier_1"),
                discord.SelectOption(label="Выдать Тир 2", value="tier_2"),
                discord.SelectOption(label="Выдать Тир 3", value="tier_3"),
            ],
            custom_id="portfolio_channel_tier_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        is_admin = interaction.user.guild_permissions.administrator
        allowed_role_ids = set(get_ticket_view_role_ids(guild_id=interaction.guild.id))
        has_role = any(r.id in allowed_role_ids for r in interaction.user.roles)
        if not (is_admin or has_role):
            await interaction.response.send_message("Нет прав выдавать тир.", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Команда доступна только в текстовом канале.", ephemeral=True)
            return

        owner_id = get_portfolio_channel_owner_id(guild_id=interaction.guild.id, channel_id=interaction.channel.id)
        if not owner_id:
            await interaction.response.send_message("Это не личный архив-канал (нет привязки владельца).", ephemeral=True)
            return

        owner = interaction.guild.get_member(owner_id)
        if owner is None:
            try:
                owner = await interaction.guild.fetch_member(owner_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                owner = None
        if owner is None:
            await interaction.response.send_message("Не смог найти владельца канала на сервере.", ephemeral=True)
            return

        tier_value = {"tier_1": "Тир 1", "tier_2": "Тир 2", "tier_3": "Тир 3"}.get(self.values[0])
        if tier_value is None:
            await interaction.response.send_message("Неизвестный тир.", ephemeral=True)
            return

        tier_num = {"tier_1": 1, "tier_2": 2, "tier_3": 3}.get(self.values[0], 0)
        rid = get_tier_role_id(guild_id=interaction.guild.id, tier=tier_num) if tier_num else None
        role_result: str | None = None

        # Выдача роли по привязке (если настроено)
        if rid:
            role = interaction.guild.get_role(rid)
            if role is None:
                role_result = "роль тира не найдена (удалена?)"
            else:
                bot_member = interaction.guild.me
                if bot_member is None:
                    role_result = "не смог определить права бота"
                else:
                    if not bot_member.guild_permissions.manage_roles:
                        role_result = "боту не хватает права **Manage Roles**"
                    elif role >= bot_member.top_role:
                        role_result = "роль выше/равна роли бота (подними роль бота выше)"
                    else:
                        # Снимаем роли других тиров (если они привязаны) и выдаём выбранную
                        to_remove: list[discord.Role] = []
                        for t in (1, 2, 3):
                            tr = get_tier_role_id(guild_id=interaction.guild.id, tier=t)
                            if not tr or tr == rid:
                                continue
                            r_obj = interaction.guild.get_role(tr)
                            if r_obj and r_obj in owner.roles and r_obj < bot_member.top_role:
                                to_remove.append(r_obj)
                        try:
                            if to_remove:
                                await owner.remove_roles(*to_remove, reason="Смена тира")
                            if role not in owner.roles:
                                await owner.add_roles(role, reason=f"Выдача {tier_value}")
                            role_result = f"роль выдана: {role.mention}"
                        except discord.Forbidden:
                            role_result = "нет прав выдать/снять роль (иерархия/права)"
                        except discord.HTTPException:
                            role_result = "ошибка Discord при выдаче роли"

        prof = get_portfolio_profile(guild_id=interaction.guild.id, user_id=owner.id)
        prof["tier"] = int(tier_num)
        set_portfolio_profile(guild_id=interaction.guild.id, user_id=owner.id, profile=prof)

        if interaction.message is not None:
            try:
                await interaction.message.edit(embed=_build_portfolio_channel_embed(member=owner), view=PortfolioChannelView())
            except (discord.Forbidden, discord.HTTPException):
                pass

        extra = f"\nРоль: {role_result}" if role_result else ""
        await interaction.response.send_message(f"Выдано: **{tier_value}** для {owner.mention}.{extra}", ephemeral=True)


@bot.tree.command(name="настройка-роль-тир", description="Привязать роли для Тир 1/2/3")
@app_commands.describe(
    действие="Что сделать (установить/очистить/показать)",
    тир="Какой тир (1/2/3)",
    роль="Роль (нужно только для 'установить')",
)
@app_commands.default_permissions(administrator=True)
@app_commands.choices(
    действие=[
        app_commands.Choice(name="установить", value="set"),
        app_commands.Choice(name="очистить", value="clear"),
        app_commands.Choice(name="показать", value="show"),
    ],
    тир=[
        app_commands.Choice(name="Тир 1", value="1"),
        app_commands.Choice(name="Тир 2", value="2"),
        app_commands.Choice(name="Тир 3", value="3"),
    ],
)
async def configure_tier_roles(
    interaction: discord.Interaction,
    действие: app_commands.Choice[str],
    тир: app_commands.Choice[str],
    роль: discord.Role | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    tier_num = int(тир.value)

    if действие.value == "show":
        rid = get_tier_role_id(guild_id=interaction.guild.id, tier=tier_num)
        pretty = f"<@&{rid}>" if rid else "—"
        await interaction.response.send_message(f"Роль для {тир.name}: {pretty}", ephemeral=True)
        return

    if действие.value == "clear":
        set_tier_role_id(guild_id=interaction.guild.id, tier=tier_num, role_id=None)
        await interaction.response.send_message(f"Готово. Роль для {тир.name} очищена.", ephemeral=True)
        return

    if действие.value == "set":
        if роль is None:
            await interaction.response.send_message("Выбери роль в параметре `роль`.", ephemeral=True)
            return
        set_tier_role_id(guild_id=interaction.guild.id, tier=tier_num, role_id=роль.id)
        await interaction.response.send_message(f"Готово. Для {тир.name} привязана роль {роль.mention}.", ephemeral=True)
        return

    await interaction.response.send_message("Неизвестное действие.", ephemeral=True)


@bot.tree.command(name="настройка-роль-ранг", description="Привязать роли для Ранг 1/2 (для повышения/понижения)")
@app_commands.describe(
    действие="Что сделать (установить/очистить/показать)",
    ранг="Какой ранг (1/2)",
    роль="Роль (нужно только для 'установить')",
)
@app_commands.default_permissions(administrator=True)
@app_commands.choices(
    действие=[
        app_commands.Choice(name="установить", value="set"),
        app_commands.Choice(name="очистить", value="clear"),
        app_commands.Choice(name="показать", value="show"),
    ],
    ранг=[
        app_commands.Choice(name="Ранг 1", value="1"),
        app_commands.Choice(name="Ранг 2", value="2"),
    ],
)
async def configure_rank_roles(
    interaction: discord.Interaction,
    действие: app_commands.Choice[str],
    ранг: app_commands.Choice[str],
    роль: discord.Role | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    rank_num = int(ранг.value)

    if действие.value == "show":
        rid = get_rank_role_id(guild_id=interaction.guild.id, rank=rank_num)
        pretty = f"<@&{rid}>" if rid else "—"
        await interaction.response.send_message(f"Роль для {ранг.name}: {pretty}", ephemeral=True)
        return

    if действие.value == "clear":
        set_rank_role_id(guild_id=interaction.guild.id, rank=rank_num, role_id=None)
        await interaction.response.send_message(f"Готово. Роль для {ранг.name} очищена.", ephemeral=True)
        return

    if действие.value == "set":
        if роль is None:
            await interaction.response.send_message("Выбери роль в параметре `роль`.", ephemeral=True)
            return
        set_rank_role_id(guild_id=interaction.guild.id, rank=rank_num, role_id=роль.id)
        await interaction.response.send_message(f"Готово. Для {ранг.name} привязана роль {роль.mention}.", ephemeral=True)
        return

    await interaction.response.send_message("Неизвестное действие.", ephemeral=True)


class PortfolioChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(PortfolioChannelActionSelect())
        self.add_item(PortfolioTierSelect())


class PortfolioSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Выберите действие",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Повысить Ранг (создать личный канал)",
                    value="create_channel",
                )
            ],
            custom_id="portfolio_panel_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        # Создание канала/веток может занять >3s, поэтому сразу подтверждаем interaction.
        try:
            await interaction.response.defer(ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            return

        guild = interaction.guild
        user = interaction.user

        category = None
        bound_category_id = get_portfolio_category_id(guild_id=guild.id)
        if bound_category_id:
            category = guild.get_channel(bound_category_id)
            if category is None:
                try:
                    category = await guild.fetch_channel(bound_category_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    category = None
        if not isinstance(category, discord.CategoryChannel):
            await interaction.followup.send(
                "Категория для портфелей не настроена. Администрации нужно сделать `/привязка-категория-портфелей`.",
                ephemeral=True,
            )
            return

        base = _safe_text_channel_name(user.display_name)
        ch_name = f"archiv-{base}"[:100]

        # Права: архив видит только создатель + заданные роли + админы (Administrator обходит оверрайды).
        # Важно: глушим "протекание" прав из категории — если у роли есть доступ к категории,
        # но она не в списке разрешённых, то явно запрещаем ей view_channel в канале.
        allowed_roles: list[discord.Role] = []
        for rid in get_ticket_view_role_ids(guild_id=guild.id):
            role = guild.get_role(rid)
            if role is not None:
                allowed_roles.append(role)

        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),  # type: ignore[arg-type]
        }
        for role in allowed_roles:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, read_message_history=True)

        # Запретим всем ролям/юзерам из оверрайтов категории, кроме разрешённых.
        allowed_keys: set[int] = {guild.default_role.id, user.id}
        allowed_keys.update(r.id for r in allowed_roles)
        if guild.me is not None:
            allowed_keys.add(guild.me.id)
        for target in category.overwrites.keys():
            try:
                tid = target.id  # type: ignore[attr-defined]
            except Exception:
                continue
            if tid in allowed_keys:
                continue
            # Явно скрываем канал от ролей/пользователей, которые могли видеть категорию.
            overwrites[target] = discord.PermissionOverwrite(view_channel=False)

        try:
            ch = await guild.create_text_channel(
                name=ch_name,
                category=category,
                overwrites=overwrites,
                reason="Создание личного канала портфеля",
            )
        except discord.Forbidden:
            await interaction.followup.send("Нет прав создавать каналы.", ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.followup.send("Не смог создать канал (ошибка Discord).", ephemeral=True)
            return

        # Сразу отправляем оформление канала (как на скрине) + создаём ветки.
        set_portfolio_channel_owner_id(guild_id=guild.id, channel_id=ch.id, owner_id=user.id)
        try:
            await ch.send(embed=_build_portfolio_channel_embed(member=user), view=PortfolioChannelView())
        except (discord.Forbidden, discord.HTTPException):
            pass

        # Ветки/треды (best-effort): если не получится — просто пропускаем.
        for thread_name in ("Рп мероприятия", "Капт/мкл", "Арена(гг)"):
            try:
                # auto_archive_duration: 1440 = 24h
                await ch.create_thread(name=thread_name, type=discord.ChannelType.public_thread, auto_archive_duration=1440)
            except Exception:
                pass

        await interaction.followup.send(f"Канал создан: {ch.mention}", ephemeral=True)

        # Сбрасываем выбор в селекте, чтобы пункт можно было выбирать многократно подряд.
        if interaction.message is not None:
            try:
                await interaction.message.edit(view=PortfolioPanelView())
            except (discord.Forbidden, discord.HTTPException):
                pass


class PortfolioPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(PortfolioSelect())


def _build_report_sent_embed(*, with_image: bool = False) -> discord.Embed:
    e = discord.Embed(
        description=(
            "— ・ **Готово**\n\n"
            "Отчёт отправлен на проверку. Ожидайте оповещение о результате в ЛС от бота."
        ),
        color=discord.Color.dark_gray(),
    )
    if with_image:
        e.set_image(url=f"attachment://{REPORT_PANEL_IMAGE_FILENAME}")
    return e


def _build_report_verdict_embed(
    *,
    guild: discord.Guild,
    admin: discord.Member,
    approved: bool,
    reason: str | None = None,
    reward: int | None = None,
    balance: float | None = None,
) -> discord.Embed:
    if approved:
        desc = "Ваш отчёт был **одобрен**!\nПоздравляем!"
        if reward is not None:
            desc += f"\n\n**Начислено:** {reward} коин(а)"
        if balance is not None:
            desc += f"\n**Баланс:** {_fmt_points(balance)}"
    else:
        desc = "Ваш отчёт был **отклонён**."
        if reason:
            desc += f"\n\n**Причина:** {reason}"

    e = discord.Embed(
        title="— ・ Вердикт по отчёту",
        description=f"{desc}\n\n**Администратор:**\n{admin.mention} | {admin.display_name} | {admin.id}",
        color=discord.Color.dark_gray(),
        timestamp=dt.datetime.now(dt.timezone.utc),
    )
    if guild.icon:
        e.set_thumbnail(url=guild.icon.url)
    e.set_footer(text=dt.datetime.now().strftime("%d.%m.%Y %H:%M"))
    return e


def _fmt_points(value: float) -> str:
    return f"{value:.2f}"


def _build_shop_order_sent_embed() -> discord.Embed:
    return discord.Embed(
        description="— ・ **Готово**\n\nЗаявка на покупку отправлена на проверку. Ожидайте результат в ЛС от бота.",
        color=discord.Color.dark_gray(),
    )


def _build_shop_order_verdict_embed(
    *,
    guild: discord.Guild,
    admin: discord.Member,
    approved: bool,
    item_name: str,
    price: int,
    reason: str | None = None,
    balance: float | None = None,
) -> discord.Embed:
    if approved:
        desc = f"Ваша покупка **{item_name}** была **одобрена**!"
        desc += f"\n\n**Списано:** {price} баллов"
        if balance is not None:
            desc += f"\n**Баланс:** {_fmt_points(balance)}"
    else:
        desc = f"Ваша покупка **{item_name}** была **отклонена**."
        if reason:
            desc += f"\n\n**Причина:** {reason}"

    e = discord.Embed(
        title="— ・ Вердикт по покупке",
        description=f"{desc}\n\n**Администратор:**\n{admin.mention} | {admin.display_name} | {admin.id}",
        color=discord.Color.dark_gray(),
        timestamp=dt.datetime.now(dt.timezone.utc),
    )
    if guild.icon:
        e.set_thumbnail(url=guild.icon.url)
    e.set_footer(text=dt.datetime.now().strftime("%d.%m.%Y %H:%M"))
    return e


class ShopSelect(discord.ui.Select):
    def __init__(self, *, guild_id: int):
        self.guild_id = guild_id
        shop_items = _get_shop_items_for_guild(guild_id)
        options = [
            discord.SelectOption(label=f"{name} — {price}", value=name)
            for name, price in shop_items[:25]
        ]
        super().__init__(
            placeholder="Выберите товар для покупки",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="shop_panel_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        review_channel_id = get_shop_orders_channel_id(guild_id=interaction.guild.id)
        if not review_channel_id:
            await interaction.response.send_message(
                "Покупки через магазин не настроены. Администрации нужно сделать `/привязка-магазина`.",
                ephemeral=True,
            )
            if interaction.message is not None:
                try:
                    await interaction.message.edit(view=ShopPanelView(guild_id=interaction.guild.id))
                except (discord.Forbidden, discord.HTTPException):
                    pass
            return

        review_channel = interaction.guild.get_channel(review_channel_id)
        if review_channel is None:
            try:
                review_channel = await interaction.guild.fetch_channel(review_channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                review_channel = None
        if not isinstance(review_channel, discord.TextChannel):
            await interaction.response.send_message(
                "Не удалось найти канал проверки магазина. Обратитесь к администрации.",
                ephemeral=True,
            )
            return

        item_name = self.values[0]
        price_map = {name: price for name, price in _get_shop_items_for_guild(interaction.guild.id)}
        price = float(price_map.get(item_name, 0))
        if price <= 0:
            await interaction.response.send_message("Этот товар больше недоступен. Обновите панель магазина.", ephemeral=True)
            return
        balance = get_user_points(guild_id=interaction.guild.id, user_id=interaction.user.id)
        if balance < price:
            await interaction.response.send_message(
                f"Недостаточно баллов! Ваш баланс: {_fmt_points(balance)}/{int(price)}",
                ephemeral=True,
            )
            if interaction.message is not None:
                try:
                    await interaction.message.edit(view=ShopPanelView(guild_id=interaction.guild.id))
                except (discord.Forbidden, discord.HTTPException):
                    pass
            return

        # Списываем сразу при покупке (резерв). Если заявку отклонят — вернём.
        balance_after = add_user_points(
            guild_id=interaction.guild.id,
            user_id=interaction.user.id,
            delta=-float(price),
        )

        review_embed = discord.Embed(
            title="— ・ Заявка на покупку",
            description=(
                f"**Пользователь:** {interaction.user.mention}\n"
                f"**Товар:** {item_name}\n"
                f"**Цена:** {int(price)} баллов\n"
                f"**Баланс:** {_fmt_points(balance)} → {_fmt_points(balance_after)}"
            ),
            color=discord.Color.dark_gray(),
            timestamp=dt.datetime.now(dt.timezone.utc),
        )
        review_embed.add_field(name="Статус", value="**⏳ На проверке**", inline=False)
        review_embed.add_field(name="ID пользователя", value=str(interaction.user.id), inline=False)
        review_embed.add_field(name="Товар", value=item_name, inline=False)
        review_embed.add_field(name="Цена", value=str(int(price)), inline=False)
        review_embed.set_footer(text="shop_order")

        review_msg = await review_channel.send(embed=review_embed, view=ShopOrderReviewView())
        add_pending_shop_order(
            guild_id=interaction.guild.id,
            user_id=interaction.user.id,
            review_message_id=review_msg.id,
            item_name=item_name,
            price=float(price),
            created_ts=int(dt.datetime.now(dt.timezone.utc).timestamp()),
            debited=True,
        )

        await interaction.response.send_message(embed=_build_shop_order_sent_embed(), ephemeral=True)
        if interaction.message is not None:
            try:
                await interaction.message.edit(view=ShopPanelView(guild_id=interaction.guild.id))
            except (discord.Forbidden, discord.HTTPException):
                pass


class ShopPanelView(discord.ui.View):
    def __init__(self, *, guild_id: int | None = None):
        super().__init__(timeout=None)
        self.add_item(ShopSelect(guild_id=int(guild_id or 0)))


class ShopManageItemSelect(discord.ui.Select):
    def __init__(self, *, guild_id: int):
        items = _get_shop_items_for_guild(guild_id)
        if items:
            options = [
                discord.SelectOption(label=str(name)[:100], value=str(name)[:100], description=str(int(price))[:100])
                for name, price in items[:25]
            ]
            disabled = False
        else:
            options = [discord.SelectOption(label="Список пуст", value="__none__", description="Сначала добавьте товар")]
            disabled = True
        super().__init__(
            placeholder="Выберите товар",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="shop_manage_item_select",
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if isinstance(self.view, ShopManageView):
            self.view.selected_item = self.values[0]
        try:
            await interaction.response.defer(ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            return
        try:
            await interaction.message.edit(view=self.view)
        except (discord.Forbidden, discord.HTTPException):
            pass
        await interaction.followup.send(f"Выбрано: **{self.values[0]}**", ephemeral=True)


class ShopManageActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Выберите действие",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Добавить товар", value="add"),
                discord.SelectOption(label="Изменить цену", value="update_price"),
                discord.SelectOption(label="Удалить товар", value="remove"),
            ],
            custom_id="shop_manage_action_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Только администрация может настраивать магазин.", ephemeral=True)
            return
        if not isinstance(self.view, ShopManageView):
            await interaction.response.send_message("Не удалось прочитать состояние панели.", ephemeral=True)
            return
        action = self.values[0]
        if action == "add":
            await interaction.response.send_modal(ShopAddItemModal())
            return

        item = (self.view.selected_item or "").strip()
        if not item:
            await interaction.response.send_message("Сначала выбери товар в первом списке.", ephemeral=True)
            return

        if action == "update_price":
            await interaction.response.send_modal(ShopSetPriceModal(item_name=item))
            return
        if action == "remove":
            guild_id = interaction.guild.id
            current = _get_shop_items_for_guild(guild_id)
            updated = [(name, price) for name, price in current if name.casefold() != item.casefold()]
            if len(updated) == len(current):
                await interaction.response.send_message("Товар не найден (возможно уже удалён).", ephemeral=True)
                return
            set_shop_items(guild_id=guild_id, items=[{"name": name, "price": price} for name, price in updated])
            updated_panel = await _refresh_shop_panel_message(guild=interaction.guild)
            try:
                await interaction.message.edit(view=ShopManageView(guild_id=guild_id))
            except (discord.Forbidden, discord.HTTPException):
                pass
            await interaction.response.send_message(
                f"Готово. Товар удалён: **{item}**" + (" Панель обновлена автоматически." if updated_panel else ""),
                ephemeral=True,
            )
            return

        await interaction.response.send_message("Неизвестное действие.", ephemeral=True)


class ShopSetPriceModal(discord.ui.Modal):
    def __init__(self, *, item_name: str):
        self.item_name = item_name
        super().__init__(title=f"Цена товара • {item_name}"[:45])
        self.price = discord.ui.TextInput(
            label="Новая цена",
            placeholder="Например: 100",
            style=discord.TextStyle.short,
            required=True,
            max_length=12,
        )
        self.add_item(self.price)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Только администрация может настраивать магазин.", ephemeral=True)
            return
        m = re.search(r"-?\d+", str(self.price.value))
        if not m:
            await interaction.response.send_message("Укажи число в поле цены.", ephemeral=True)
            return
        new_price = int(m.group(0))
        if new_price <= 0:
            await interaction.response.send_message("Цена должна быть > 0.", ephemeral=True)
            return

        guild_id = interaction.guild.id
        current = _get_shop_items_for_guild(guild_id)
        updated = list(current)
        found_idx: int | None = None
        for i, (name, _) in enumerate(updated):
            if name.casefold() == self.item_name.casefold():
                found_idx = i
                break
        if found_idx is None:
            await interaction.response.send_message("Товар не найден (возможно уже удалён).", ephemeral=True)
            return
        updated[found_idx] = (updated[found_idx][0], int(new_price))
        set_shop_items(guild_id=guild_id, items=[{"name": name, "price": price} for name, price in updated])
        updated_panel = await _refresh_shop_panel_message(guild=interaction.guild)
        await interaction.response.send_message(
            f"Готово. Цена обновлена: **{updated[found_idx][0]}** — **{int(new_price)}**"
            + (" Панель обновлена автоматически." if updated_panel else ""),
            ephemeral=True,
        )


class ShopAddItemModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Добавить товар")
        self.item_name = discord.ui.TextInput(
            label="Название товара",
            placeholder="Например: Nitro Basic",
            style=discord.TextStyle.short,
            required=True,
            max_length=100,
        )
        self.price = discord.ui.TextInput(
            label="Цена",
            placeholder="Например: 100",
            style=discord.TextStyle.short,
            required=True,
            max_length=12,
        )
        self.add_item(self.item_name)
        self.add_item(self.price)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Только администрация может настраивать магазин.", ephemeral=True)
            return

        item_name = str(self.item_name.value).strip()
        if not item_name:
            await interaction.response.send_message("Укажи название товара.", ephemeral=True)
            return

        m = re.search(r"-?\d+", str(self.price.value))
        if not m:
            await interaction.response.send_message("Укажи число в поле цены.", ephemeral=True)
            return
        new_price = int(m.group(0))
        if new_price <= 0:
            await interaction.response.send_message("Цена должна быть > 0.", ephemeral=True)
            return

        guild_id = interaction.guild.id
        current = _get_shop_items_for_guild(guild_id)
        if any(name.casefold() == item_name.casefold() for name, _ in current):
            await interaction.response.send_message("Такой товар уже есть. Используй действие `Изменить цену`.", ephemeral=True)
            return

        updated = list(current)
        updated.append((item_name[:100], int(new_price)))
        set_shop_items(guild_id=guild_id, items=[{"name": name, "price": price} for name, price in updated])
        updated_panel = await _refresh_shop_panel_message(guild=interaction.guild)
        await interaction.response.send_message(
            f"Готово. Товар добавлен: **{item_name[:100]}** — **{int(new_price)}**"
            + (" Панель обновлена автоматически." if updated_panel else ""),
            ephemeral=True,
        )


class ShopManageView(discord.ui.View):
    def __init__(self, *, guild_id: int):
        super().__init__(timeout=900)
        self.selected_item: str | None = None
        self.add_item(ShopManageItemSelect(guild_id=guild_id))
        self.add_item(ShopManageActionSelect())


class ShopRejectReasonModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Причина отказа")
        self.reason = discord.ui.TextInput(
            label="Укажите причину отказа",
            placeholder="Например: недостаточно баллов / нет в наличии / ошибка заявки",
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
            await interaction.response.send_message("Только администрация может отклонять покупки.", ephemeral=True)
            return
        if not interaction.message.embeds:
            await interaction.response.send_message("Не удалось прочитать данные заявки.", ephemeral=True)
            return

        e = interaction.message.embeds[0]
        user_id: int | None = None
        item_name: str = "Товар"
        price: int = 0
        for fld in e.fields:
            if fld.name == "ID пользователя":
                try:
                    user_id = int(fld.value.strip())
                except ValueError:
                    user_id = None
            if fld.name == "Товар":
                item_name = fld.value.strip() or item_name
            if fld.name == "Цена":
                m = re.search(r"\d+", fld.value)
                price = int(m.group(0)) if m else price

        if e.fields:
            e.set_field_at(0, name="Статус", value=f"**❌ Отказано**\nПричина: {self.reason.value}", inline=False)
        else:
            e.add_field(name="Статус", value=f"**❌ Отказано**\nПричина: {self.reason.value}", inline=False)
        e.color = EMBED_COLOR
        await interaction.message.edit(embed=e, view=None)

        if user_id is not None:
            # Возврат средств при отказе (только если покупка списывалась сразу).
            should_refund = False
            refunded_balance: float | None = None
            try:
                pending = get_pending_shop_orders(guild_id=interaction.guild.id, user_id=user_id)
                for p in pending:
                    if int(p.get("review_message_id", 0)) == int(interaction.message.id):
                        should_refund = bool(p.get("debited", False))
                        break
            except Exception:
                should_refund = False

            if should_refund and price > 0:
                refunded_balance = add_user_points(
                    guild_id=interaction.guild.id,
                    user_id=user_id,
                    delta=float(price),
                )

            remove_pending_shop_order(
                guild_id=interaction.guild.id,
                user_id=user_id,
                review_message_id=interaction.message.id,
            )
            user = interaction.guild.get_member(user_id)
            if user is None:
                try:
                    user = await interaction.guild.fetch_member(user_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    user = None
            if user is not None:
                try:
                    await user.send(
                        embed=_build_shop_order_verdict_embed(
                            guild=interaction.guild,
                            admin=interaction.user,
                            approved=False,
                            item_name=item_name,
                            price=price,
                            reason=self.reason.value,
                            balance=refunded_balance,
                        )
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

        await interaction.response.send_message("Покупка отклонена.", ephemeral=True)


class ShopOrderReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success, custom_id="shop_review_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Только администрация может принимать покупки.", ephemeral=True)
            return
        if not interaction.message.embeds:
            await interaction.response.send_message("Не удалось прочитать данные заявки.", ephemeral=True)
            return

        e = interaction.message.embeds[0]
        user_id: int | None = None
        item_name: str = "Товар"
        price: int = 0
        for fld in e.fields:
            if fld.name == "ID пользователя":
                try:
                    user_id = int(fld.value.strip())
                except ValueError:
                    user_id = None
            if fld.name == "Товар":
                item_name = fld.value.strip() or item_name
            if fld.name == "Цена":
                m = re.search(r"\d+", fld.value)
                price = int(m.group(0)) if m else price

        if user_id is None or price <= 0:
            await interaction.response.send_message("Не смог прочитать ID пользователя или цену.", ephemeral=True)
            return

        # Принимаем без доп. списания: списание было в момент покупки (резерв).
        new_balance = get_user_points(guild_id=interaction.guild.id, user_id=user_id)
        remove_pending_shop_order(
            guild_id=interaction.guild.id,
            user_id=user_id,
            review_message_id=interaction.message.id,
        )

        if e.fields:
            e.set_field_at(
                0,
                name="Статус",
                value=(
                    f"**✅ Принято**\n"
                    f"Проверил: {interaction.user.mention}\n"
                    f"Списано: {price}"
                ),
                inline=False,
            )
        else:
            e.add_field(name="Статус", value=f"**✅ Принято**\nПроверил: {interaction.user.mention}\nСписано: {price}", inline=False)
        e.color = EMBED_COLOR
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
                    embed=_build_shop_order_verdict_embed(
                        guild=interaction.guild,
                        admin=interaction.user,
                        approved=True,
                        item_name=item_name,
                        price=price,
                        balance=new_balance,
                    )
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

        await interaction.response.send_message("Покупка принята.", ephemeral=True)

    @discord.ui.button(label="Отказать", style=discord.ButtonStyle.danger, custom_id="shop_review_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Только администрация может отклонять покупки.", ephemeral=True)
            return
        await interaction.response.send_modal(ShopRejectReasonModal())


class ReportLinkModal(discord.ui.Modal):
    def __init__(self, *, report_key: str, report_label: str):
        title = report_label
        super().__init__(title=f"Отчёт • {title}")
        self.report_key = report_key
        self.report_link = discord.ui.TextInput(
            label="Ссылка на отчёт",
            placeholder="Вставьте ссылку на ваш отчёт",
            style=discord.TextStyle.short,
            required=True,
            max_length=500,
        )
        self.add_item(self.report_link)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        review_channel_id = get_reports_channel_id(guild_id=interaction.guild.id)
        if not review_channel_id:
            await interaction.response.send_message(
                "Канал проверки отчётов не настроен. Обратитесь к администрации.",
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
                "Не удалось найти канал проверки отчётов. Обратитесь к администрации.",
                ephemeral=True,
            )
            return

        report_types = _get_report_types_for_guild(interaction.guild.id)
        data = report_types.get(self.report_key)
        if data is None:
            await interaction.response.send_message(
                "Этот тип отчёта больше недоступен. Обновите панель отчётов.",
                ephemeral=True,
            )
            return
        reward = int(data["reward"])
        review_embed = discord.Embed(
            title="— ・ Новый отчёт",
            description=(
                f"**Пользователь:** {interaction.user.mention}\n"
                f"**Тип:** {data['label']}\n"
                f"**Ссылка:** {self.report_link.value}"
            ),
            color=discord.Color.dark_gray(),
            timestamp=dt.datetime.now(dt.timezone.utc),
        )
        review_embed.add_field(name="Статус", value="**⏳ На проверке**", inline=False)
        review_embed.add_field(name="Награда", value=f"**{reward}** коин(а)", inline=False)
        review_embed.add_field(name="ID пользователя", value=str(interaction.user.id), inline=False)
        review_embed.set_footer(text=f"report:{self.report_key}")

        review_msg = await review_channel.send(embed=review_embed, view=ReportReviewView())
        add_pending_report(
            guild_id=interaction.guild.id,
            user_id=interaction.user.id,
            review_message_id=review_msg.id,
            report_type=str(data["label"]),
            report_url=self.report_link.value.strip(),
            created_ts=int(dt.datetime.now(dt.timezone.utc).timestamp()),
        )

        f = _report_image_file()
        done_embed = _build_report_sent_embed(with_image=(f is not None))
        if f is not None:
            await interaction.response.send_message(embed=done_embed, file=f, ephemeral=True)
        else:
            await interaction.response.send_message(embed=done_embed, ephemeral=True)


class ReportTypeSelect(discord.ui.Select):
    def __init__(self, *, guild_id: int | None = None):
        report_types = _get_report_types_for_guild(int(guild_id or 0))
        options = [
            discord.SelectOption(
                label=str(data["label"])[:100],
                value=key,
                description=str(data.get("desc", ""))[:100] or f"{int(data['reward'])} коин(а)",
            )
            for key, data in list(report_types.items())[:25]
        ]
        super().__init__(
            placeholder="Выберите тип отчёта",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="report_panel_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        report_key = self.values[0]
        report_types = _get_report_types_for_guild(interaction.guild.id)
        data = report_types.get(report_key)
        if data is None:
            await interaction.response.send_message("Этот тип отчёта больше недоступен.", ephemeral=True)
            return
        await interaction.response.send_modal(
            ReportLinkModal(report_key=report_key, report_label=str(data["label"]))
        )
        if interaction.message is not None:
            try:
                await interaction.message.edit(view=ReportPanelView(guild_id=interaction.guild.id))
            except (discord.Forbidden, discord.HTTPException):
                pass


def _build_quick_report_embed(
    *,
    title: str,
    author: discord.abc.User,
    rows: list[tuple[str, str]],
) -> discord.Embed:
    body_lines: list[str] = [f"**Отправил:** {author.mention}"]
    for name, value in rows:
        body_lines.append(f"**{name}:** {value.strip() or '—'}")
    e = discord.Embed(
        title=title,
        description="\n".join(body_lines),
        color=discord.Color.dark_gray(),
        timestamp=dt.datetime.now(dt.timezone.utc),
    )
    e.set_footer(text=f"{author.display_name} | {author.id}")
    return e


class ReportVzhModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Отчет ВЗХ")
        self.report_date = discord.ui.TextInput(
            label="1. За какое число",
            placeholder="06.05.2026",
            required=True,
            max_length=32,
        )
        self.fraction = discord.ui.TextInput(
            label="2. За какую фракцию",
            placeholder="YAK",
            required=True,
            max_length=64,
        )
        self.materials = discord.ui.TextInput(
            label="3. ВЗХ (количество материалов)",
            placeholder="5к",
            required=True,
            max_length=64,
        )
        self.add_item(self.report_date)
        self.add_item(self.fraction)
        self.add_item(self.materials)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("Отправка доступна только в текстовом канале.", ephemeral=True)
            return
        e = _build_quick_report_embed(
            title="— ・ Отчет ВЗХ",
            author=interaction.user,
            rows=[
                ("За какое число", str(self.report_date.value)),
                ("За какую фракцию", str(self.fraction.value)),
                ("ВЗХ (количество материалов)", str(self.materials.value)),
            ],
        )
        await interaction.channel.send(embed=e)
        await interaction.response.send_message("Отчет ВЗХ отправлен.", ephemeral=True)


class ReportMpModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Отчет МП")
        self.report_date = discord.ui.TextInput(
            label="1. За какое число",
            placeholder="06.05.2026",
            required=True,
            max_length=32,
        )
        self.mp_type = discord.ui.TextInput(
            label="2. МП (тип / событие)",
            placeholder="ГШ / Флаг Вагонетка",
            required=True,
            max_length=128,
        )
        self.fraction = discord.ui.TextInput(
            label="3. За какую фракцию",
            placeholder="YAK",
            required=True,
            max_length=64,
        )
        self.materials = discord.ui.TextInput(
            label="4. Количество получиных материалов",
            placeholder="2к",
            required=True,
            max_length=64,
        )
        self.result = discord.ui.TextInput(
            label="5. Итог",
            placeholder="Win / Lose",
            required=True,
            max_length=64,
        )
        self.add_item(self.report_date)
        self.add_item(self.mp_type)
        self.add_item(self.fraction)
        self.add_item(self.materials)
        self.add_item(self.result)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("Отправка доступна только в текстовом канале.", ephemeral=True)
            return
        e = _build_quick_report_embed(
            title="— ・ Отчет МП",
            author=interaction.user,
            rows=[
                ("За какое число", str(self.report_date.value)),
                ("МП (тип / событие)", str(self.mp_type.value)),
                ("За какую фракцию", str(self.fraction.value)),
                ("Количество получиных материалов", str(self.materials.value)),
                ("Итог", str(self.result.value)),
            ],
        )
        await interaction.channel.send(embed=e)
        await interaction.response.send_message("Отчет МП отправлен.", ephemeral=True)


class ReportPanelView(discord.ui.View):
    def __init__(self, *, guild_id: int | None = None):
        super().__init__(timeout=None)
        self.add_item(ReportTypeSelect(guild_id=guild_id))

    @discord.ui.button(label="Информация", style=discord.ButtonStyle.secondary, custom_id="report_info_button")
    async def info_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        pending = get_pending_reports(guild_id=interaction.guild.id, user_id=interaction.user.id)
        if not pending:
            e = discord.Embed(
                description="— ・ **Ваши необработанные отчёты**\n\nУ вас нет непроверенных отчётов.",
                color=discord.Color.dark_gray(),
            )
            await interaction.response.send_message(embed=e, ephemeral=True)
            return

        lines: list[str] = []
        for item in pending[:10]:
            report_type = str(item.get("type", "Отчёт"))
            report_url = str(item.get("url", "")).strip() or "https://discord.com"
            try:
                created_ts = int(item.get("created_ts", 0))
            except (TypeError, ValueError):
                created_ts = 0
            if created_ts > 0:
                created_dt = dt.datetime.fromtimestamp(created_ts)
                created_text = created_dt.strftime("%d.%m.%Y %H:%M")
            else:
                created_text = dt.datetime.now().strftime("%d.%m.%Y %H:%M")
            lines.append(
                f"⚙️ **{report_type}**\n{created_text} МСК  |  [перейти]({report_url})"
            )

        e = discord.Embed(
            description="— ・ **Ваши необработанные отчёты**\n\n" + "\n\n".join(lines),
            color=discord.Color.dark_gray(),
        )
        await interaction.response.send_message(embed=e, ephemeral=True)


def _build_quick_panel_embed(title: str) -> discord.Embed:
    return discord.Embed(description=title, color=discord.Color.dark_gray())


class ReportVzhPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="+", style=discord.ButtonStyle.success, custom_id="report_vzh_panel_plus")
    async def plus(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(ReportVzhModal())


class ReportMpPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="+", style=discord.ButtonStyle.success, custom_id="report_mp_panel_plus")
    async def plus(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(ReportMpModal())


class ReportRejectReasonModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Причина отказа")
        self.reason = discord.ui.TextInput(
            label="Укажите причину отказа",
            placeholder="Например: ссылка невалидна / отчёт старше 48 часов",
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
            await interaction.response.send_message("Только администрация может отклонять отчёты.", ephemeral=True)
            return
        if not interaction.message.embeds:
            await interaction.response.send_message("Не удалось прочитать данные отчёта.", ephemeral=True)
            return

        e = interaction.message.embeds[0]
        user_id: int | None = None
        for fld in e.fields:
            if fld.name == "ID пользователя":
                try:
                    user_id = int(fld.value.strip())
                except ValueError:
                    user_id = None
                break

        if e.fields:
            e.set_field_at(0, name="Статус", value=f"**❌ Отказано**\nПричина: {self.reason.value}", inline=False)
        else:
            e.add_field(name="Статус", value=f"**❌ Отказано**\nПричина: {self.reason.value}", inline=False)
        e.color = EMBED_COLOR
        await interaction.message.edit(embed=e, view=None)

        if user_id is not None:
            remove_pending_report(
                guild_id=interaction.guild.id,
                user_id=user_id,
                review_message_id=interaction.message.id,
            )
            user = interaction.guild.get_member(user_id)
            if user is None:
                try:
                    user = await interaction.guild.fetch_member(user_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    user = None
            if user is not None:
                try:
                    await user.send(
                        embed=_build_report_verdict_embed(
                            guild=interaction.guild,
                            admin=interaction.user,
                            approved=False,
                            reason=self.reason.value,
                        )
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

        await interaction.response.send_message("Отчёт отклонён.", ephemeral=True)


class ReportReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success, custom_id="report_review_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Только администрация может принимать отчёты.", ephemeral=True)
            return
        if not interaction.message.embeds:
            await interaction.response.send_message("Не удалось прочитать данные отчёта.", ephemeral=True)
            return

        e = interaction.message.embeds[0]
        user_id: int | None = None
        reward: int = 0
        for fld in e.fields:
            if fld.name == "ID пользователя":
                try:
                    user_id = int(fld.value.strip())
                except ValueError:
                    user_id = None
            if fld.name == "Награда":
                m = re.search(r"\d+", fld.value)
                reward = int(m.group(0)) if m else 0

        if user_id is None:
            await interaction.response.send_message("Не найден ID пользователя в отчёте.", ephemeral=True)
            return

        new_balance = add_user_points(guild_id=interaction.guild.id, user_id=user_id, delta=float(reward))
        remove_pending_report(
            guild_id=interaction.guild.id,
            user_id=user_id,
            review_message_id=interaction.message.id,
        )
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
        e.color = EMBED_COLOR
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
                    embed=_build_report_verdict_embed(
                        guild=interaction.guild,
                        admin=interaction.user,
                        approved=True,
                        reward=reward,
                        balance=new_balance,
                    )
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

        await interaction.response.send_message("Отчёт принят и баллы начислены.", ephemeral=True)

    @discord.ui.button(label="Отказать", style=discord.ButtonStyle.danger, custom_id="report_review_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Только администрация может отклонять отчёты.", ephemeral=True)
            return
        await interaction.response.send_modal(ReportRejectReasonModal())


@bot.tree.command(name="сбор", description="Создать сбор и отправить пинг в ЛС роли")
@app_commands.describe(
    роль="Роль для пинга и рассылки",
    тип="Тип сбора",
    участников="Сколько участников нужно (необязательно)",
    замены="Сколько замен нужно (необязательно)",
    время="19:00 / 19 00 / 15 (через 15 минут)",
    уточнение="Текст для типа 'контент' (необязательно)",
)
@app_commands.default_permissions(administrator=True)
@app_commands.choices(
    тип=[
        app_commands.Choice(name="взп", value="vzp"),
        app_commands.Choice(name="биз", value="biz"),
        app_commands.Choice(name="капт", value="capt"),
        app_commands.Choice(name="контент", value="content"),
    ]
)
async def sbor_command(
    interaction: discord.Interaction,
    роль: discord.Role,
    тип: app_commands.Choice[str],
    время: str,
    участников: str | None = None,
    замены: str | None = None,
    уточнение: str | None = None,
):
    if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("Команда доступна только в текстовом канале сервера.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    if тип.value == "content" and (уточнение is None or not уточнение.strip()):
        await interaction.followup.send("Для типа `контент` укажи параметр `уточнение`.", ephemeral=True)
        return

    parsed = _parse_sbor_time(время)
    if parsed is None:
        await interaction.followup.send(
            "Неверный формат `время`. Используй: `19:00`, `19 00` или `15` (через 15 минут).",
            ephemeral=True,
        )
        return
    when_dt, pretty_time = parsed
    type_text = _format_sbor_type(тип.value, уточнение.strip() if уточнение else None)
    main_target = _extract_target(участников)
    sub_target = _extract_target(замены)

    e = discord.Embed(
        title="— ・ Сбор",
        description=(
            f"**Тип:** {type_text}\n"
            f"**Время:** {pretty_time}\n"
            f"**Организатор:** {interaction.user.mention}"
        ),
        color=discord.Color.dark_gray(),
        timestamp=when_dt,
    )
    e.add_field(
        name=f"Участники (0/{main_target})" if main_target else "Участники (0)",
        value="—",
        inline=False,
    )
    e.add_field(
        name=f"Замены (0/{sub_target})" if sub_target else "Замены (0)",
        value="—",
        inline=False,
    )
    e.set_footer(text="Сбор")
    view = SborView(author_id=interaction.user.id, main_target=main_target, sub_target=sub_target)

    msg = await interaction.channel.send(
        content=роль.mention,
        embed=e,
        view=view,
        allowed_mentions=discord.AllowedMentions(roles=True),
    )

    dm_embed = discord.Embed(
        title="— ・ Сбор",
        description=(
            f"**Тип:** {type_text}\n"
            f"**Время:** {pretty_time}\n"
            f"**Организатор:** {interaction.user.mention}\n"
            f"**Сервер:** {interaction.guild.name}"
        ),
        color=discord.Color.dark_gray(),
        timestamp=when_dt,
    )
    dm_embed.add_field(name="Канал", value=f"{interaction.channel.mention}", inline=False)
    if main_target:
        dm_embed.add_field(name="Участников нужно", value=str(main_target), inline=True)
    if sub_target:
        dm_embed.add_field(name="Замен нужно", value=str(sub_target), inline=True)
    dm_embed.add_field(name="Записаться", value=msg.jump_url, inline=False)
    if interaction.guild.icon:
        dm_embed.set_thumbnail(url=interaction.guild.icon.url)
    dm_embed.set_footer(text="Открой ссылку, чтобы записаться")
    sent = 0
    failed = 0
    for member in роль.members:
        if member.bot:
            continue
        try:
            await member.send(embed=dm_embed, allowed_mentions=discord.AllowedMentions(users=True, roles=True))
            sent += 1
        except (discord.Forbidden, discord.HTTPException):
            failed += 1

    await interaction.followup.send(
        f"Сбор создан: {msg.jump_url}\nЛС отправлено: {sent}. Не удалось: {failed}.",
        ephemeral=True,
    )


@bot.tree.command(name="спам", description="Массовая рассылка в ЛС участникам выбранной роли")
@app_commands.describe(
    роль="Роль, участникам которой отправится сообщение",
    текст="Текст, который бот отправит в ЛС",
)
@app_commands.default_permissions(administrator=True)
async def spam_command(
    interaction: discord.Interaction,
    роль: discord.Role,
    текст: str,
):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    message_text = текст.strip()
    if not message_text:
        await interaction.response.send_message("Укажи непустой текст для рассылки.", ephemeral=True)
        return
    if len(message_text) > 2000:
        await interaction.response.send_message("Текст слишком длинный (максимум 2000 символов).", ephemeral=True)
        return
    formatted_text = f"**{message_text}**"

    await interaction.response.defer(ephemeral=True)

    sent = 0
    failed = 0
    skipped = 0
    failed_mentions: list[str] = []
    for idx, member in enumerate(роль.members, start=1):
        if member.bot:
            skipped += 1
            continue
        try:
            await member.send(formatted_text)
            sent += 1
        except (discord.Forbidden, discord.HTTPException):
            failed += 1
            if len(failed_mentions) < 10:
                failed_mentions.append(member.mention)
        if idx % 5 == 0:
            await asyncio.sleep(0.5)

    fail_preview = "\n".join(failed_mentions) if failed_mentions else "—"
    if failed > len(failed_mentions):
        fail_preview += f"\n...и ещё {failed - len(failed_mentions)}"

    await interaction.followup.send(
        (
            f"Рассылка по роли {роль.mention} завершена.\n"
            f"Отправлено: {sent}\n"
            f"Пропущено (боты): {skipped}\n"
            f"Не удалось отправить: {failed}\n"
            f"Кому не дошло (до 10):\n{fail_preview}"
        ),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@bot.tree.command(name="розыгрыш", description="Создать розыгрыш с кнопками участия")
@app_commands.default_permissions(administrator=True)
async def giveaway_command(interaction: discord.Interaction):
    await interaction.response.send_modal(GiveawayCreateModal())


def _build_voice_room_control_embed(*, owner: discord.Member) -> discord.Embed:
    return discord.Embed(
        title="Панель управления",
        description=(
            "Кнопки ниже - настройки твоей голосовой комнаты.\n"
            "(чат справа у этого войса): **Название, Лимит, Регион**\n"
            "- сразу меняют войс; **Кикнуть** - из списка;\n"
            "**Прихожая** - закрыть вход для всех, кроме тебя;\n"
            "**Забрать** - передать владельца из списка; **Друзья / Баны** - выбор из списка.\n\n"
            f"Владелец: {owner.mention}\n"
            "Комната создана автоматически после входа в лобби приват-войса."
        ),
        color=discord.Color.dark_gray(),
    )


def _message_category_id(message: discord.Message) -> int | None:
    channel = message.channel
    if isinstance(channel, discord.TextChannel):
        return channel.category_id
    if isinstance(channel, discord.Thread) and isinstance(channel.parent, discord.TextChannel):
        return channel.parent.category_id
    return None


def _build_role_ping_dm_embed(
    *,
    guild: discord.Guild,
    channel: discord.abc.GuildChannel,
    role: discord.Role,
    author: discord.abc.User,
    message_link: str,
) -> discord.Embed:
    role_label = f"@{role.name}"
    e = discord.Embed(
        title="Вас тегнули по роли",
        description=(
            f"В привязанной категории было упоминание роли **{role_label}**.\n\n"
            f"**Сервер:** {guild.name}\n"
            f"**Канал:** {channel.mention}\n"
            f"**Кто тегнул:** {author.mention}\n\n"
            f"[Перейти к сообщению]({message_link})"
        ),
        color=discord.Color.dark_gray(),
    )
    if guild.icon:
        e.set_thumbnail(url=guild.icon.url)
    e.set_footer(text="Уведомление о теге роли")
    return e


def _attack_def_remaining_text(until_ts: int | None) -> str:
    now_ts = int(time.time())
    if not until_ts or until_ts <= now_ts:
        return "готово (КД нет)"
    return f"<t:{until_ts}:R> (до <t:{until_ts}:T>)"


def _build_attack_def_embed(*, guild_id: int) -> discord.Embed:
    cfg = get_attack_def_cooldown_config(guild_id=guild_id)
    until = get_attack_def_cooldown_until(guild_id=guild_id)
    att_minutes = int(cfg.get("att_minutes", 120))
    deff_minutes = int(cfg.get("deff_minutes", 120))
    att_until = int(until.get("att_until_ts", 0) or 0)
    deff_until = int(until.get("deff_until_ts", 0) or 0)

    e = discord.Embed(
        title="ATT / DEFF",
        description="Текущий статус откатов. Кнопки ниже запускают КД.",
        color=discord.Color.dark_gray(),
    )
    e.add_field(
        name=f"ATT (КД: {att_minutes} мин)",
        value=_attack_def_remaining_text(att_until),
        inline=False,
    )
    e.add_field(
        name=f"DEFF (КД: {deff_minutes} мин)",
        value=_attack_def_remaining_text(deff_until),
        inline=False,
    )
    e.set_footer(text="Обновляйте КД кнопками ATT/DEFF")
    return e


async def _refresh_attack_def_panel_message(*, guild: discord.Guild) -> bool:
    existing = get_attack_def_panel_message_id(guild_id=guild.id)
    if not existing:
        return False
    channel_id, message_id = existing
    ch = guild.get_channel(channel_id)
    if ch is None:
        try:
            ch = await guild.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False
    if not isinstance(ch, discord.TextChannel):
        return False
    try:
        msg = await ch.fetch_message(message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False
    try:
        await msg.edit(embed=_build_attack_def_embed(guild_id=guild.id), view=AttackDefCooldownView())
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


class AttackDefCooldownView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="ATT", style=discord.ButtonStyle.danger, custom_id="attack_def_start_att")
    async def start_att(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not (interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild):
            await interaction.response.send_message("Нужны права администратора или Manage Server.", ephemeral=True)
            return

        cfg = get_attack_def_cooldown_config(guild_id=interaction.guild.id)
        minutes = int(cfg.get("att_minutes", 120))
        until_ts = int(time.time()) + minutes * 60
        set_attack_def_cooldown_until(guild_id=interaction.guild.id, att_until_ts=until_ts)

        await interaction.response.edit_message(
            embed=_build_attack_def_embed(guild_id=interaction.guild.id),
            view=AttackDefCooldownView(),
        )

    @discord.ui.button(label="DEFF", style=discord.ButtonStyle.primary, custom_id="attack_def_start_deff")
    async def start_deff(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not (interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild):
            await interaction.response.send_message("Нужны права администратора или Manage Server.", ephemeral=True)
            return

        cfg = get_attack_def_cooldown_config(guild_id=interaction.guild.id)
        minutes = int(cfg.get("deff_minutes", 120))
        until_ts = int(time.time()) + minutes * 60
        set_attack_def_cooldown_until(guild_id=interaction.guild.id, deff_until_ts=until_ts)

        await interaction.response.edit_message(
            embed=_build_attack_def_embed(guild_id=interaction.guild.id),
            view=AttackDefCooldownView(),
        )


def _build_contracts_panel_embed() -> discord.Embed:
    return discord.Embed(
        title="Контракты",
        description="Нажмите кнопку ниже, чтобы создать заявку на контракт.",
        color=discord.Color.dark_gray(),
    )


def _build_contract_request_embed(
    *,
    author: discord.Member,
    contract_name: str,
    participants: int,
    on_hundred: str,
) -> discord.Embed:
    e = discord.Embed(
        title="— ・ Заявка на контракт",
        description=(
            f"**Название:** {contract_name}\n"
            f"**На 100%:** {on_hundred}\n"
            f"**Участников:** {participants}\n"
            f"**Кто создал:** {author.mention}"
        ),
        color=discord.Color.dark_gray(),
    )
    e.add_field(name="Статус", value="⏳ На рассмотрении", inline=False)
    e.add_field(name=f"Список участников (1/{participants})", value=author.mention, inline=False)
    return e


def _extract_first_id(raw: str) -> int | None:
    m = re.search(r"\d{6,25}", raw or "")
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None


def _extract_contract_author_id(embed: discord.Embed) -> int | None:
    return _extract_first_id(embed.description or "")


def _extract_contract_participants_limit(embed: discord.Embed) -> int:
    m = re.search(r"\*\*Участников:\*\*\s*(\d{1,3})", embed.description or "")
    if not m:
        return 1
    try:
        return max(1, int(m.group(1)))
    except ValueError:
        return 1


def _extract_contract_participant_ids(embed: discord.Embed) -> list[int]:
    for f in embed.fields:
        if str(f.name).startswith("Список участников"):
            found = re.findall(r"<@!?(\d{6,25})>", str(f.value or ""))
            out: list[int] = []
            for x in found:
                try:
                    uid = int(x)
                except ValueError:
                    continue
                if uid not in out:
                    out.append(uid)
            return out
    return []


def _render_contract_participants(*, member_ids: list[int], limit: int) -> tuple[str, str]:
    uniq: list[int] = []
    for uid in member_ids:
        if uid not in uniq:
            uniq.append(uid)
    title = f"Список участников ({len(uniq)}/{max(1, limit)})"
    if not uniq:
        return title, "—"
    return title, "\n".join(f"<@{uid}>" for uid in uniq)


def _build_contract_reject_dm_embed(
    *,
    guild: discord.Guild,
    reviewer: discord.abc.User,
    reason: str,
) -> discord.Embed:
    e = discord.Embed(
        title="— ・ Контракт отклонён",
        description=(
            f"Ваша заявка на контракт была отклонена.\n\n"
            f"**Причина:** {reason}\n"
            f"**Кто отказал:** {reviewer.mention}\n"
            f"**Сервер:** {guild.name}"
        ),
        color=discord.Color.dark_gray(),
    )
    if guild.icon:
        e.set_thumbnail(url=guild.icon.url)
    e.set_footer(text=dt.datetime.now().strftime("%d.%m.%Y %H:%M"))
    return e


class ContractCreateModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Заявка на контракт")
        self.contract_name = discord.ui.TextInput(
            label="Название контракта",
            placeholder="Например: Контракт на поставку",
            required=True,
            max_length=100,
        )
        self.participants = discord.ui.TextInput(
            label="Сколько участников нужно",
            placeholder="Например: 5",
            required=True,
            max_length=4,
        )
        self.on_hundred = discord.ui.TextInput(
            label="На 100%",
            placeholder="Например: Да / Нет / 100%",
            required=True,
            max_length=30,
        )
        self.add_item(self.contract_name)
        self.add_item(self.participants)
        self.add_item(self.on_hundred)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        raw_count = str(self.participants.value).strip()
        if not raw_count.isdigit():
            await interaction.response.send_message("`Сколько участников` должно быть числом.", ephemeral=True)
            return
        count = int(raw_count)
        if count <= 0 or count > 99:
            await interaction.response.send_message("Укажи число участников от 1 до 99.", ephemeral=True)
            return

        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message(
                "Заявку можно отправить только из текстового канала/треда.",
                ephemeral=True,
            )
            return

        embed = _build_contract_request_embed(
            author=interaction.user,
            contract_name=str(self.contract_name.value).strip(),
            participants=count,
            on_hundred=str(self.on_hundred.value).strip(),
        )
        await interaction.channel.send(embed=embed, view=ContractReviewView())
        await interaction.response.send_message("Заявка на контракт отправлена на рассмотрение.", ephemeral=True)


class ContractsPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="+", style=discord.ButtonStyle.success, custom_id="contracts_create")
    async def create_contract(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ContractCreateModal())


class ContractRejectReasonModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Отказать по контракту")
        self.reason = discord.ui.TextInput(
            label="Причина отказа",
            placeholder="Укажи причину, которая уйдёт автору в ЛС",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=600,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return

        applicant = None
        if interaction.message and interaction.message.embeds:
            uid = _extract_contract_author_id(interaction.message.embeds[0])
            if uid:
                applicant = interaction.guild.get_member(uid)
                if applicant is None:
                    try:
                        applicant = await interaction.guild.fetch_member(uid)
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        applicant = None

        if interaction.message and interaction.message.embeds:
            e = interaction.message.embeds[0]
            if e.fields:
                e.set_field_at(0, name="Статус", value=f"❌ Отказано — {interaction.user.mention}", inline=False)
            else:
                e.add_field(name="Статус", value=f"❌ Отказано — {interaction.user.mention}", inline=False)
            try:
                await interaction.message.edit(embed=e, view=None)
            except (discord.Forbidden, discord.HTTPException):
                pass

        if applicant is not None:
            try:
                await applicant.send(
                    embed=_build_contract_reject_dm_embed(
                        guild=interaction.guild,
                        reviewer=interaction.user,
                        reason=str(self.reason.value).strip(),
                    )
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

        await interaction.response.send_message("Заявка отклонена. Причина отправлена в ЛС (если открыты).", ephemeral=True)


class ContractReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Участвовать", style=discord.ButtonStyle.secondary, custom_id="contracts_join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.message is None or not interaction.message.embeds:
            await interaction.response.send_message("Не удалось прочитать заявку.", ephemeral=True)
            return
        e = interaction.message.embeds[0]
        if interaction.user.id in _extract_contract_participant_ids(e):
            await interaction.response.send_message("Ты уже в списке участников.", ephemeral=True)
            return
        limit = _extract_contract_participants_limit(e)
        members = _extract_contract_participant_ids(e)
        if len(members) >= limit:
            await interaction.response.send_message("Список участников уже заполнен.", ephemeral=True)
            return
        members.append(interaction.user.id)
        name, value = _render_contract_participants(member_ids=members, limit=limit)
        if len(e.fields) >= 2:
            e.set_field_at(1, name=name, value=value, inline=False)
        else:
            e.add_field(name=name, value=value, inline=False)
        await interaction.response.edit_message(embed=e, view=self)

    @discord.ui.button(label="Пикнул", style=discord.ButtonStyle.success, custom_id="contracts_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.message and interaction.message.embeds:
            e = interaction.message.embeds[0]
            if e.fields:
                e.set_field_at(0, name="Статус", value=f"✅ Пикнул — {interaction.user.mention}", inline=False)
            else:
                e.add_field(name="Статус", value=f"✅ Пикнул — {interaction.user.mention}", inline=False)
            await interaction.message.edit(embed=e, view=None)
        await interaction.response.send_message("Заявка отмечена как пикнутая.", ephemeral=True)

    @discord.ui.button(label="Отказать", style=discord.ButtonStyle.danger, custom_id="contracts_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ContractRejectReasonModal())


def _who_line(user: discord.abc.User) -> str:
    display = user.display_name if isinstance(user, discord.Member) else user.name
    return f"{user.mention} | {display} | {user.id}"


async def _get_logs_text_channel(guild: discord.Guild) -> discord.TextChannel | None:
    logs_id = get_logs_channel_id(guild_id=guild.id)
    if not logs_id:
        return None
    ch = guild.get_channel(logs_id)
    if ch is None:
        try:
            ch = await guild.fetch_channel(logs_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None
    return ch if isinstance(ch, discord.TextChannel) else None


def _build_action_log_embed(
    *,
    action_name: str,
    actor_line: str,
    target_line: str | None = None,
    account_created_text: str | None = None,
) -> discord.Embed:
    parts: list[str] = [f"**Действие:** {action_name}", "", f"**Кто:**\n{actor_line}"]
    if target_line:
        parts.extend(["", f"**Кого:**\n{target_line}"])
    if account_created_text:
        parts.extend(["", f"**Когда регистрация аккаунта:**\n{account_created_text}"])

    e = discord.Embed(
        title="— ・ Действие",
        description="\n".join(parts),
        color=discord.Color.dark_gray(),
    )
    e.set_footer(text=dt.datetime.now().strftime("%d.%m.%Y %H:%M"))
    return e


async def _send_action_log(
    *,
    guild: discord.Guild,
    action_name: str,
    actor: discord.abc.User,
    target: discord.abc.User,
) -> None:
    channel = await _get_logs_text_channel(guild)
    if channel is None:
        return
    e = _build_action_log_embed(
        action_name=action_name,
        actor_line=_who_line(actor),
        target_line=_who_line(target),
    )
    try:
        await channel.send(embed=e)
    except (discord.Forbidden, discord.HTTPException):
        return


async def _send_join_leave_log(
    *,
    guild: discord.Guild,
    action_name: str,
    member: discord.Member,
) -> None:
    channel = await _get_logs_text_channel(guild)
    if channel is None:
        return
    created_text = member.created_at.astimezone(MSK_TZ).strftime("%d.%m.%Y %H:%M МСК")
    e = _build_action_log_embed(
        action_name=action_name,
        actor_line=_who_line(member),
        account_created_text=created_text,
    )
    try:
        await channel.send(embed=e)
    except (discord.Forbidden, discord.HTTPException):
        return


async def _find_recent_audit_actor(
    *,
    guild: discord.Guild,
    action: discord.AuditLogAction,
    target_id: int,
    max_age_s: int = 20,
    retries: int = 3,
) -> discord.abc.User | None:
    attempts = max(1, int(retries))
    for attempt in range(attempts):
        now = dt.datetime.now(dt.timezone.utc)
        try:
            async for entry in guild.audit_logs(limit=12, action=action):
                entry_target_id = getattr(entry.target, "id", None)
                if entry_target_id is None:
                    continue
                try:
                    if int(entry_target_id) != int(target_id):
                        continue
                except (TypeError, ValueError):
                    continue
                age_s = (now - entry.created_at).total_seconds()
                if age_s < 0 or age_s > max_age_s:
                    continue
                if isinstance(entry.user, (discord.Member, discord.User)):
                    return entry.user
        except (discord.Forbidden, discord.HTTPException):
            return None
        if attempt < attempts - 1:
            await asyncio.sleep(1.0)
    return None


def _parse_member_id(raw: str) -> int | None:
    m = re.search(r"\d{6,25}", raw or "")
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None


def _can_manage_voice_room(member: discord.Member, owner_id: int | None) -> bool:
    if owner_id is not None and member.id == owner_id:
        return True
    return member.guild_permissions.administrator or member.guild_permissions.manage_channels


def _voice_hub_lobby_line(guild: discord.Guild) -> str:
    lid = get_voice_lobby_channel_id(guild_id=guild.id)
    if lid is None:
        return "Сначала администратор должен привязать лобби: `/привязка-приват-войса`."
    ch = guild.get_channel(lid)
    if isinstance(ch, discord.VoiceChannel):
        return f"Зайди в {ch.mention}, чтобы создать комнату: {ch.jump_url}"
    return "Канал-лобби не найден. Попроси админа снова выполнить `/привязка-приват-войса`."


def _resolve_hub_target_voice(member: discord.Member, guild: discord.Guild) -> tuple[discord.VoiceChannel | None, str | None]:
    hint = _voice_hub_lobby_line(guild)
    if member.voice is None or member.voice.channel is None:
        return None, hint
    vc = member.voice.channel
    if not isinstance(vc, discord.VoiceChannel):
        return None, hint
    owner_id = get_temp_voice_owner_id(guild_id=guild.id, channel_id=vc.id)
    if owner_id is None:
        # Fallback for legacy/missed mappings: if this member has explicit room-owner overwrite,
        # restore DB binding so the private panel keeps working after restarts/manual edits.
        member_overwrite = vc.overwrites.get(member)
        if member_overwrite is not None and member_overwrite.manage_channels is True:
            set_temp_voice_owner_id(guild_id=guild.id, channel_id=vc.id, owner_id=member.id)
            owner_id = member.id
    if owner_id is None:
        return None, "Панель работает только в **своей** комнате, созданной ботом через лобби.\n" + hint
    if not _can_manage_voice_room(member, owner_id):
        return None, "Только **владелец** этой комнаты или администратор может менять настройки."
    return vc, None


def _pickable_voice_members(channel: discord.VoiceChannel, *, action: str, actor_id: int) -> list[discord.Member]:
    out: list[discord.Member] = []
    for m in channel.members:
        if m.bot:
            continue
        if action in {"kick", "ban", "owner", "revoke"} and m.id == actor_id:
            continue
        out.append(m)
    return out


class VoiceRoomNameModal(discord.ui.Modal):
    def __init__(self, *, voice_channel_id: int | None = None):
        super().__init__(title="Название комнаты")
        self._voice_channel_id = voice_channel_id
        self.new_name = discord.ui.TextInput(
            label="Новое название",
            placeholder="Например: Комната • prestige",
            max_length=100,
            required=True,
        )
        self.add_item(self.new_name)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if self._voice_channel_id is not None:
            raw = interaction.guild.get_channel(self._voice_channel_id)
        else:
            raw = interaction.channel
        if not isinstance(raw, discord.VoiceChannel):
            await interaction.response.send_message("Эта кнопка работает только в чате голосовой комнаты.", ephemeral=True)
            return
        channel = raw

        owner_id = get_temp_voice_owner_id(guild_id=interaction.guild.id, channel_id=channel.id)
        if not _can_manage_voice_room(interaction.user, owner_id):
            await interaction.response.send_message("Только владелец комнаты или админ может это делать.", ephemeral=True)
            return
        try:
            await channel.edit(name=self.new_name.value.strip()[:100], reason=f"Переименование: {interaction.user}")
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("Не удалось изменить название.", ephemeral=True)
            return
        await interaction.response.send_message("Название обновлено.", ephemeral=True)


class VoiceRoomLimitModal(discord.ui.Modal):
    def __init__(self, *, voice_channel_id: int | None = None):
        super().__init__(title="Лимит комнаты")
        self._voice_channel_id = voice_channel_id
        self.limit = discord.ui.TextInput(
            label="Лимит (0-99)",
            placeholder="0 = без лимита",
            max_length=2,
            required=True,
        )
        self.add_item(self.limit)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if self._voice_channel_id is not None:
            raw = interaction.guild.get_channel(self._voice_channel_id)
        else:
            raw = interaction.channel
        if not isinstance(raw, discord.VoiceChannel):
            await interaction.response.send_message("Эта кнопка работает только в чате голосовой комнаты.", ephemeral=True)
            return
        channel = raw

        owner_id = get_temp_voice_owner_id(guild_id=interaction.guild.id, channel_id=channel.id)
        if not _can_manage_voice_room(interaction.user, owner_id):
            await interaction.response.send_message("Только владелец комнаты или админ может это делать.", ephemeral=True)
            return
        try:
            value = int(self.limit.value.strip())
        except ValueError:
            await interaction.response.send_message("Введи число от 0 до 99.", ephemeral=True)
            return
        if value < 0 or value > 99:
            await interaction.response.send_message("Лимит должен быть от 0 до 99.", ephemeral=True)
            return
        try:
            await channel.edit(user_limit=value, reason=f"Лимит: {interaction.user}")
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("Не удалось изменить лимит.", ephemeral=True)
            return
        await interaction.response.send_message(f"Лимит обновлён: {value}.", ephemeral=True)


async def _apply_voice_room_member_action(
    *,
    guild: discord.Guild,
    channel: discord.VoiceChannel,
    actor: discord.abc.User,
    action: str,
    target_member: discord.Member,
) -> str:
    if action == "kick":
        if target_member not in channel.members:
            return "Пользователь не в этой комнате."
        await target_member.move_to(None, reason=f"Кик из комнаты: {actor}")
        return f"{target_member.mention} кикнут из комнаты."

    if action == "owner":
        if target_member not in channel.members:
            return "Новый владелец должен быть в комнате."
        set_temp_voice_owner_id(
            guild_id=guild.id,
            channel_id=channel.id,
            owner_id=target_member.id,
        )
        await channel.set_permissions(
            target_member,
            connect=True,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            speak=True,
            stream=True,
            use_voice_activation=True,
            priority_speaker=True,
            move_members=True,
            mute_members=True,
            deafen_members=True,
            manage_channels=True,
        )
        return f"Владелец комнаты: {target_member.mention}."

    if action == "friend":
        await channel.set_permissions(
            target_member,
            connect=True,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            speak=True,
            stream=True,
        )
        return f"{target_member.mention} добавлен в друзья комнаты."

    if action == "revoke":
        if target_member in channel.members:
            try:
                await target_member.move_to(None, reason=f"Снят доступ: {actor}")
            except (discord.Forbidden, discord.HTTPException):
                pass
        await channel.set_permissions(target_member, overwrite=None)
        return f"У {target_member.mention} снят персональный доступ к комнате."

    if action == "ban":
        if target_member in channel.members:
            try:
                await target_member.move_to(None, reason=f"Бан в комнате: {actor}")
            except (discord.Forbidden, discord.HTTPException):
                pass
        await channel.set_permissions(
            target_member,
            connect=False,
            view_channel=False,
            send_messages=False,
            read_message_history=False,
        )
        return f"{target_member.mention} добавлен в бан комнаты."

    return "Неизвестное действие."


class VoiceRoomMemberSelect(discord.ui.Select):
    def __init__(self, *, action: str, members: list[discord.Member], voice_channel_id: int | None = None):
        self.action = action
        self.voice_channel_id = voice_channel_id
        label_map = {
            "kick": "Выбери кого кикнуть",
            "owner": "Выбери нового владельца",
            "friend": "Выбери друга",
            "ban": "Выбери кого забанить",
            "revoke": "Выбери кого убрать из доступа",
        }
        options: list[discord.SelectOption] = []
        for member in members[:25]:
            options.append(
                discord.SelectOption(
                    label=member.display_name[:100],
                    value=str(member.id),
                    description=str(member.id),
                )
            )
        super().__init__(
            placeholder=label_map.get(action, "Выбери участника"),
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        guild = interaction.guild
        if self.voice_channel_id is not None:
            raw_ch = guild.get_channel(self.voice_channel_id)
        else:
            raw_ch = interaction.channel
        if not isinstance(raw_ch, discord.VoiceChannel):
            await interaction.response.send_message("Эта кнопка работает только в чате голосовой комнаты.", ephemeral=True)
            return
        ch = raw_ch
        owner_id = get_temp_voice_owner_id(guild_id=guild.id, channel_id=ch.id)
        if not _can_manage_voice_room(interaction.user, owner_id):
            await interaction.response.send_message("Только владелец комнаты или админ может это делать.", ephemeral=True)
            return

        try:
            target_id = int(self.values[0])
        except (TypeError, ValueError):
            await interaction.response.send_message("Не смог прочитать выбранного пользователя.", ephemeral=True)
            return
        target_member = guild.get_member(target_id)
        if target_member is None:
            await interaction.response.send_message("Пользователь не найден на сервере.", ephemeral=True)
            return

        try:
            result_text = await _apply_voice_room_member_action(
                guild=guild,
                channel=ch,
                actor=interaction.user,
                action=self.action,
                target_member=target_member,
            )
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("Не удалось применить действие (права/иерархия).", ephemeral=True)
            return
        await interaction.response.send_message(result_text, ephemeral=True)


class VoiceRoomMemberPickerView(discord.ui.View):
    def __init__(self, *, action: str, members: list[discord.Member], voice_channel_id: int | None = None):
        super().__init__(timeout=120)
        self.add_item(VoiceRoomMemberSelect(action=action, members=members, voice_channel_id=voice_channel_id))


class VoiceRoomControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @staticmethod
    def _pickable_members(channel: discord.VoiceChannel, *, action: str, actor_id: int) -> list[discord.Member]:
        return _pickable_voice_members(channel, action=action, actor_id=actor_id)

    @discord.ui.button(label="Название", style=discord.ButtonStyle.secondary, emoji="🔤")
    async def set_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VoiceRoomNameModal())

    @discord.ui.button(label="Лимит", style=discord.ButtonStyle.secondary, emoji="👥")
    async def set_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VoiceRoomLimitModal())

    @discord.ui.button(label="Регион", style=discord.ButtonStyle.secondary, emoji="🌐")
    async def set_region(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.channel, discord.VoiceChannel):
            await interaction.response.send_message("Эта кнопка работает только в чате голосовой комнаты.", ephemeral=True)
            return
        owner_id = get_temp_voice_owner_id(guild_id=interaction.guild.id, channel_id=interaction.channel.id)
        if not _can_manage_voice_room(interaction.user, owner_id):
            await interaction.response.send_message("Только владелец комнаты или админ может это делать.", ephemeral=True)
            return

        regions: list[str | None] = [None, "rotterdam", "frankfurt", "singapore", "us-central", "us-east", "us-west"]
        current = str(interaction.channel.rtc_region) if interaction.channel.rtc_region is not None else None
        try:
            idx = regions.index(current)
        except ValueError:
            idx = 0
        next_region = regions[(idx + 1) % len(regions)]
        try:
            await interaction.channel.edit(rtc_region=next_region, reason=f"Смена региона: {interaction.user}")
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("Не удалось изменить регион.", ephemeral=True)
            return
        pretty = next_region if next_region is not None else "auto"
        await interaction.response.send_message(f"Регион: `{pretty}`.", ephemeral=True)

    @discord.ui.button(label="Кикнуть", style=discord.ButtonStyle.secondary, emoji="🦶")
    async def kick_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.channel, discord.VoiceChannel):
            await interaction.response.send_message("Эта кнопка работает только в чате голосовой комнаты.", ephemeral=True)
            return
        members = self._pickable_members(interaction.channel, action="kick", actor_id=interaction.user.id)
        if not members:
            await interaction.response.send_message("В комнате нет доступных участников для кика.", ephemeral=True)
            return
        await interaction.response.send_message("Кого кикнуть?", view=VoiceRoomMemberPickerView(action="kick", members=members), ephemeral=True)

    @discord.ui.button(label="Гайд", style=discord.ButtonStyle.primary, emoji="ℹ️")
    async def guide(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            (
                "Настройки комнаты:\n"
                "- `Название` — меняет имя войса\n"
                "- `Лимит` — максимум участников\n"
                "- `Регион` — цикл регионов звонка\n"
                "- `Кикнуть` — выгнать участника\n"
                "- `Прихожая` — закрыть/открыть вход всем\n"
                "- `Забрать` — передать владельца\n"
                "- `Друзья` — дать доступ участнику\n"
                "- `Баны` — запретить доступ участнику"
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Прихожая", style=discord.ButtonStyle.secondary, emoji="🕓")
    async def toggle_lobby(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.channel, discord.VoiceChannel):
            await interaction.response.send_message("Эта кнопка работает только в чате голосовой комнаты.", ephemeral=True)
            return
        owner_id = get_temp_voice_owner_id(guild_id=interaction.guild.id, channel_id=interaction.channel.id)
        if not _can_manage_voice_room(interaction.user, owner_id):
            await interaction.response.send_message("Только владелец комнаты или админ может это делать.", ephemeral=True)
            return

        ow = interaction.channel.overwrites_for(interaction.guild.default_role)
        currently_locked = ow.connect is False
        new_connect = True if currently_locked else False
        try:
            await interaction.channel.set_permissions(
                interaction.guild.default_role,
                connect=new_connect,
                view_channel=ow.view_channel,
                send_messages=ow.send_messages,
                read_message_history=ow.read_message_history,
            )
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("Не удалось обновить доступ в комнату.", ephemeral=True)
            return
        state_text = "открыт" if new_connect else "закрыт"
        await interaction.response.send_message(f"Вход для всех: **{state_text}**.", ephemeral=True)

    @discord.ui.button(label="Забрать", style=discord.ButtonStyle.secondary, emoji="⭐")
    async def transfer_owner(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.channel, discord.VoiceChannel):
            await interaction.response.send_message("Эта кнопка работает только в чате голосовой комнаты.", ephemeral=True)
            return
        members = self._pickable_members(interaction.channel, action="owner", actor_id=interaction.user.id)
        if not members:
            await interaction.response.send_message("Некому передавать владельца.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Кому передать владельца?",
            view=VoiceRoomMemberPickerView(action="owner", members=members),
            ephemeral=True,
        )

    @discord.ui.button(label="Друзья", style=discord.ButtonStyle.success, emoji="👥")
    async def add_friend(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.channel, discord.VoiceChannel):
            await interaction.response.send_message("Эта кнопка работает только в чате голосовой комнаты.", ephemeral=True)
            return
        members = self._pickable_members(interaction.channel, action="friend", actor_id=interaction.user.id)
        if not members:
            await interaction.response.send_message("В комнате нет участников для добавления в друзья.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Кого добавить в друзья?",
            view=VoiceRoomMemberPickerView(action="friend", members=members),
            ephemeral=True,
        )

    @discord.ui.button(label="Баны", style=discord.ButtonStyle.danger, emoji="⛔")
    async def add_ban(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.channel, discord.VoiceChannel):
            await interaction.response.send_message("Эта кнопка работает только в чате голосовой комнаты.", ephemeral=True)
            return
        members = self._pickable_members(interaction.channel, action="ban", actor_id=interaction.user.id)
        if not members:
            await interaction.response.send_message("В комнате нет доступных участников для бана.", ephemeral=True)
            return
        await interaction.response.send_message("Кого забанить в комнате?", view=VoiceRoomMemberPickerView(action="ban", members=members), ephemeral=True)


def _build_private_voice_hub_embed() -> discord.Embed:
    e = discord.Embed(
        title="Управление приватной комнатой",
        description=(
            "➕ • **Добавить слот** — +1 к лимиту мест\n"
            "➖ • **Убрать слот** — −1 к лимиту\n"
            "🔢 • **Изменить слоты** — ввести лимит вручную\n"
            "🔓 • **Открыть канал** — все могут зайти\n"
            "🔒 • **Закрыть канал** — вход только с доступом\n\n"
            "🙋 • **Добавить пользователя** — выдать доступ\n"
            "🧹 • **Убрать пользователя** — снять доступ\n"
            "🤝 • **Передать канал** — новый владелец\n"
            "🙈 • **Скрыть канал** — не виден в списке\n"
            "👁️ • **Показать канал** — снова виден\n\n"
            "✏️ • **Переименовать канал**\n"
            "⛔ • **Заблокировать пользователя**"
        ),
        color=discord.Color.dark_gray(),
    )
    e.set_footer(
        text="Кнопки работают, когда ты в своей приватной комнате (созданной через лобби).",
    )
    return e


class PrivateVoiceHubView(discord.ui.View):
    """Панель в текстовом канале: действия на голосовой комнате пользователя (persistent custom_id)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="➕", custom_id="pvh:slot_up", row=0)
    async def slot_up(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Только на сервере.", ephemeral=True)
            return
        vc, err = _resolve_hub_target_voice(interaction.user, interaction.guild)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        u = vc.user_limit or 0
        if u >= 99:
            await interaction.response.send_message("Лимит уже **99**.", ephemeral=True)
            return
        new_u = min(99, u + 1) if u else 2
        try:
            await vc.edit(user_limit=new_u, reason=f"Слот +: {interaction.user}")
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("Не удалось изменить лимит.", ephemeral=True)
            return
        await interaction.response.send_message(f"Лимит мест: **{new_u}**.", ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="➖", custom_id="pvh:slot_down", row=0)
    async def slot_down(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Только на сервере.", ephemeral=True)
            return
        vc, err = _resolve_hub_target_voice(interaction.user, interaction.guild)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        u = vc.user_limit or 0
        if u == 0:
            await interaction.response.send_message("Уже **без лимита** слотов.", ephemeral=True)
            return
        new_u = max(0, u - 1)
        try:
            await vc.edit(user_limit=new_u, reason=f"Слот −: {interaction.user}")
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("Не удалось изменить лимит.", ephemeral=True)
            return
        await interaction.response.send_message(f"Лимит мест: **{new_u if new_u else 'без лимита'}**.", ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="🔢", custom_id="pvh:slots_modal", row=0)
    async def slots_modal(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Только на сервере.", ephemeral=True)
            return
        vc, err = _resolve_hub_target_voice(interaction.user, interaction.guild)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await interaction.response.send_modal(VoiceRoomLimitModal(voice_channel_id=vc.id))

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="🔓", custom_id="pvh:open", row=0)
    async def open_room(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Только на сервере.", ephemeral=True)
            return
        vc, err = _resolve_hub_target_voice(interaction.user, interaction.guild)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        ow = vc.overwrites_for(interaction.guild.default_role)
        try:
            await vc.set_permissions(
                interaction.guild.default_role,
                connect=True,
                view_channel=ow.view_channel,
                send_messages=ow.send_messages,
                read_message_history=ow.read_message_history,
            )
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("Не удалось открыть вход.", ephemeral=True)
            return
        await interaction.response.send_message("Вход для **всех** открыт.", ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="pvh:close", row=0)
    async def close_room(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Только на сервере.", ephemeral=True)
            return
        vc, err = _resolve_hub_target_voice(interaction.user, interaction.guild)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        ow = vc.overwrites_for(interaction.guild.default_role)
        try:
            await vc.set_permissions(
                interaction.guild.default_role,
                connect=False,
                view_channel=ow.view_channel,
                send_messages=ow.send_messages,
                read_message_history=ow.read_message_history,
            )
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("Не удалось закрыть вход.", ephemeral=True)
            return
        await interaction.response.send_message("Вход для **всех** закрыт (остаётся доступ у владельца и друзей).", ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="🙋", custom_id="pvh:friend", row=1)
    async def add_friend_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Только на сервере.", ephemeral=True)
            return
        vc, err = _resolve_hub_target_voice(interaction.user, interaction.guild)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        members = _pickable_voice_members(vc, action="friend", actor_id=interaction.user.id)
        if not members:
            await interaction.response.send_message("Нет участников для выдачи доступа.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Кого добавить?",
            view=VoiceRoomMemberPickerView(action="friend", members=members, voice_channel_id=vc.id),
            ephemeral=True,
        )

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="🧹", custom_id="pvh:revoke", row=1)
    async def revoke_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Только на сервере.", ephemeral=True)
            return
        vc, err = _resolve_hub_target_voice(interaction.user, interaction.guild)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        members = _pickable_voice_members(vc, action="revoke", actor_id=interaction.user.id)
        if not members:
            await interaction.response.send_message("Некого убирать из доступа.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Кого убрать из доступа?",
            view=VoiceRoomMemberPickerView(action="revoke", members=members, voice_channel_id=vc.id),
            ephemeral=True,
        )

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="🤝", custom_id="pvh:owner", row=1)
    async def transfer_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Только на сервере.", ephemeral=True)
            return
        vc, err = _resolve_hub_target_voice(interaction.user, interaction.guild)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        members = _pickable_voice_members(vc, action="owner", actor_id=interaction.user.id)
        if not members:
            await interaction.response.send_message("Некому передавать владельца.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Кому передать владельца?",
            view=VoiceRoomMemberPickerView(action="owner", members=members, voice_channel_id=vc.id),
            ephemeral=True,
        )

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="🙈", custom_id="pvh:hide", row=1)
    async def hide_room(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Только на сервере.", ephemeral=True)
            return
        vc, err = _resolve_hub_target_voice(interaction.user, interaction.guild)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        ow = vc.overwrites_for(interaction.guild.default_role)
        try:
            await vc.set_permissions(
                interaction.guild.default_role,
                view_channel=False,
                connect=ow.connect,
                send_messages=ow.send_messages,
                read_message_history=ow.read_message_history,
            )
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("Не удалось скрыть канал.", ephemeral=True)
            return
        await interaction.response.send_message("Канал **скрыт** для @everyone в списке.", ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="👁️", custom_id="pvh:show", row=1)
    async def show_room(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Только на сервере.", ephemeral=True)
            return
        vc, err = _resolve_hub_target_voice(interaction.user, interaction.guild)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        ow = vc.overwrites_for(interaction.guild.default_role)
        try:
            await vc.set_permissions(
                interaction.guild.default_role,
                view_channel=True,
                connect=ow.connect,
                send_messages=ow.send_messages,
                read_message_history=ow.read_message_history,
            )
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("Не удалось показать канал.", ephemeral=True)
            return
        await interaction.response.send_message("Канал снова **виден** в списке.", ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="pvh:rename", row=2)
    async def rename_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Только на сервере.", ephemeral=True)
            return
        vc, err = _resolve_hub_target_voice(interaction.user, interaction.guild)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await interaction.response.send_modal(VoiceRoomNameModal(voice_channel_id=vc.id))

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="⛔", custom_id="pvh:ban", row=2)
    async def ban_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Только на сервере.", ephemeral=True)
            return
        vc, err = _resolve_hub_target_voice(interaction.user, interaction.guild)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        members = _pickable_voice_members(vc, action="ban", actor_id=interaction.user.id)
        if not members:
            await interaction.response.send_message("Нет участников для блокировки.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Кого заблокировать?",
            view=VoiceRoomMemberPickerView(action="ban", members=members, voice_channel_id=vc.id),
            ephemeral=True,
        )


@bot.tree.command(name="панель-магазин", description="Отправить панель магазина в выбранный канал")
@app_commands.describe(panel_channel="Канал, куда отправить панель магазина")
@app_commands.default_permissions(administrator=True)
async def shop_panel(interaction: discord.Interaction, panel_channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    # Важно: отправка embed + файла может занять >3s, поэтому сразу подтверждаем interaction.
    await interaction.response.defer(ephemeral=True)

    f = _shop_image_file()
    embed = _build_shop_embed_for_guild(guild_id=interaction.guild.id, with_image=(f is not None))
    view = ShopPanelView(guild_id=interaction.guild.id)
    existing = get_shop_panel_message_id(guild_id=interaction.guild.id)
    edited = False
    if existing and existing[0] == panel_channel.id:
        try:
            old_msg = await panel_channel.fetch_message(existing[1])
            await old_msg.edit(embed=embed, view=view)
            edited = True
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            edited = False

    if not edited:
        if f is not None:
            msg = await panel_channel.send(embed=embed, view=view, file=f)
        else:
            msg = await panel_channel.send(embed=embed, view=view)
        set_shop_panel_message_id(guild_id=interaction.guild.id, channel_id=panel_channel.id, message_id=msg.id)

    await interaction.followup.send(
        f"Панель магазина {'обновлена' if edited else 'отправлена'} в {panel_channel.mention}.",
        ephemeral=True,
    )


@bot.tree.command(name="привязка-отчетов", description="Выбрать канал, куда будут отправляться отчёты на проверку")
@app_commands.describe(send_to="Канал, куда бот будет отправлять отчёты")
@app_commands.default_permissions(administrator=True)
async def bind_reports(interaction: discord.Interaction, send_to: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    set_reports_channel_id(guild_id=interaction.guild.id, channel_id=send_to.id)
    await interaction.response.send_message(
        f"Готово. Теперь отчёты будут отправляться в {send_to.mention}.",
        ephemeral=True,
    )


@bot.tree.command(name="привязка-логов", description="Выбрать канал, куда бот будет отправлять логи действий")
@app_commands.describe(send_to="Канал для логов: бан, исключение, войс-действия")
@app_commands.default_permissions(administrator=True)
async def bind_logs(interaction: discord.Interaction, send_to: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    set_logs_channel_id(guild_id=interaction.guild.id, channel_id=send_to.id)
    await interaction.response.send_message(
        f"Готово. Логи действий будут отправляться в {send_to.mention}.",
        ephemeral=True,
    )


@bot.tree.command(name="привязка-магазина", description="Выбрать канал, куда будут отправляться покупки из магазина на проверку")
@app_commands.describe(send_to="Канал, куда бот будет отправлять заявки на покупку")
@app_commands.default_permissions(administrator=True)
async def bind_shop_orders(interaction: discord.Interaction, send_to: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    set_shop_orders_channel_id(guild_id=interaction.guild.id, channel_id=send_to.id)
    await interaction.response.send_message(
        f"Готово. Теперь покупки из магазина будут отправляться в {send_to.mention}.",
        ephemeral=True,
    )


@bot.tree.command(name="настройка-магазина", description="Открыть всплывающую панель управления товарами магазина")
@app_commands.default_permissions(administrator=True)
async def shop_manage_panel(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    e = discord.Embed(
        title="— ・ Настройка магазина",
        description=(
            "Выбери **действие** во втором списке.\n"
            "Для `изменить`/`удалить` сначала выбери **товар** в первом списке."
        ),
        color=discord.Color.dark_gray(),
    )
    await interaction.response.send_message(embed=e, view=ShopManageView(guild_id=interaction.guild.id), ephemeral=True)


@bot.tree.command(name="настройка-ивентов", description="Открыть всплывающую панель настройки ивентов")
@app_commands.default_permissions(administrator=True)
async def events_manage_panel(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    current = _get_report_types_for_guild(interaction.guild.id)
    if not current:
        await interaction.response.send_message("Список ивентов пуст. Добавь через `/ивент-добавить`.", ephemeral=True)
        return
    e = discord.Embed(
        title="— ・ Настройка ивентов",
        description=(
            "Выбери **действие** во втором списке.\n"
            "Для `изменить`/`удалить` сначала выбери **ивент** в первом списке."
        ),
        color=discord.Color.dark_gray(),
    )
    await interaction.response.send_message(embed=e, view=EventsManageView(guild_id=interaction.guild.id), ephemeral=True)


@bot.tree.command(name="привязка-промо", description="Выбрать канал, куда будут отправляться промокоды на проверку")
@app_commands.describe(send_to="Канал, куда бот будет отправлять промокоды")
@app_commands.default_permissions(administrator=True)
async def bind_promo(interaction: discord.Interaction, send_to: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    set_promo_channel_id(guild_id=interaction.guild.id, channel_id=send_to.id)
    await interaction.response.send_message(
        f"Готово. Теперь промокоды будут отправляться в {send_to.mention}.",
        ephemeral=True,
    )


@bot.tree.command(name="привязка-стрима", description="Выбрать канал для оповещений о начале стрима")
@app_commands.describe(send_to="Канал, куда бот будет писать про старт стрима")
@app_commands.default_permissions(administrator=True)
async def bind_stream_announce(interaction: discord.Interaction, send_to: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    set_stream_announce_channel_id(guild_id=interaction.guild.id, channel_id=send_to.id)
    await interaction.response.send_message(
        f"Готово. Теперь при старте стрима бот будет писать в {send_to.mention}.",
        ephemeral=True,
    )


@bot.tree.command(name="настройка-стримеров", description="Кого анонсить при старте стрима")
@app_commands.describe(
    действие="Что сделать (добавить/убрать/список/очистить)",
    пользователь="Пользователь (нужно только для добавить/убрать)",
)
@app_commands.default_permissions(administrator=True)
@app_commands.choices(
    действие=[
        app_commands.Choice(name="добавить", value="add"),
        app_commands.Choice(name="убрать", value="remove"),
        app_commands.Choice(name="список", value="list"),
        app_commands.Choice(name="очистить", value="clear"),
    ]
)
async def configure_streamers(
    interaction: discord.Interaction,
    действие: app_commands.Choice[str],
    пользователь: discord.Member | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    guild = interaction.guild
    user_ids = get_stream_announce_user_ids(guild_id=guild.id)

    if действие.value == "list":
        pretty = " ".join(f"<@{uid}>" for uid in user_ids) if user_ids else "—"
        await interaction.response.send_message(f"Кого анонсить при старте стрима: {pretty}", ephemeral=True)
        return

    if действие.value == "clear":
        set_stream_announce_user_ids(guild_id=guild.id, user_ids=[])
        await interaction.response.send_message("Готово. Список стримеров очищен.", ephemeral=True)
        return

    if пользователь is None:
        await interaction.response.send_message("Выбери пользователя в параметре `пользователь`.", ephemeral=True)
        return

    if действие.value == "add":
        if пользователь.id not in user_ids:
            user_ids.append(пользователь.id)
            set_stream_announce_user_ids(guild_id=guild.id, user_ids=user_ids)
        pretty = " ".join(f"<@{uid}>" for uid in user_ids) if user_ids else "—"
        await interaction.response.send_message(
            f"Готово. Добавлен {пользователь.mention}. Теперь анонс для: {pretty}",
            ephemeral=True,
        )
        return

    if действие.value == "remove":
        if пользователь.id in user_ids:
            user_ids = [uid for uid in user_ids if uid != пользователь.id]
            set_stream_announce_user_ids(guild_id=guild.id, user_ids=user_ids)
        pretty = " ".join(f"<@{uid}>" for uid in user_ids) if user_ids else "—"
        await interaction.response.send_message(
            f"Готово. Убран {пользователь.mention}. Теперь анонс для: {pretty}",
            ephemeral=True,
        )
        return

    await interaction.response.send_message("Неизвестное действие.", ephemeral=True)


@bot.tree.command(name="настройка-твич-стримеров", description="Привязать Twitch-логин к конкретному пользователю")
@app_commands.describe(
    действие="Что сделать (добавить/убрать/список/очистить)",
    пользователь="Пользователь (для добавить/убрать)",
    twitch_login="Логин на Twitch или ссылка на канал (для добавить)",
)
@app_commands.default_permissions(administrator=True)
@app_commands.choices(
    действие=[
        app_commands.Choice(name="добавить", value="add"),
        app_commands.Choice(name="убрать", value="remove"),
        app_commands.Choice(name="список", value="list"),
        app_commands.Choice(name="очистить", value="clear"),
    ]
)
async def configure_twitch_streamers(
    interaction: discord.Interaction,
    действие: app_commands.Choice[str],
    пользователь: discord.Member | None = None,
    twitch_login: str | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    guild = interaction.guild
    twitch_map = get_stream_announce_twitch_map(guild_id=guild.id)

    if действие.value == "list":
        if not twitch_map:
            await interaction.response.send_message("Список Twitch-привязок пуст.", ephemeral=True)
            return
        lines = [f"<@{uid}> -> `{login}`" for uid, login in twitch_map.items()]
        await interaction.response.send_message("Twitch-привязки:\n" + "\n".join(lines[:25]), ephemeral=True)
        return

    if действие.value == "clear":
        set_stream_announce_twitch_map(guild_id=guild.id, mapping={})
        await interaction.response.send_message("Готово. Twitch-привязки очищены.", ephemeral=True)
        return

    if пользователь is None:
        await interaction.response.send_message("Выбери пользователя в параметре `пользователь`.", ephemeral=True)
        return

    if действие.value == "remove":
        if пользователь.id in twitch_map:
            twitch_map.pop(пользователь.id, None)
            set_stream_announce_twitch_map(guild_id=guild.id, mapping=twitch_map)
        await interaction.response.send_message(f"Готово. Twitch-привязка для {пользователь.mention} удалена.", ephemeral=True)
        return

    if действие.value == "add":
        login = _normalize_twitch_login(twitch_login or "")
        if not login:
            await interaction.response.send_message("Укажи корректный `twitch_login` (например `nickname`).", ephemeral=True)
            return
        twitch_map[пользователь.id] = login
        set_stream_announce_twitch_map(guild_id=guild.id, mapping=twitch_map)
        allowed = get_stream_announce_user_ids(guild_id=guild.id)
        if пользователь.id not in allowed:
            allowed.append(пользователь.id)
            set_stream_announce_user_ids(guild_id=guild.id, user_ids=allowed)
        await interaction.response.send_message(
            f"Готово. {пользователь.mention} привязан к Twitch: `https://twitch.tv/{login}`",
            ephemeral=True,
        )
        return

    await interaction.response.send_message("Неизвестное действие.", ephemeral=True)

@bot.tree.command(name="панель-промо", description="Отправить панель промокодов в выбранный канал")
@app_commands.describe(panel_channel="Канал, куда отправить панель промокодов")
@app_commands.default_permissions(administrator=True)
async def promo_panel(interaction: discord.Interaction, panel_channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    f = _promo_image_file()
    embed = build_promo_panel_embed(with_image=(f is not None))
    view = PromoPanelView()
    existing = get_promo_panel_message_id(guild_id=interaction.guild.id)
    edited = False
    if existing and existing[0] == panel_channel.id:
        try:
            old_msg = await panel_channel.fetch_message(existing[1])
            await old_msg.edit(embed=embed, view=view)
            edited = True
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            edited = False

    if not edited:
        if f is not None:
            msg = await panel_channel.send(embed=embed, view=view, file=f)
        else:
            msg = await panel_channel.send(embed=embed, view=view)
        set_promo_panel_message_id(guild_id=interaction.guild.id, channel_id=panel_channel.id, message_id=msg.id)

    await interaction.followup.send(
        f"Панель промокодов {'обновлена' if edited else 'отправлена'} в {panel_channel.mention}.",
        ephemeral=True,
    )


@app_commands.describe(
    действие="Что сделать",
    товар="Название товара (для добавить/изменить/удалить)",
    цена="Цена товара (для добавить/изменить)",
)
@app_commands.default_permissions(administrator=True)
@app_commands.choices(
    действие=[
        app_commands.Choice(name="показать", value="list"),
        app_commands.Choice(name="добавить", value="add"),
        app_commands.Choice(name="изменить", value="update"),
        app_commands.Choice(name="удалить", value="remove"),
        app_commands.Choice(name="сбросить", value="reset"),
    ]
)
async def _shop_settings_legacy(
    interaction: discord.Interaction,
    действие: app_commands.Choice[str],
    товар: str | None = None,
    цена: int | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    action = действие.value
    current = _get_shop_items_for_guild(guild_id)

    if action == "list":
        lines = [f"{idx}. {name} — {price}" for idx, (name, price) in enumerate(current, start=1)]
        await interaction.response.send_message(
            "Товары магазина:\n" + ("\n".join(lines) if lines else "—"),
            ephemeral=True,
        )
        return

    if action == "reset":
        set_shop_items(
            guild_id=guild_id,
            items=[{"name": name, "price": price} for name, price in DEFAULT_SHOP_ITEMS],
        )
        updated_panel = await _refresh_shop_panel_message(guild=interaction.guild)
        await interaction.response.send_message(
            "Готово. Магазин сброшен к стандартным товарам."
            + (" Панель обновлена автоматически." if updated_panel else ""),
            ephemeral=True,
        )
        return

    item_name = (товар or "").strip()
    if not item_name:
        await interaction.response.send_message("Укажи параметр `товар`.", ephemeral=True)
        return

    if action in {"add", "update"}:
        if цена is None or int(цена) <= 0:
            await interaction.response.send_message("Укажи параметр `цена` (> 0).", ephemeral=True)
            return
        updated = list(current)
        found_idx: int | None = None
        for i, (name, _) in enumerate(updated):
            if name.casefold() == item_name.casefold():
                found_idx = i
                break
        if action == "add":
            if found_idx is not None:
                await interaction.response.send_message("Такой товар уже есть. Используй действие `изменить`.", ephemeral=True)
                return
            updated.append((item_name[:100], int(цена)))
        else:
            if found_idx is None:
                await interaction.response.send_message("Товар не найден. Используй действие `добавить`.", ephemeral=True)
                return
            updated[found_idx] = (updated[found_idx][0], int(цена))
        set_shop_items(
            guild_id=guild_id,
            items=[{"name": name, "price": price} for name, price in updated],
        )
        updated_panel = await _refresh_shop_panel_message(guild=interaction.guild)
        await interaction.response.send_message(
            "Готово. Магазин обновлён." + (" Панель обновлена автоматически." if updated_panel else ""),
            ephemeral=True,
        )
        return

    if action == "remove":
        updated = [(name, price) for name, price in current if name.casefold() != item_name.casefold()]
        if len(updated) == len(current):
            await interaction.response.send_message("Товар не найден.", ephemeral=True)
            return
        set_shop_items(
            guild_id=guild_id,
            items=[{"name": name, "price": price} for name, price in updated],
        )
        updated_panel = await _refresh_shop_panel_message(guild=interaction.guild)
        await interaction.response.send_message(
            "Товар удалён." + (" Панель обновлена автоматически." if updated_panel else ""),
            ephemeral=True,
        )
        return

    await interaction.response.send_message("Неизвестное действие.", ephemeral=True)


@bot.tree.command(name="товар-изменить", description="Изменить цену товара через выбор из списка")
@app_commands.describe(
    товар="Начни вводить название и выбери из списка",
    цена="Новая цена",
)
@app_commands.default_permissions(administrator=True)
@app_commands.autocomplete(товар=_shop_item_autocomplete)
async def shop_item_update_simple(
    interaction: discord.Interaction,
    товар: str,
    цена: int,
):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    item_name = (товар or "").strip()
    if not item_name:
        await interaction.response.send_message("Выбери `товар`.", ephemeral=True)
        return
    if int(цена) <= 0:
        await interaction.response.send_message("Укажи `цена` (> 0).", ephemeral=True)
        return

    guild_id = interaction.guild.id
    current = _get_shop_items_for_guild(guild_id)
    updated = list(current)
    found_idx: int | None = None
    for i, (name, _) in enumerate(updated):
        if name.casefold() == item_name.casefold():
            found_idx = i
            break
    if found_idx is None:
        await interaction.response.send_message("Товар не найден (возможно уже удалён).", ephemeral=True)
        return

    updated[found_idx] = (updated[found_idx][0], int(цена))
    set_shop_items(guild_id=guild_id, items=[{"name": name, "price": price} for name, price in updated])
    updated_panel = await _refresh_shop_panel_message(guild=interaction.guild)
    await interaction.response.send_message(
        f"Готово. Цена обновлена: **{updated[found_idx][0]}** — **{int(цена)}**"
        + (" Панель обновлена автоматически." if updated_panel else ""),
        ephemeral=True,
    )


@bot.tree.command(name="товар-удалить", description="Удалить товар через выбор из списка")
@app_commands.describe(товар="Начни вводить название и выбери из списка")
@app_commands.default_permissions(administrator=True)
@app_commands.autocomplete(товар=_shop_item_autocomplete)
async def shop_item_remove_simple(
    interaction: discord.Interaction,
    товар: str,
):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    item_name = (товар or "").strip()
    if not item_name:
        await interaction.response.send_message("Выбери `товар`.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    current = _get_shop_items_for_guild(guild_id)
    updated = [(name, price) for name, price in current if name.casefold() != item_name.casefold()]
    if len(updated) == len(current):
        await interaction.response.send_message("Товар не найден (возможно уже удалён).", ephemeral=True)
        return

    set_shop_items(guild_id=guild_id, items=[{"name": name, "price": price} for name, price in updated])
    updated_panel = await _refresh_shop_panel_message(guild=interaction.guild)
    await interaction.response.send_message(
        f"Готово. Товар удалён: **{item_name}**" + (" Панель обновлена автоматически." if updated_panel else ""),
        ephemeral=True,
    )


@bot.tree.command(name="привязка-категория-обзвона", description="Выбрать категорию, где будут создаваться каналы обзвона")
@app_commands.describe(category="Категория для каналов обзвона (форум/категория)")
@app_commands.default_permissions(administrator=True)
async def bind_call_category(interaction: discord.Interaction, category: discord.CategoryChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    set_call_category_id(guild_id=interaction.guild.id, category_id=category.id)
    await interaction.response.send_message(
        f"Готово. Теперь каналы обзвона будут создаваться в категории {category.name}.",
        ephemeral=True,
    )


@bot.tree.command(name="привязка-тег-роль-лс", description="Привязать категорию и роль для ЛС-уведомлений при теге роли")
@app_commands.describe(
    действие="Что сделать с привязкой",
    category="Категория, где бот отслеживает тег роли",
    роль="Роль, при теге которой бот отправляет ЛС",
)
@app_commands.choices(
    действие=[
        app_commands.Choice(name="Показать текущую", value="show"),
        app_commands.Choice(name="Установить/обновить", value="set"),
        app_commands.Choice(name="Очистить", value="clear"),
    ]
)
@app_commands.default_permissions(administrator=True)
async def bind_role_ping_notify(
    interaction: discord.Interaction,
    действие: app_commands.Choice[str],
    category: discord.CategoryChannel | None = None,
    роль: discord.Role | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    guild_id = interaction.guild.id
    action = действие.value

    if action == "show":
        current = get_role_ping_notify_binding(guild_id=guild_id)
        if not current:
            await interaction.followup.send("Привязка тега роли для ЛС ещё не настроена.", ephemeral=True)
            return
        category_id, role_id = current
        await interaction.followup.send(
            f"Текущая привязка: категория <#{category_id}> + роль <@&{role_id}>.",
            ephemeral=True,
        )
        return

    if action == "clear":
        set_role_ping_notify_binding(guild_id=guild_id, category_id=None, role_id=None)
        await interaction.followup.send("Готово. Привязка категории и роли очищена.", ephemeral=True)
        return

    if category is None or роль is None:
        await interaction.followup.send("Для установки укажи и `category`, и `роль`.", ephemeral=True)
        return

    set_role_ping_notify_binding(guild_id=guild_id, category_id=category.id, role_id=роль.id)
    await interaction.followup.send(
        f"Готово. При теге {роль.mention} в категории {category.name} бот отправит ЛС участникам роли.",
        ephemeral=True,
    )


@bot.tree.command(name="привязка-розыгрыш-тег-лс", description="Настроить роли: тег в канале и ЛС-уведомления при старте розыгрыша")
@app_commands.describe(
    действие="Что сделать с ролями розыгрыша",
    роль="Роль (нужна только для добавить/убрать)",
)
@app_commands.choices(
    действие=[
        app_commands.Choice(name="Показать роли", value="show"),
        app_commands.Choice(name="Добавить роль", value="add"),
        app_commands.Choice(name="Убрать роль", value="remove"),
        app_commands.Choice(name="Очистить все", value="clear"),
    ]
)
@app_commands.default_permissions(administrator=True)
async def bind_giveaway_notify_roles(
    interaction: discord.Interaction,
    действие: app_commands.Choice[str],
    роль: discord.Role | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    action = действие.value
    role_ids = get_giveaway_notify_role_ids(guild_id=guild_id)

    if action == "show":
        if not role_ids:
            await interaction.response.send_message("Роли для розыгрыша ещё не настроены.", ephemeral=True)
            return
        shown = role_ids[:20]
        tail = f"\n…и ещё {len(role_ids) - len(shown)}" if len(role_ids) > len(shown) else ""
        await interaction.response.send_message(
            "Роли для тега/ЛС при старте розыгрыша:\n" + " ".join(f"<@&{rid}>" for rid in shown) + tail,
            ephemeral=True,
        )
        return

    if action == "clear":
        set_giveaway_notify_role_ids(guild_id=guild_id, role_ids=[])
        await interaction.response.send_message("Готово. Роли для розыгрыша очищены.", ephemeral=True)
        return

    if роль is None:
        await interaction.response.send_message("Выбери роль в параметре `роль`.", ephemeral=True)
        return

    if action == "add":
        if роль.id not in role_ids:
            role_ids.append(роль.id)
            set_giveaway_notify_role_ids(guild_id=guild_id, role_ids=role_ids)
        await interaction.response.send_message(
            f"Готово. Роль {роль.mention} добавлена в уведомления розыгрыша.",
            ephemeral=True,
        )
        return

    if action == "remove":
        if роль.id in role_ids:
            role_ids = [rid for rid in role_ids if rid != роль.id]
            set_giveaway_notify_role_ids(guild_id=guild_id, role_ids=role_ids)
        await interaction.response.send_message(
            f"Готово. Роль {роль.mention} убрана из уведомлений розыгрыша.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message("Неизвестное действие.", ephemeral=True)


@bot.tree.command(name="привязка-приват-войса", description="Выбрать голосовой канал-лобби: вход создаёт личную комнату")
@app_commands.describe(channel="Лобби приват-войсов: заход сюда создаёт личный голосовой канал")
@app_commands.default_permissions(administrator=True)
async def bind_voice_lobby(interaction: discord.Interaction, channel: discord.VoiceChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    set_voice_lobby_channel_id(guild_id=interaction.guild.id, channel_id=channel.id)
    await interaction.response.send_message(
        f"Готово. Лобби приват-войсов: {channel.mention}.",
        ephemeral=True,
    )


@bot.tree.command(
    name="панель-приват-хаб",
    description="Отправить панель управления приватными войсами (текстовый канал)",
)
@app_commands.describe(panel_channel="Канал для панели с кнопками")
@app_commands.default_permissions(administrator=True)
async def private_voice_hub_panel(interaction: discord.Interaction, panel_channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    guild = interaction.guild
    me = guild.me
    if me is None or not panel_channel.permissions_for(me).send_messages or not panel_channel.permissions_for(me).embed_links:
        await interaction.response.send_message(
            f"В {panel_channel.mention} боту нужны **отправка сообщений** и **встраивание ссылок**.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)
    embed = _build_private_voice_hub_embed()
    view = PrivateVoiceHubView()
    existing = get_voice_hub_panel_message_id(guild_id=guild.id)
    edited = False
    msg: discord.Message
    if existing and existing[0] == panel_channel.id:
        try:
            old_msg = await panel_channel.fetch_message(existing[1])
            await old_msg.edit(embed=embed, view=view)
            edited = True
            msg = old_msg
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            edited = False

    if not edited:
        msg = await panel_channel.send(embed=embed, view=view)

    set_voice_hub_panel_message_id(guild_id=guild.id, channel_id=panel_channel.id, message_id=msg.id)
    await interaction.followup.send(
        f"Панель приват-хаба {'обновлена' if edited else 'отправлена'} в {panel_channel.mention}.",
        ephemeral=True,
    )


@bot.tree.command(name="привязка-категория-портфелей", description="Выбрать категорию, где будут создаваться личные каналы портфеля")
@app_commands.describe(category="Категория для каналов портфеля")
@app_commands.default_permissions(administrator=True)
async def bind_portfolio_category(interaction: discord.Interaction, category: discord.CategoryChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    set_portfolio_category_id(guild_id=interaction.guild.id, category_id=category.id)
    await interaction.response.send_message(
        f"Готово. Теперь личные каналы портфеля будут создаваться в категории {category.name}.",
        ephemeral=True,
    )


@bot.tree.command(name="панель-портфеля", description="Отправить панель создания портфеля в выбранный канал")
@app_commands.describe(panel_channel="Канал, куда отправить панель портфеля")
@app_commands.default_permissions(administrator=True)
async def portfolio_panel(interaction: discord.Interaction, panel_channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    f = _portfolio_image_file()
    embed = _build_portfolio_embed(with_image=(f is not None))
    view = PortfolioPanelView()
    if f is not None:
        await panel_channel.send(embed=embed, view=view, file=f)
    else:
        await panel_channel.send(embed=embed, view=view)
    await interaction.followup.send(f"Панель портфеля отправлена в {panel_channel.mention}.", ephemeral=True)


@bot.tree.command(name="панель-отчетов", description="Отправить панель отчётов в выбранный канал")
@app_commands.describe(panel_channel="Канал, куда отправить панель отчётов")
@app_commands.default_permissions(administrator=True)
async def reports_panel(interaction: discord.Interaction, panel_channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    # Важно: отправка embed + файла может занять >3s, поэтому сразу подтверждаем interaction.
    await interaction.response.defer(ephemeral=True)

    f = _report_image_file()
    embed = _build_report_embed(guild_id=interaction.guild.id, with_image=(f is not None))
    view = ReportPanelView(guild_id=interaction.guild.id)
    existing = get_reports_panel_message_id(guild_id=interaction.guild.id)
    edited = False
    if existing and existing[0] == panel_channel.id:
        try:
            old_msg = await panel_channel.fetch_message(existing[1])
            await old_msg.edit(embed=embed, view=view)
            edited = True
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            edited = False

    if not edited:
        if f is not None:
            msg = await panel_channel.send(embed=embed, view=view, file=f)
        else:
            msg = await panel_channel.send(embed=embed, view=view)
        set_reports_panel_message_id(guild_id=interaction.guild.id, channel_id=panel_channel.id, message_id=msg.id)

    await interaction.followup.send(
        f"Панель отчётов {'обновлена' if edited else 'отправлена'} в {panel_channel.mention}.",
        ephemeral=True,
    )


@bot.tree.command(name="панель-взх", description="Отправить отдельную панель отчета ВЗХ")
@app_commands.describe(panel_channel="Канал, куда отправить панель ВЗХ")
@app_commands.default_permissions(administrator=True)
async def report_vzh_panel(interaction: discord.Interaction, panel_channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    embed = _build_quick_panel_embed("Отчёт: ВЗХ")
    await panel_channel.send(embed=embed, view=ReportVzhPanelView())
    await interaction.response.send_message(f"Панель ВЗХ отправлена в {panel_channel.mention}.", ephemeral=True)


@bot.tree.command(name="панель-мп", description="Отправить отдельную панель отчета МП")
@app_commands.describe(panel_channel="Канал, куда отправить панель МП")
@app_commands.default_permissions(administrator=True)
async def report_mp_panel(interaction: discord.Interaction, panel_channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    embed = _build_quick_panel_embed("Отчёт: МП")
    await panel_channel.send(embed=embed, view=ReportMpPanelView())
    await interaction.response.send_message(f"Панель МП отправлена в {panel_channel.mention}.", ephemeral=True)


@bot.tree.command(name="панель-атт-дефф", description="Отправить панель ATT/DEFF с текущим КД")
@app_commands.describe(panel_channel="Канал, куда отправить панель ATT/DEFF")
@app_commands.default_permissions(administrator=True)
async def attack_def_panel(interaction: discord.Interaction, panel_channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    embed = _build_attack_def_embed(guild_id=interaction.guild.id)
    view = AttackDefCooldownView()
    existing = get_attack_def_panel_message_id(guild_id=interaction.guild.id)
    edited = False
    if existing and existing[0] == panel_channel.id:
        try:
            old_msg = await panel_channel.fetch_message(existing[1])
            await old_msg.edit(embed=embed, view=view)
            edited = True
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            edited = False
    if not edited:
        msg = await panel_channel.send(embed=embed, view=view)
        set_attack_def_panel_message_id(guild_id=interaction.guild.id, channel_id=panel_channel.id, message_id=msg.id)

    await interaction.followup.send(
        f"Панель ATT/DEFF {'обновлена' if edited else 'отправлена'} в {panel_channel.mention}.",
        ephemeral=True,
    )


@bot.tree.command(name="настройка-кд", description="Настроить длительность КД для ATT/DEFF")
@app_commands.describe(
    тип="Какой КД настраиваем",
    минуты="Сколько минут КД (если не указано, просто покажет текущее значение)",
)
@app_commands.choices(
    тип=[
        app_commands.Choice(name="ATT", value="att"),
        app_commands.Choice(name="DEFF", value="deff"),
    ]
)
@app_commands.default_permissions(administrator=True)
async def configure_attack_def_cooldown(
    interaction: discord.Interaction,
    тип: app_commands.Choice[str],
    минуты: app_commands.Range[int, 1, 10080] | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    guild_id = interaction.guild.id
    cfg = get_attack_def_cooldown_config(guild_id=guild_id)

    if минуты is None:
        current = int(cfg.get("att_minutes" if тип.value == "att" else "deff_minutes", 120))
        await interaction.followup.send(f"Текущий КД для {тип.name}: **{current} мин**.", ephemeral=True)
        return

    if тип.value == "att":
        set_attack_def_cooldown_config(guild_id=guild_id, att_minutes=int(минуты))
    else:
        set_attack_def_cooldown_config(guild_id=guild_id, deff_minutes=int(минуты))

    refreshed = await _refresh_attack_def_panel_message(guild=interaction.guild)
    await interaction.followup.send(
        f"Готово. КД для {тип.name} установлен: **{int(минуты)} мин**."
        + (" Панель обновлена автоматически." if refreshed else ""),
        ephemeral=True,
    )


@bot.tree.command(name="панель-контрактов", description="Отправить панель заявок на контракты в выбранный канал")
@app_commands.describe(panel_channel="Канал, куда отправить панель контрактов")
@app_commands.default_permissions(administrator=True)
async def contracts_panel(interaction: discord.Interaction, panel_channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    embed = _build_contracts_panel_embed()
    view = ContractsPanelView()
    existing = get_contracts_panel_message_id(guild_id=interaction.guild.id)
    edited = False
    if existing and existing[0] == panel_channel.id:
        try:
            old_msg = await panel_channel.fetch_message(existing[1])
            await old_msg.edit(embed=embed, view=view)
            edited = True
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            edited = False
    if not edited:
        msg = await panel_channel.send(embed=embed, view=view)
        set_contracts_panel_message_id(guild_id=interaction.guild.id, channel_id=panel_channel.id, message_id=msg.id)

    await interaction.followup.send(
        f"Панель контрактов {'обновлена' if edited else 'отправлена'} в {panel_channel.mention}.",
        ephemeral=True,
    )


@bot.tree.command(name="баланс", description="Показать баланс баллов пользователя")
@app_commands.describe(пользователь="Если не указан, покажет ваш баланс")
async def points_balance(interaction: discord.Interaction, пользователь: discord.Member | None = None):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    if пользователь is not None and пользователь.id != interaction.user.id:
        actor = interaction.user if isinstance(interaction.user, discord.Member) else None
        if actor is None or not actor.guild_permissions.administrator:
            await interaction.response.send_message(
                "Чужой баланс может смотреть только **администратор**.",
                ephemeral=True,
            )
            return
    target = пользователь or interaction.user
    points = get_user_points(guild_id=interaction.guild.id, user_id=target.id)
    await interaction.response.send_message(
        f"Баланс {target.mention}: **{_fmt_points(points)}**",
        ephemeral=True,
    )


@bot.tree.command(name="баллы-выдать", description="Выдать или списать баллы пользователю")
@app_commands.describe(пользователь="Кому изменить баланс", количество="Положительное число - выдать, отрицательное - списать")
@app_commands.default_permissions(administrator=True)
async def points_grant(interaction: discord.Interaction, пользователь: discord.Member, количество: float):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    new_balance = add_user_points(guild_id=interaction.guild.id, user_id=пользователь.id, delta=количество)
    await interaction.response.send_message(
        f"Готово. Новый баланс {пользователь.mention}: **{_fmt_points(new_balance)}**",
        ephemeral=True,
    )


@bot.tree.command(name="баллы-лог", description="Лог баллов: сколько у кого очков")
@app_commands.default_permissions(administrator=True)
async def points_log(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    points_map = get_points_map(guild_id=interaction.guild.id)
    if not points_map:
        await interaction.response.send_message("Лог баллов пуст.", ephemeral=True)
        return

    ranked = sorted(points_map.items(), key=lambda x: x[1], reverse=True)
    lines: list[str] = []
    for uid, bal in ranked[:50]:
        lines.append(f"<@{uid}> — **{_fmt_points(bal)}**")
    await interaction.response.send_message(
        "Лог баллов (топ 50):\n" + "\n".join(lines),
        ephemeral=True,
    )


@bot.tree.command(name="карты-взп", description="Панель выбора карт VZP")
@app_commands.default_permissions(administrator=True)
async def vzp_maps_panel(interaction: discord.Interaction):
    if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    await interaction.channel.send(embed=_build_vzp_embed(), view=VzpMapView())
    await interaction.response.send_message("Панель VZP отправлена в канал.", ephemeral=True)


@bot.tree.command(name="настройка-роль-принять", description="Настроить роль, которую выдавать при принятии заявки")
@app_commands.describe(
    действие="Что сделать (установить/очистить/показать)",
    тип="Для какого типа заявки настраиваем роль",
    роль="Роль для выдачи при принятии (нужно только для 'установить')",
)
@app_commands.default_permissions(administrator=True)
@app_commands.choices(
    действие=[
        app_commands.Choice(name="установить", value="set"),
        app_commands.Choice(name="очистить", value="clear"),
#         app_commands.Choice(name="показать", value="show"),
    ]
)
@app_commands.choices(
    тип=[
        app_commands.Choice(name="RP", value="RP"),
        app_commands.Choice(name="VZP", value="VZP"),
        app_commands.Choice(name="Capt/Biz", value="CAPT_BIZ"),
    ]
)
async def configure_accept_role(
    interaction: discord.Interaction,
    действие: app_commands.Choice[str],
    тип: app_commands.Choice[str],
    роль: discord.Role | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    guild = interaction.guild
    # Подтверждаем interaction заранее, чтобы не ловить Unknown interaction.
    await interaction.response.defer(ephemeral=True)

    if действие.value == "show":
        from storage import get_accept_role_id_for_type

        rid = get_accept_role_id_for_type(guild_id=guild.id, application_type=тип.value)
        pretty = f"<@&{rid}>" if rid else "—"
        await interaction.followup.send(
            f"Роль для выдачи при принятии ({тип.name}): {pretty}",
            ephemeral=True,
        )
        return

    if действие.value == "clear":
        from storage import set_accept_role_id_for_type

        set_accept_role_id_for_type(guild_id=guild.id, application_type=тип.value, role_id=None)
        await interaction.followup.send(
            f"Готово. Роль для выдачи при принятии ({тип.name}) очищена.",
            ephemeral=True,
        )
        return

    if действие.value == "set":
        if роль is None:
            await interaction.followup.send("Выбери роль в параметре `роль`.", ephemeral=True)
            return
        from storage import set_accept_role_id_for_type

        set_accept_role_id_for_type(guild_id=guild.id, application_type=тип.value, role_id=роль.id)
        await interaction.followup.send(
            f"Готово. При принятии ({тип.name}) будет выдаваться роль {роль.mention}.",
            ephemeral=True,
        )
        return

    await interaction.followup.send("Неизвестное действие.", ephemeral=True)


@bot.tree.command(name="сводка-команд", description="Показать все текущие привязки (каналы/категории/роли)")
@app_commands.default_permissions(administrator=True)
async def bindings_summary(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    guild = interaction.guild

    def _ch(cid: int | None) -> str:
        return f"<#{cid}>" if cid else "—"

    def _role(rid: int | None) -> str:
        return f"<@&{rid}>" if rid else "—"

    def _role_list(rids: list[int]) -> str:
        rids = [int(x) for x in (rids or []) if x]
        if not rids:
            return "—"
        shown = rids[:15]
        tail = f"\n…и ещё {len(rids) - len(shown)}" if len(rids) > len(shown) else ""
        return " ".join(f"<@&{rid}>" for rid in shown) + tail

    def _panel_tuple(t: tuple[int, int] | None) -> str:
        if not t:
            return "—"
        ch_id, msg_id = t
        return f"<#{ch_id}> • `{msg_id}`"

    from storage import (
        get_destination_channel_id,
        get_reports_channel_id,
        get_logs_channel_id,
        get_shop_orders_channel_id,
        get_promo_channel_id,
        get_stream_announce_channel_id,
        get_giveaway_notify_role_ids,
        get_stream_announce_user_ids,
        get_stream_announce_twitch_map,
        get_call_category_id,
        get_role_ping_notify_binding,
        get_voice_lobby_channel_id,
        get_portfolio_category_id,
        get_tier_role_id,
        get_rank_role_id,
        get_ticket_view_role_ids,
        get_vacation_channel_id,
        get_vacation_role_id,
        get_vacation_remove_role_ids,
        get_accept_role_id_for_type,
        get_panel_message_id,
        get_reports_panel_message_id,
        get_shop_panel_message_id,
        get_promo_panel_message_id,
        get_afk_panel_message_id,
        get_vacation_panel_message_id,
        get_attack_def_cooldown_config,
        get_attack_def_panel_message_id,
        get_contracts_panel_message_id,
        get_voice_hub_panel_message_id,
    )

    fields: list[tuple[str, str]] = []

    fields.append(("Заявки → канал", _ch(get_destination_channel_id(guild_id=guild.id))))
    fields.append(("Отчёты → канал", _ch(get_reports_channel_id(guild_id=guild.id))))
    fields.append(("Логи → канал", _ch(get_logs_channel_id(guild_id=guild.id))))
    fields.append(("Магазин → канал проверок", _ch(get_shop_orders_channel_id(guild_id=guild.id))))
    fields.append(("Промо → канал проверок", _ch(get_promo_channel_id(guild_id=guild.id))))
    fields.append(("Стрим → канал анонса", _ch(get_stream_announce_channel_id(guild_id=guild.id))))
    fields.append(("Розыгрыш → роли тега/ЛС", _role_list(get_giveaway_notify_role_ids(guild_id=guild.id))))
    fields.append(("Отпуска → канал логов", _ch(get_vacation_channel_id(guild_id=guild.id))))
    fields.append(("Обзвон → категория", _ch(get_call_category_id(guild_id=guild.id))))
    role_ping_binding = get_role_ping_notify_binding(guild_id=guild.id)
    if role_ping_binding:
        bind_category_id, bind_role_id = role_ping_binding
        fields.append(("Тег роли в категории → ЛС", f"<#{bind_category_id}> + <@&{bind_role_id}>"))
    else:
        fields.append(("Тег роли в категории → ЛС", "—"))
    fields.append(("Приват-войсы → лобби", _ch(get_voice_lobby_channel_id(guild_id=guild.id))))
    fields.append(("Портфели → категория", _ch(get_portfolio_category_id(guild_id=guild.id))))

    fields.append(("Тир 1/2/3 роли", f"{_role(get_tier_role_id(guild_id=guild.id, tier=1))} {_role(get_tier_role_id(guild_id=guild.id, tier=2))} {_role(get_tier_role_id(guild_id=guild.id, tier=3))}"))
    fields.append(("Ранг 1/2 роли", f"{_role(get_rank_role_id(guild_id=guild.id, rank=1))} {_role(get_rank_role_id(guild_id=guild.id, rank=2))}"))
    fields.append(("Роль при принятии (RP)", _role(get_accept_role_id_for_type(guild_id=guild.id, application_type="RP"))))
    fields.append(("Роль при принятии (VZP)", _role(get_accept_role_id_for_type(guild_id=guild.id, application_type="VZP"))))
    fields.append(("Роль при принятии (Capt/Biz)", _role(get_accept_role_id_for_type(guild_id=guild.id, application_type="CAPT_BIZ"))))
    fields.append(("Смотреть тикеты (роли)", _role_list(get_ticket_view_role_ids(guild_id=guild.id))))
    fields.append(("Роль отпуска", _role(get_vacation_role_id(guild_id=guild.id))))
    fields.append(("Снимать роли в отпуск (список)", _role_list(get_vacation_remove_role_ids(guild_id=guild.id))))
    attack_def_cfg = get_attack_def_cooldown_config(guild_id=guild.id)
    fields.append(
        (
            "КД ATT/DEFF (мин)",
            f"ATT: {int(attack_def_cfg.get('att_minutes', 120))} | DEFF: {int(attack_def_cfg.get('deff_minutes', 120))}",
        )
    )

    announce_users = get_stream_announce_user_ids(guild_id=guild.id)
    if announce_users:
        shown = announce_users[:15]
        tail = f"\n…и ещё {len(announce_users) - len(shown)}" if len(announce_users) > len(shown) else ""
        fields.append(("Стрим → кто анонсится", " ".join(f"<@{uid}>" for uid in shown) + tail))
    else:
        fields.append(("Стрим → кто анонсится", "—"))

    twitch_map = get_stream_announce_twitch_map(guild_id=guild.id)
    if twitch_map:
        pairs = [f"<@{uid}> → `{login}`" for uid, login in list(twitch_map.items())[:12]]
        more = f"\n…и ещё {len(twitch_map) - len(pairs)}" if len(twitch_map) > len(pairs) else ""
        fields.append(("Twitch-привязки", "\n".join(pairs) + more))
    else:
        fields.append(("Twitch-привязки", "—"))

    fields.append(("Панель заявок (сообщение)", _panel_tuple(get_panel_message_id(guild_id=guild.id))))
    fields.append(("Панель отчётов (сообщение)", _panel_tuple(get_reports_panel_message_id(guild_id=guild.id))))
    fields.append(("Панель магазина (сообщение)", _panel_tuple(get_shop_panel_message_id(guild_id=guild.id))))
    fields.append(("Панель промо (сообщение)", _panel_tuple(get_promo_panel_message_id(guild_id=guild.id))))
    fields.append(("AFK-панель (сообщение)", _panel_tuple(get_afk_panel_message_id(guild_id=guild.id))))
    fields.append(("Панель отпусков (сообщение)", _panel_tuple(get_vacation_panel_message_id(guild_id=guild.id))))
    fields.append(("Панель ATT/DEFF (сообщение)", _panel_tuple(get_attack_def_panel_message_id(guild_id=guild.id))))
    fields.append(("Панель контрактов (сообщение)", _panel_tuple(get_contracts_panel_message_id(guild_id=guild.id))))
    fields.append(("Панель приват-хаба (сообщение)", _panel_tuple(get_voice_hub_panel_message_id(guild_id=guild.id))))

    embeds: list[discord.Embed] = []
    chunk: list[tuple[str, str]] = []
    for name, value in fields:
        chunk.append((name, value))
        if len(chunk) >= 25:
            e = discord.Embed(title="Сводка привязок", color=discord.Color.dark_gray())
            for n, v in chunk:
                e.add_field(name=n, value=v or "—", inline=False)
            embeds.append(e)
            chunk = []
    if chunk:
        e = discord.Embed(title="Сводка привязок", color=discord.Color.dark_gray())
        for n, v in chunk:
            e.add_field(name=n, value=v or "—", inline=False)
        embeds.append(e)

    await interaction.response.send_message(embeds=embeds[:10], ephemeral=True)


class _DailyMessageTextModal(discord.ui.Modal):
    def __init__(self, *, guild_id: int):
        super().__init__(title="Ежедневное сообщение • Текст")
        self.guild_id = guild_id
        self.text = discord.ui.TextInput(
            label="Текст сообщения",
            placeholder="Что бот будет писать каждый день",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000,
        )
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        from storage import set_daily_message_config, set_daily_message_last_sent

        set_daily_message_config(guild_id=self.guild_id, text=str(self.text.value or "").strip())
        set_daily_message_last_sent(guild_id=self.guild_id, ymd=None)
        await interaction.response.send_message("Готово. Текст ежедневного сообщения сохранён.", ephemeral=True)
        await _try_refresh_daily_menu_message(interaction=interaction, guild_id=self.guild_id)


def _build_daily_message_embed(*, guild_id: int) -> discord.Embed:
    from storage import get_daily_message_config

    cfg = get_daily_message_config(guild_id=guild_id) or {}
    ch_id = int(cfg.get("channel_id") or 0) or None
    hour = cfg.get("hour")
    minute = cfg.get("minute")
    text = str(cfg.get("text") or "").strip()

    when = "—"
    if isinstance(hour, int) and isinstance(minute, int):
        when = f"{hour:02d}:{minute:02d} МСК"
    elif hour is not None and minute is not None:
        try:
            when = f"{int(hour):02d}:{int(minute):02d} МСК"
        except Exception:
            when = "—"

    e = discord.Embed(title="Ежедневное сообщение", color=discord.Color.dark_gray())
    e.add_field(name="Канал", value=(f"<#{ch_id}>" if ch_id else "—"), inline=False)
    e.add_field(name="Время", value=when, inline=False)
    e.add_field(name="Текст", value=(text[:900] + "…" if len(text) > 900 else (text or "—")), inline=False)
    ready = bool(ch_id) and ("—" not in when) and bool(text)
    e.add_field(name="Статус", value=("✅ настроено" if ready else "⚠️ не настроено полностью"), inline=False)
    return e


def _daily_message_missing_parts(*, guild_id: int) -> list[str]:
    from storage import get_daily_message_config

    cfg = get_daily_message_config(guild_id=guild_id) or {}
    missing: list[str] = []
    if not int(cfg.get("channel_id") or 0):
        missing.append("канал")
    text = str(cfg.get("text") or "").strip()
    if not text:
        missing.append("текст")
    try:
        hour = int(cfg.get("hour"))
        minute = int(cfg.get("minute"))
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            missing.append("время")
    except Exception:
        missing.append("время")
    return missing


class _DailyMessageTimeModal(discord.ui.Modal):
    def __init__(self, *, guild_id: int):
        super().__init__(title="Ежедневное сообщение • Время")
        self.guild_id = guild_id
        self.time = discord.ui.TextInput(
            label="Время по МСК",
            placeholder="Например: 18:30",
            style=discord.TextStyle.short,
            required=True,
            max_length=5,
        )
        self.add_item(self.time)

    async def on_submit(self, interaction: discord.Interaction):
        from storage import set_daily_message_config, set_daily_message_last_sent

        raw = str(self.time.value or "")
        m = re.match(r"^\s*(\d{1,2})\s*:\s*(\d{2})\s*$", raw)
        if not m:
            await interaction.response.send_message("Неверный формат. Пример: `18:30`.", ephemeral=True)
            return
        hh = int(m.group(1))
        mm = int(m.group(2))
        if hh < 0 or hh > 23 or mm < 0 or mm > 59:
            await interaction.response.send_message("Время должно быть в диапазоне `00:00`–`23:59`.", ephemeral=True)
            return
        set_daily_message_config(guild_id=self.guild_id, hour=hh, minute=mm)
        set_daily_message_last_sent(guild_id=self.guild_id, ymd=None)
        await interaction.response.send_message(f"Готово. Время ежедневки: **{hh:02d}:{mm:02d} МСК**", ephemeral=True)
        await _try_refresh_daily_menu_message(interaction=interaction, guild_id=self.guild_id)


_DAILY_MENU_MESSAGE_ID_BY_USER: dict[tuple[int, int], int] = {}


def _set_daily_menu_message_id(*, guild_id: int, user_id: int, message_id: int) -> None:
    _DAILY_MENU_MESSAGE_ID_BY_USER[(int(guild_id), int(user_id))] = int(message_id)
    set_daily_menu_message_ids(mapping=_DAILY_MENU_MESSAGE_ID_BY_USER)


async def _try_refresh_daily_menu_message(*, interaction: discord.Interaction, guild_id: int) -> None:
    if interaction.user is None:
        return
    key = (int(guild_id), int(interaction.user.id))
    mid = _DAILY_MENU_MESSAGE_ID_BY_USER.get(key)
    if not mid:
        return
    try:
        await interaction.followup.edit_message(
            message_id=mid,
            embed=_build_daily_message_embed(guild_id=guild_id),
            view=_DailyMessageMenuView(guild_id=guild_id),
        )
    except Exception:
        pass


class _DailyMessageMenuView(discord.ui.View):
    def __init__(self, *, guild_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Нужны права администратора.", ephemeral=True)
            return False
        return True

    async def _refresh(self, interaction: discord.Interaction) -> None:
        if interaction.message:
            _set_daily_menu_message_id(guild_id=self.guild_id, user_id=interaction.user.id, message_id=interaction.message.id)
        await interaction.response.edit_message(embed=_build_daily_message_embed(guild_id=self.guild_id), view=self)

    @discord.ui.button(label="Добавить", style=discord.ButtonStyle.success)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        from storage import set_daily_message_last_sent

        missing = _daily_message_missing_parts(guild_id=self.guild_id)
        if missing:
            await interaction.response.send_message(
                "Сначала заполни: " + ", ".join(f"**{x}**" for x in missing) + ".",
                ephemeral=True,
            )
            return
        set_daily_message_last_sent(guild_id=self.guild_id, ymd=None)
        await interaction.response.send_message("Готово. Ежедневка включена (если время уже прошло — отправит сегодня).", ephemeral=True)
        await _try_refresh_daily_menu_message(interaction=interaction, guild_id=self.guild_id)

    @discord.ui.button(label="Очистить", style=discord.ButtonStyle.danger)
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        from storage import clear_daily_message_config

        clear_daily_message_config(guild_id=self.guild_id)
        await self._refresh(interaction)

    @discord.ui.button(label="Посмотреть", style=discord.ButtonStyle.secondary)
    async def show(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._refresh(interaction)

    @discord.ui.button(label="Канал", style=discord.ButtonStyle.primary)
    async def channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View(timeout=180)
        select = discord.ui.ChannelSelect(
            placeholder="Выберите канал для ежедневки",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )

        async def _on_select(i: discord.Interaction):
            from storage import set_daily_message_config, set_daily_message_last_sent

            if i.guild is None:
                await i.response.send_message("Команда доступна только на сервере.", ephemeral=True)
                return
            picked = select.values[0] if select.values else None
            picked_id = int(getattr(picked, "id", 0) or 0)
            ch = i.guild.get_channel(picked_id)
            if ch is None and picked_id:
                try:
                    ch = await i.guild.fetch_channel(picked_id)
                except Exception:
                    ch = None
            if not isinstance(ch, discord.TextChannel):
                await i.response.send_message("Нужно выбрать текстовый канал.", ephemeral=True)
                return
            set_daily_message_config(guild_id=self.guild_id, channel_id=ch.id)
            set_daily_message_last_sent(guild_id=self.guild_id, ymd=None)
            if i.message:
                _set_daily_menu_message_id(guild_id=self.guild_id, user_id=i.user.id, message_id=i.message.id)
            await i.response.edit_message(embed=_build_daily_message_embed(guild_id=self.guild_id), view=self)

        select.callback = _on_select  # type: ignore[assignment]
        view.add_item(select)

        back_btn = discord.ui.Button(label="Назад", style=discord.ButtonStyle.secondary)

        async def _back(i: discord.Interaction):
            await i.response.edit_message(embed=_build_daily_message_embed(guild_id=self.guild_id), view=self)

        back_btn.callback = _back  # type: ignore[assignment]
        view.add_item(back_btn)

        await interaction.response.edit_message(embed=_build_daily_message_embed(guild_id=self.guild_id), view=view)

    @discord.ui.button(label="Текст", style=discord.ButtonStyle.primary)
    async def text(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(_DailyMessageTextModal(guild_id=self.guild_id))

    @discord.ui.button(label="Время", style=discord.ButtonStyle.primary)
    async def time(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(_DailyMessageTimeModal(guild_id=self.guild_id))


@bot.tree.command(name="ежедневка", description="Управление ежедневными сообщениями (несколько в день / разные каналы)")
@app_commands.describe(
    действие="Что сделать",
    канал="Канал для ежедневки (для действия добавить)",
    время="Время по МСК в формате HH:MM (для действия добавить)",
    текст="Текст сообщения (для действия добавить)",
    id="ID записи (для действия удалить)",
)
@app_commands.default_permissions(administrator=True)
@app_commands.choices(
    действие=[
        app_commands.Choice(name="список", value="list"),
        app_commands.Choice(name="добавить", value="add"),
        app_commands.Choice(name="удалить", value="remove"),
        app_commands.Choice(name="очистить всё", value="clear"),
    ]
)
async def daily_message_configure(
    interaction: discord.Interaction,
    действие: app_commands.Choice[str],
    канал: discord.TextChannel | None = None,
    время: str | None = None,
    текст: str | None = None,
    id: int | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    from storage import (
        add_daily_message_entry,
        clear_daily_message_entries,
        get_daily_message_entries,
        remove_daily_message_entry,
        set_daily_message_sent_for_entry,
    )

    action = действие.value
    guild_id = interaction.guild.id

    if action == "list":
        entries = get_daily_message_entries(guild_id=guild_id)
        if not entries:
            await interaction.response.send_message("Ежедневок пока нет. Добавь через действие `добавить`.", ephemeral=True)
            return
        lines: list[str] = []
        for item in entries[:30]:
            eid = int(item["id"])
            ch_id = int(item["channel_id"])
            hh = int(item["hour"])
            mm = int(item["minute"])
            msg_text = str(item["text"])
            preview = (msg_text[:120] + "…") if len(msg_text) > 120 else msg_text
            lines.append(f"**ID {eid}** • <#{ch_id}> • `{hh:02d}:{mm:02d} МСК`\n{preview}")
        await interaction.response.send_message("\n\n".join(lines), ephemeral=True)
        return

    if action == "add":
        if канал is None or not время or not (текст or "").strip():
            await interaction.response.send_message(
                "Для `добавить` укажи `канал`, `время` (HH:MM) и `текст`.",
                ephemeral=True,
            )
            return
        m = re.match(r"^\s*(\d{1,2})\s*:\s*(\d{2})\s*$", str(время))
        if not m:
            await interaction.response.send_message("Неверный формат времени. Пример: `18:30`.", ephemeral=True)
            return
        hh = int(m.group(1))
        mm = int(m.group(2))
        if hh < 0 or hh > 23 or mm < 0 or mm > 59:
            await interaction.response.send_message("Время должно быть в диапазоне `00:00`–`23:59`.", ephemeral=True)
            return
        text_clean = str(текст or "").strip()
        if len(text_clean) > 2000:
            await interaction.response.send_message("Текст слишком длинный (максимум 2000 символов).", ephemeral=True)
            return
        entry_id = add_daily_message_entry(
            guild_id=guild_id,
            channel_id=канал.id,
            hour=hh,
            minute=mm,
            text=text_clean,
        )
        # Сброс "уже отправлено", чтобы запись могла сработать сегодня, если время уже прошло.
        set_daily_message_sent_for_entry(guild_id=guild_id, entry_id=entry_id, ymd=None)
        await interaction.response.send_message(
            f"Готово. Добавлена ежедневка **ID {entry_id}**: {канал.mention} в `{hh:02d}:{mm:02d} МСК`.",
            ephemeral=True,
        )
        return

    if action == "remove":
        if id is None or id <= 0:
            await interaction.response.send_message("Для `удалить` укажи параметр `id`.", ephemeral=True)
            return
        removed = remove_daily_message_entry(guild_id=guild_id, entry_id=id)
        await interaction.response.send_message(
            ("Готово. Запись удалена." if removed else "Запись с таким ID не найдена."),
            ephemeral=True,
        )
        return

    if action == "clear":
        clear_daily_message_entries(guild_id=guild_id)
        await interaction.response.send_message("Готово. Все ежедневки удалены.", ephemeral=True)
        return

    await interaction.response.send_message("Неизвестное действие.", ephemeral=True)


@bot.tree.command(name="настройка-смотреть-тикеты", description="Настроить роли, которые могут смотреть каналы тикетов/обзвона")
@app_commands.describe(
    действие="Что сделать (добавить/убрать/список/очистить)",
    роль="Роль (нужно только для добавить/убрать)",
)
@app_commands.default_permissions(administrator=True)
@app_commands.choices(
    действие=[
        app_commands.Choice(name="добавить", value="add"),
        app_commands.Choice(name="убрать", value="remove"),
        app_commands.Choice(name="список", value="list"),
        app_commands.Choice(name="очистить", value="clear"),
    ]
)
async def configure_ticket_view_roles(
    interaction: discord.Interaction,
    действие: app_commands.Choice[str],
    роль: discord.Role | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    guild = interaction.guild

    if действие.value == "list":
        role_ids = get_ticket_view_role_ids(guild_id=guild.id)
        pretty = " ".join(f"<@&{rid}>" for rid in role_ids) if role_ids else "—"
        await interaction.response.send_message(f"Роли, которые могут смотреть тикеты: {pretty}", ephemeral=True)
        return

    if действие.value == "clear":
        set_ticket_view_role_ids(guild_id=interaction.guild.id, role_ids=[])
        await interaction.response.send_message("Готово. Доп. роли для просмотра тикетов очищены.", ephemeral=True)
        return

    if роль is None:
        await interaction.response.send_message("Выбери роль в параметре `роль`.", ephemeral=True)
        return

    role_ids = get_ticket_view_role_ids(guild_id=guild.id)

    if действие.value == "add":
        if роль.id not in role_ids:
            role_ids.append(роль.id)
            set_ticket_view_role_ids(guild_id=guild.id, role_ids=role_ids)
        await interaction.response.send_message(
            f"Готово. Роль {роль.mention} добавлена. Теперь смотреть тикеты смогут: "
            f"{' '.join(f'<@&{rid}>' for rid in role_ids)}",
            ephemeral=True,
        )
        return

    if действие.value == "remove":
        if роль.id in role_ids:
            role_ids = [rid for rid in role_ids if rid != роль.id]
            set_ticket_view_role_ids(guild_id=guild.id, role_ids=role_ids)
        pretty = " ".join(f"<@&{rid}>" for rid in role_ids) if role_ids else "—"
        await interaction.response.send_message(
            f"Готово. Роль {роль.mention} убрана. Теперь смотреть тикеты смогут: {pretty}",
            ephemeral=True,
        )
        return

    await interaction.response.send_message("Неизвестное действие.", ephemeral=True)


@bot.tree.command(name="привязка-отпусков", description="Выбрать канал, куда будут отправляться логи отпусков")
@app_commands.describe(send_to="Канал, куда бот будет отправлять логи отпусков")
@app_commands.default_permissions(administrator=True)
async def bind_vacations(interaction: discord.Interaction, send_to: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    set_vacation_channel_id(guild_id=interaction.guild.id, channel_id=send_to.id)
    await interaction.response.send_message(
        f"Готово. Теперь логи отпусков будут отправляться в {send_to.mention}.",
        ephemeral=True,
    )


@bot.tree.command(name="настройка-роль-отпуск", description="Настроить роль, которую выдавать при уходе в отпуск")
@app_commands.describe(
    действие="Что сделать (установить/очистить/показать)",
    роль="Роль отпуска (нужно только для 'установить')",
)
@app_commands.default_permissions(administrator=True)
@app_commands.choices(
    действие=[
        app_commands.Choice(name="установить", value="set"),
        app_commands.Choice(name="очистить", value="clear"),
        app_commands.Choice(name="показать", value="show"),
    ]
)
async def configure_vacation_role(
    interaction: discord.Interaction,
    действие: app_commands.Choice[str],
    роль: discord.Role | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    guild = interaction.guild
    if действие.value == "show":
        rid = get_vacation_role_id(guild_id=guild.id)
        pretty = f"<@&{rid}>" if rid else "—"
        await interaction.response.send_message(f"Роль отпуска: {pretty}", ephemeral=True)
        return
    if действие.value == "clear":
        set_vacation_role_id(guild_id=guild.id, role_id=None)
        await interaction.response.send_message("Готово. Роль отпуска очищена.", ephemeral=True)
        return
    if действие.value == "set":
        if роль is None:
            await interaction.response.send_message("Выбери роль в параметре `роль`.", ephemeral=True)
            return
        set_vacation_role_id(guild_id=guild.id, role_id=роль.id)
        await interaction.response.send_message(f"Готово. Роль отпуска установлена: {роль.mention}.", ephemeral=True)
        return
    await interaction.response.send_message("Неизвестное действие.", ephemeral=True)


@bot.tree.command(name="настройка-снимать-роли-отпуск", description="Настроить роли, которые снимать при уходе в отпуск")
@app_commands.describe(
    действие="Что сделать (добавить/убрать/список/очистить)",
    роль="Роль (нужно только для добавить/убрать)",
)
@app_commands.default_permissions(administrator=True)
@app_commands.choices(
    действие=[
        app_commands.Choice(name="добавить", value="add"),
        app_commands.Choice(name="убрать", value="remove"),
        app_commands.Choice(name="список", value="list"),
        app_commands.Choice(name="очистить", value="clear"),
    ]
)
async def configure_vacation_remove_roles(
    interaction: discord.Interaction,
    действие: app_commands.Choice[str],
    роль: discord.Role | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    guild = interaction.guild
    if действие.value == "list":
        role_ids = get_vacation_remove_role_ids(guild_id=guild.id)
        pretty = " ".join(f"<@&{rid}>" for rid in role_ids) if role_ids else "—"
        await interaction.response.send_message(f"Роли для снятия при отпуске: {pretty}", ephemeral=True)
        return
    if действие.value == "clear":
        set_vacation_remove_role_ids(guild_id=guild.id, role_ids=[])
        await interaction.response.send_message("Готово. Список ролей для снятия очищен.", ephemeral=True)
        return
    if роль is None:
        await interaction.response.send_message("Выбери роль в параметре `роль`.", ephemeral=True)
        return
    role_ids = get_vacation_remove_role_ids(guild_id=guild.id)
    if действие.value == "add":
        if роль.id not in role_ids:
            role_ids.append(роль.id)
            set_vacation_remove_role_ids(guild_id=guild.id, role_ids=role_ids)
        await interaction.response.send_message("Готово. Роль добавлена в список снятия.", ephemeral=True)
        return
    if действие.value == "remove":
        if роль.id in role_ids:
            role_ids = [rid for rid in role_ids if rid != роль.id]
            set_vacation_remove_role_ids(guild_id=guild.id, role_ids=role_ids)
        await interaction.response.send_message("Готово. Роль убрана из списка снятия.", ephemeral=True)
        return
    await interaction.response.send_message("Неизвестное действие.", ephemeral=True)


def _panel_image_file() -> discord.File | None:
    p = Path(__file__).resolve().parent / "foto" / PANEL_IMAGE_FILENAME
    if p.exists() and p.is_file():
        return discord.File(str(p), filename=PANEL_IMAGE_FILENAME)
    return None


@bot.tree.command(name="привязка-заявок", description="Выбрать канал, куда будут отправляться заявки")
@app_commands.describe(send_to="Канал, куда бот будет отправлять заявки")
@app_commands.default_permissions(administrator=True)
async def bind_applications(interaction: discord.Interaction, send_to: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    set_destination_channel_id(guild_id=interaction.guild.id, channel_id=send_to.id)
    await interaction.response.send_message(
        f"Готово. Теперь заявки будут отправляться в {send_to.mention}.",
        ephemeral=True,
    )


@bot.tree.command(
    name="модерация",
    description="Панель приёма заявок (embed и кнопки), видна только вам",
)
@app_commands.default_permissions(administrator=True)
async def moderation_application_panel(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    guild = interaction.guild
    embed = build_application_receipt_panel_embed(
        guild=guild,
        status_by_type=application_receipt_status_map(guild.id),
        bot_user=interaction.client.user,
    )
    await interaction.response.send_message(
        embed=embed,
        view=ApplicationReceiptPanelView(),
        ephemeral=True,
    )


@bot.tree.command(
    name="панель-приёма-заявок",
    description="Красивая embed-панель: приём заявок РП / VZP / Capt-Biz с кнопками",
)
@app_commands.describe(
    канал="Если указать — панель уйдёт в канал (видна тем, у кого есть доступ). Иначе только вам.",
)
@app_commands.default_permissions(administrator=True)
async def application_receipt_panel_cmd(
    interaction: discord.Interaction,
    канал: discord.TextChannel | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    guild = interaction.guild
    embed = build_application_receipt_panel_embed(
        guild=guild,
        status_by_type=application_receipt_status_map(guild.id),
        bot_user=interaction.client.user,
    )
    view = ApplicationReceiptPanelView()

    if канал is not None:
        me = guild.me
        if me is None or not канал.permissions_for(me).send_messages or not канал.permissions_for(me).embed_links:
            await interaction.response.send_message(
                f"В {канал.mention} боту нужны права **отправлять сообщения** и **встраивать ссылки** (embed).",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await канал.send(embed=embed, view=view)
        except (discord.Forbidden, discord.HTTPException):
            await interaction.followup.send("Не удалось отправить панель в канал (права или лимиты API).", ephemeral=True)
            return
        await interaction.followup.send(f"Панель отправлена в {канал.mention}.", ephemeral=True)
        return

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="панель-заявок", description="Отправить панель заявок в выбранный канал")
@app_commands.describe(panel_channel="Канал, куда отправить панель")
@app_commands.default_permissions(administrator=True)
async def applications_panel(interaction: discord.Interaction, panel_channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    destination_id = get_destination_channel_id(guild_id=interaction.guild.id) or config.APPLICATION_CHANNEL_ID
    if not destination_id:
        await interaction.response.send_message(
            "Сначала сделай `/привязка-заявок` и выбери канал для заявок (или заполни `APPLICATION_CHANNEL_ID` в `.env`).",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    f = _panel_image_file()
    embed = build_panel_embed(with_image=(f is not None))
    v2_supported = ApplicationPanelV2View is not None and f is not None
    view = (
        ApplicationPanelV2View(destination_channel_id=int(destination_id))
        if v2_supported
        else ApplicationPanelView(destination_channel_id=int(destination_id))
    )

    # Если панель уже была отправлена раньше — обновляем.
    # Важно: v2 LayoutView иногда ломается после message.edit на стороне Discord,
    # поэтому для v2 мы НЕ редактируем старое сообщение, а пересоздаём (delete + send).
    existing = get_panel_message_id(guild_id=interaction.guild.id)
    edited = False
    if existing and existing[0] == panel_channel.id:
        try:
            old_msg = await panel_channel.fetch_message(existing[1])
            if v2_supported:
                if f is not None:
                    msg = await panel_channel.send(view=view, file=f)
                else:
                    msg = await panel_channel.send(embed=embed, view=ApplicationPanelView(destination_channel_id=int(destination_id)))
                try:
                    await old_msg.delete()
                except (discord.Forbidden, discord.HTTPException):
                    pass
                set_panel_message_id(guild_id=interaction.guild.id, channel_id=panel_channel.id, message_id=msg.id)
            else:
                await old_msg.edit(embed=embed, view=view)
                msg = old_msg
            edited = True
        except (discord.NotFound, discord.Forbidden):
            edited = False
        except discord.HTTPException:
            edited = False

    if not edited:
        if v2_supported and f is not None:
            msg = await panel_channel.send(view=view, file=f)
        elif f is not None:
            msg = await panel_channel.send(embed=embed, view=view, file=f)
        else:
            msg = await panel_channel.send(embed=embed, view=view)
        set_panel_message_id(guild_id=interaction.guild.id, channel_id=panel_channel.id, message_id=msg.id)

    await interaction.followup.send(
        f"Панель {'обновлена' if edited else 'отправлена'} в {panel_channel.mention}. Заявки будут уходить в <#{destination_id}>.",
        ephemeral=True,
    )


@bot.tree.command(name="афк-панель", description="Отправить AFK-панель в выбранный канал")
@app_commands.describe(panel_channel="Канал, куда отправить AFK-панель")
@app_commands.default_permissions(administrator=True)
async def afk_panel(interaction: discord.Interaction, panel_channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    f = _afk_image_file()
    embed = build_afk_panel_embed(with_image=(f is not None))
    view = AFKPanelView()

    existing = get_afk_panel_message_id(guild_id=interaction.guild.id)
    edited = False
    if existing and existing[0] == panel_channel.id:
        try:
            old_msg = await panel_channel.fetch_message(existing[1])
            await old_msg.edit(embed=embed, view=view)
            edited = True
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            edited = False

    if not edited:
        if f is not None:
            msg = await panel_channel.send(embed=embed, view=view, file=f)
        else:
            msg = await panel_channel.send(embed=embed, view=view)
        set_afk_panel_message_id(guild_id=interaction.guild.id, channel_id=panel_channel.id, message_id=msg.id)

    await interaction.followup.send(
        f"AFK-панель {'обновлена' if edited else 'отправлена'} в {panel_channel.mention}.",
        ephemeral=True,
    )


@bot.tree.command(name="отпуск-панель", description="Отправить панель отпусков в выбранный канал")
@app_commands.describe(panel_channel="Канал, куда отправить панель отпусков")
@app_commands.default_permissions(administrator=True)
async def vacation_panel(interaction: discord.Interaction, panel_channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    f = _vacation_image_file()
    embed = build_vacation_panel_embed(with_image=(f is not None))
    view = VacationPanelView()

    existing = get_vacation_panel_message_id(guild_id=interaction.guild.id)
    edited = False
    if existing and existing[0] == panel_channel.id:
        try:
            old_msg = await panel_channel.fetch_message(existing[1])
            await old_msg.edit(embed=embed, view=view)
            edited = True
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            edited = False

    if not edited:
        if f is not None:
            msg = await panel_channel.send(embed=embed, view=view, file=f)
        else:
            msg = await panel_channel.send(embed=embed, view=view)
        set_vacation_panel_message_id(guild_id=interaction.guild.id, channel_id=panel_channel.id, message_id=msg.id)

    await interaction.followup.send(
        f"Панель отпусков {'обновлена' if edited else 'отправлена'} в {panel_channel.mention}.",
        ephemeral=True,
    )


@bot.event
async def on_ready():
    if bot.user:
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    actor = await _find_recent_audit_actor(guild=guild, action=discord.AuditLogAction.ban, target_id=user.id)
    if actor is None:
        return
    await _send_action_log(guild=guild, action_name="Бан на сервере", actor=actor, target=user)


@bot.event
async def on_member_join(member: discord.Member):
    if member.guild is None or member.bot:
        return
    await _send_join_leave_log(
        guild=member.guild,
        action_name="Зашёл на сервер",
        member=member,
    )


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if after.guild is None or after.bot:
        return

    before_role_ids = {r.id for r in before.roles}
    added_roles = [r for r in after.roles if r.id not in before_role_ids]
    if not added_roles:
        return

    actor = await _find_recent_audit_actor(
        guild=after.guild,
        action=discord.AuditLogAction.member_role_update,
        target_id=after.id,
        max_age_s=20,
    )
    if actor is None:
        return

    for role in added_roles:
        await _send_action_log(
            guild=after.guild,
            action_name=f"Выдал роль: {role.name}",
            actor=actor,
            target=after,
        )


@bot.event
async def on_presence_update(before: discord.Member | discord.User, after: discord.Member | discord.User):
    if not isinstance(after, discord.Member) or after.guild is None or after.bot:
        return

    guild = after.guild
    channel_id = get_stream_announce_channel_id(guild_id=guild.id)
    if channel_id is None:
        return
    allowed_user_ids = get_stream_announce_user_ids(guild_id=guild.id)
    if not allowed_user_ids or after.id not in allowed_user_ids:
        return
    twitch_map = get_stream_announce_twitch_map(guild_id=guild.id)
    mapped_login = twitch_map.get(after.id)
    if mapped_login and config.TWITCH_CLIENT_ID and config.TWITCH_CLIENT_SECRET:
        # Для привязанных Twitch-стримеров при наличии Twitch API
        # уведомления отправляет Twitch watcher.
        return

    def _is_streaming(m: discord.Member | discord.User) -> bool:
        for activity in getattr(m, "activities", []) or []:
            if isinstance(activity, discord.Streaming):
                return True
        return False

    was_streaming = _is_streaming(before)
    is_streaming = _is_streaming(after)

    if not was_streaming and is_streaming:
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                channel = None
        if not isinstance(channel, discord.TextChannel):
            return

        twitch_url = None
        for activity in after.activities:
            if isinstance(activity, discord.Streaming) and activity.url:
                twitch_url = activity.url
                break
        if twitch_url is None and mapped_login:
            twitch_url = f"https://twitch.tv/{mapped_login}"

        text = f"@everyone 🔴 {after.mention} запустил стрим!"
        if twitch_url:
            text += f" Заходи смотреть: {twitch_url}"
        try:
            await channel.send(text, allowed_mentions=discord.AllowedMentions(everyone=True, users=True))
        except (discord.Forbidden, discord.HTTPException):
            return


@bot.event
async def on_member_remove(member: discord.Member):
    if member.guild is None or member.bot:
        return
    actor = await _find_recent_audit_actor(
        guild=member.guild,
        action=discord.AuditLogAction.kick,
        target_id=member.id,
    )
    if actor is None:
        await _send_join_leave_log(
            guild=member.guild,
            action_name="Вышел с сервера",
            member=member,
        )
        return
    await _send_action_log(guild=member.guild, action_name="Исключение с сервера", actor=actor, target=member)


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.bot or member.guild is None:
        return

    guild = member.guild
    if before.mute != after.mute:
        actor = await _find_recent_audit_actor(
            guild=guild,
            action=discord.AuditLogAction.member_update,
            target_id=member.id,
            max_age_s=12,
        )
        if actor is not None:
            await _send_action_log(
                guild=guild,
                action_name="Отключил/включил микрофон (сервером)",
                actor=actor,
                target=member,
            )
    if before.deaf != after.deaf:
        actor = await _find_recent_audit_actor(
            guild=guild,
            action=discord.AuditLogAction.member_update,
            target_id=member.id,
            max_age_s=12,
        )
        if actor is not None:
            await _send_action_log(
                guild=guild,
                action_name="Отключил/включил наушники (сервером)",
                actor=actor,
                target=member,
            )
    if before.channel is not None and after.channel is None:
        actor = await _find_recent_audit_actor(
            guild=guild,
            action=discord.AuditLogAction.member_disconnect,
            target_id=member.id,
            max_age_s=12,
        )
        if actor is not None and actor.id != member.id:
            await _send_action_log(
                guild=guild,
                action_name="Кик из голосового канала",
                actor=actor,
                target=member,
            )

    # Удаляем пустые временные комнаты, созданные ботом.
    if before.channel is not None and len(before.channel.members) == 0:
        if get_temp_voice_owner_id(guild_id=guild.id, channel_id=before.channel.id) is not None:
            remove_temp_voice_owner_id(guild_id=guild.id, channel_id=before.channel.id)
            try:
                await before.channel.delete(reason="Временная комната пуста")
            except (discord.Forbidden, discord.HTTPException):
                pass

    lobby_id = get_voice_lobby_channel_id(guild_id=guild.id)
    if lobby_id is None:
        return
    if after.channel is None or after.channel.id != lobby_id:
        return
    if before.channel is not None and before.channel.id == lobby_id:
        return

    lobby_channel = after.channel
    if not isinstance(lobby_channel, discord.VoiceChannel):
        return

    room_name = f"Комната • {member.display_name}"[:100]
    try:
        temp_channel = await guild.create_voice_channel(
            name=room_name,
            category=lobby_channel.category,
            reason=f"Авто-комната для {member}",
        )
    except (discord.Forbidden, discord.HTTPException):
        return

    # Сохраняем правила категории (видимость/доступ), а поверх даём владельцу управление комнатой.
    try:
        await temp_channel.set_permissions(
            member,
            connect=True,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            speak=True,
            stream=True,
            use_voice_activation=True,
            priority_speaker=True,
            move_members=True,
            mute_members=True,
            deafen_members=True,
            manage_channels=True,
        )
        if guild.me is not None:
            await temp_channel.set_permissions(
                guild.me,
                connect=True,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                move_members=True,
                manage_channels=True,
            )
    except (discord.Forbidden, discord.HTTPException):
        pass

    set_temp_voice_owner_id(guild_id=guild.id, channel_id=temp_channel.id, owner_id=member.id)

    try:
        await member.move_to(temp_channel, reason="Перенос в личную авто-комнату")
    except (discord.Forbidden, discord.HTTPException):
        remove_temp_voice_owner_id(guild_id=guild.id, channel_id=temp_channel.id)
        try:
            await temp_channel.delete(reason="Не удалось перенести владельца")
        except (discord.Forbidden, discord.HTTPException):
            pass
        return

    # Пишем панель в чат голосового канала (если у сервера/клиента доступен voice text chat API).
    panel_embed = _build_voice_room_control_embed(owner=member)
    sent_panel = False
    if hasattr(temp_channel, "send"):
        # После создания voice-канала его текстовый чат может стать доступен не мгновенно.
        for _ in range(5):
            try:
                await temp_channel.send(embed=panel_embed, view=VoiceRoomControlView())  # type: ignore[attr-defined]
                sent_panel = True
                break
            except (discord.Forbidden, TypeError):
                break
            except discord.HTTPException:
                await asyncio.sleep(1.0)
    if not sent_panel:
        try:
            await member.send(embed=panel_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return

    role_ping_binding = get_role_ping_notify_binding(guild_id=message.guild.id)
    if role_ping_binding and isinstance(message.author, discord.Member):
        binding_category_id, binding_role_id = role_ping_binding
        if _message_category_id(message) == binding_category_id:
            mentioned_role_ids = {r.id for r in message.role_mentions}
            if binding_role_id in mentioned_role_ids:
                role = message.guild.get_role(binding_role_id)
                if role is not None:
                    dm_embed = _build_role_ping_dm_embed(
                        guild=message.guild,
                        channel=message.channel,
                        role=role,
                        author=message.author,
                        message_link=message.jump_url,
                    )
                    for member in role.members:
                        if member.bot or member.id == message.author.id:
                            continue
                        try:
                            await member.send(embed=dm_embed)
                        except (discord.Forbidden, discord.HTTPException):
                            pass

    trigger = message.content.strip().lower()
    if trigger in {
        "!картывзп",
        "!карты-взп",
        "!vzp",
        "!mapsvzp",
        ".картывзп",
        ".карты-взп",
    }:
        if not isinstance(message.author, discord.Member):
            return
        if not (message.author.guild_permissions.administrator or message.author.guild_permissions.manage_guild):
            return
        await message.channel.send(embed=_build_vzp_embed(), view=VzpMapView())
        try:
            await message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass


bot.run(config.DISCORD_TOKEN)

