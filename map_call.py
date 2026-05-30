from __future__ import annotations

import io
import json
import threading
from pathlib import Path
from typing import Any

import discord
from discord import app_commands

_DATA_DIR = Path(__file__).resolve().parent / "data"
_STATE_PATH = _DATA_DIR / "panel_extra_state.json"
_LOCK = threading.Lock()
_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _load_state() -> dict[str, Any]:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _STATE_PATH.exists():
        return {"panels": {}}
    try:
        raw = json.loads(_STATE_PATH.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {"panels": {}}
    if not isinstance(raw, dict):
        return {"panels": {}}
    raw.setdefault("panels", {})
    return raw


def _save_state(data: dict[str, Any]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _style_for_place(place: int) -> discord.ButtonStyle:
    row = ((place - 1) % 25) // 5
    styles = (
        discord.ButtonStyle.primary,
        discord.ButtonStyle.success,
        discord.ButtonStyle.secondary,
        discord.ButtonStyle.danger,
        discord.ButtonStyle.secondary,
    )
    return styles[row]


def _occupied_count(slots: dict[str, int]) -> int:
    return len(slots)


def _build_embed(*, total: int, slots: dict[str, int]) -> discord.Embed:
    taken = _occupied_count(slots)
    e = discord.Embed(
        title="🗺️ Расстановка по местам",
        description=f"📍 Места ({taken}/{total})",
    )
    e.set_footer(text="Нажми номер, чтобы занять место. Свой номер — чтобы освободить.")
    return e


def _find_panel(data: dict[str, Any], message_id: int) -> tuple[str, dict[str, Any]] | None:
    panels = data.get("panels", {})
    mid = str(message_id)
    for key, panel in panels.items():
        if not isinstance(panel, dict):
            continue
        if key == mid or str(panel.get("primary_message_id")) == mid:
            return key, panel
        second = panel.get("second_message_id")
        if second is not None and str(second) == mid:
            return key, panel
    return None


def _user_slot(slots: dict[str, int], user_id: int) -> int | None:
    for num, uid in slots.items():
        if uid == user_id:
            try:
                return int(num)
            except ValueError:
                continue
    return None


def build_place_view(*, start: int, end: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for place in range(start, end + 1):
        row = (place - start) // 5
        view.add_item(MapPlaceButton(place=place, row=row))
    return view


class MapPlaceButton(discord.ui.Button):
    def __init__(self, *, place: int, row: int):
        self.place = place
        super().__init__(
            label=str(place),
            style=_style_for_place(place),
            custom_id=f"map_place_{place}",
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        with _LOCK:
            data = _load_state()
            found = _find_panel(data, interaction.message.id if interaction.message else 0)
            if found is None:
                await interaction.response.send_message("Панель не найдена или устарела.", ephemeral=True)
                return
            key, panel = found
            slots: dict[str, int] = panel.setdefault("slots", {})
            total = int(panel.get("total_slots", 0))
            if self.place < 1 or self.place > total:
                await interaction.response.send_message("Недопустимое место.", ephemeral=True)
                return

            uid = interaction.user.id
            slot_key = str(self.place)
            occupant = slots.get(slot_key)
            current = _user_slot(slots, uid)

            if occupant == uid:
                slots.pop(slot_key, None)
                reply = f"Место {self.place} освобождено."
            elif occupant is not None:
                await interaction.response.send_message("Место уже занято", ephemeral=True)
                return
            else:
                if current is not None:
                    slots.pop(str(current), None)
                slots[slot_key] = uid
                reply = f"Вы заняли место {self.place}."

            panel["slots"] = slots
            data["panels"][key] = panel
            _save_state(data)

        await interaction.response.send_message(reply, ephemeral=True)
        await refresh_panel(interaction.client, panel)


async def refresh_panel(client: discord.Client, panel: dict[str, Any]) -> None:
    channel_id = int(panel.get("channel_id", 0))
    primary_id = int(panel.get("primary_message_id", 0))
    if not channel_id or not primary_id:
        return

    ch = client.get_channel(channel_id)
    if not isinstance(ch, (discord.TextChannel, discord.Thread)):
        return

    total = int(panel.get("total_slots", 0))
    slots: dict[str, int] = panel.get("slots") or {}
    embed = _build_embed(total=total, slots=slots)

    try:
        primary = await ch.fetch_message(primary_id)
        first_end = min(25, total)
        await primary.edit(embed=embed, view=build_place_view(start=1, end=first_end))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return

    second_id = panel.get("second_message_id")
    if second_id and total > 25:
        try:
            second = await ch.fetch_message(int(second_id))
            await second.edit(content="\u200b", view=build_place_view(start=26, end=total))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass


def register_map_call_views(bot: discord.Client) -> None:
    """До 25 кнопок на view — регистрируем два persistent view (1–25 и 26–50)."""
    bot.add_view(build_place_view(start=1, end=25))
    bot.add_view(build_place_view(start=26, end=50))


def _attachment_ok(attachment: discord.Attachment) -> bool:
    name = (attachment.filename or "").lower()
    ext = Path(name).suffix
    if ext in _ALLOWED_EXT:
        return True
    ctype = (attachment.content_type or "").lower()
    return ctype.startswith("image/")


def register_map_call_commands(tree: app_commands.CommandTree) -> None:
    @tree.command(name="колл", description="Расстановка по местам на карте")
    @app_commands.describe(
        мест="Количество мест (1–50)",
        карта="Карта (png/jpg/gif/webp)",
    )
    async def koll_command(
        interaction: discord.Interaction,
        мест: app_commands.Range[int, 1, 50],
        карта: discord.Attachment,
    ):
        if interaction.guild is None:
            await interaction.response.send_message("Команда только на сервере.", ephemeral=True)
            return
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("Команда доступна в текстовом канале или ветке.", ephemeral=True)
            return
        if not _attachment_ok(карта):
            await interaction.response.send_message(
                "Нужно изображение: png, jpg, gif или webp.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            image_bytes = await карта.read()
        except discord.HTTPException:
            await interaction.followup.send("Не удалось прочитать вложение.", ephemeral=True)
            return

        total = int(мест)
        slots: dict[str, int] = {}
        embed = _build_embed(total=total, slots=slots)
        filename = карта.filename or "map.png"
        file = discord.File(io.BytesIO(image_bytes), filename=filename)

        first_end = min(25, total)
        view1 = build_place_view(start=1, end=first_end)

        msg1 = await interaction.channel.send(file=file, embed=embed, view=view1)

        msg2: discord.Message | None = None
        if total > 25:
            view2 = build_place_view(start=26, end=total)
            msg2 = await interaction.channel.send(content="\u200b", view=view2)

        panel: dict[str, Any] = {
            "total_slots": total,
            "guild_id": interaction.guild.id,
            "channel_id": interaction.channel.id,
            "slots": slots,
            "primary_message_id": msg1.id,
            "second_message_id": msg2.id if msg2 else None,
        }

        with _LOCK:
            data = _load_state()
            data.setdefault("panels", {})[str(msg1.id)] = panel
            _save_state(data)

        await interaction.followup.send(f"Расстановка создана: {msg1.jump_url}", ephemeral=True)


def setup_map_call(bot: discord.Client) -> None:
    register_map_call_views(bot)
