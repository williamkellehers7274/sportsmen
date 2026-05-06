from __future__ import annotations

"""
Telegram Userbot ↔ Discord bridge для GTA RP (видит сообщения от других ботов).

Запускается из discord.Client.setup_hook один раз через asyncio.create_task().
Требует Telethon и личную сессию Telegram (не Bot API).

Переменные окружения (см. config.py): TELEGRAM_API_ID, TELEGRAM_API_HASH,
TELEGRAM_SESSION_NAME, TG_SOURCE_CHAT_ID, TG_CHAT_TITLE_SUBSTRING (опционально),
TG_RP_DISCORD_CHANNEL_ID — куда отправлять в Discord.
TG_RP_PAIR_OUTCOME_SECONDS — сколько ждать второе сообщение с итогом после «забили войну…» (по умолчанию 3600 с ≈ час).

TG_RP_STRIKE_TRIGGERS — свои ключевые фразы через «|» (сообщение о забитой войне только если есть совпадение).
TG_RP_PAIR_MATCH_LOCATION=on — второе сообщение к первому только если совпало имя локации; по умолчанию важен порядок в чате, не название территории.

Вторым часто приходит «Проигрывает / Выигрывает в бою #N за …», либо коротко «Победа / проигрыш». Иначе после таймера пост без блока «Итог боя».

Без TG_SOURCE_CHAT_ID пишется в канал любое распознанное событие (не рекомендуется для продакшена).
"""

import asyncio
import re
import time
from typing import Any

import discord
from telethon import TelegramClient, events

import config
from storage import get_tg_bridge_pair_state, set_tg_bridge_pair_state

PAIR_OUTCOME_SECONDS = float(config.TG_RP_PAIR_OUTCOME_SECONDS or 3600)

PENDING_STRIKE_KINDS = frozenset({"scored_for_us", "scored_against_us"})
STRIKE_PREVIEW_KINDS = frozenset({"scored_for_us", "scored_against_us"})


def _strike_triggers_allow(text_lc: str) -> bool:
    raw = getattr(config, "TG_RP_STRIKE_TRIGGERS", "").strip()
    if not raw:
        return True
    low = text_lc.lower().replace("ё", "е")
    low = re.sub(r"\s+", " ", low).strip()
    for frag in raw.split("|"):
        f = frag.strip().lower().replace("ё", "е")
        if not f:
            continue
        if f in low:
            return True
    return False


def _clean_extra_fragment(s: str) -> str:
    x = (s or "").strip()
    while x.startswith((",", ";", ".")):
        x = x[1:].strip()
    return x


def _extract_format_xy(full_compact: str) -> str | None:
    m = re.search(r"\b(\d+)\s*[xх]\s*(\d+)\b", full_compact, flags=re.IGNORECASE)
    if not m:
        return None
    return f"{m.group(1)}×{m.group(2)}"


def _rules_tail_after_formats(s: str) -> str:
    """Из хвоста после времени убирает ведущие «12×12, …», оставляет правила до конца (алкоголь/…)."""
    t = (s or "").strip()
    t = _clean_extra_fragment(t)
    t = re.sub(r"^(?:\d+\s*[xх]\s*\d+\s*,?\s*)+", "", t, flags=re.IGNORECASE)
    return t.strip()


def _strike_md_value(inner: str) -> str:
    t = (inner or "").strip().replace("**", "")
    if len(t) > 900:
        t = t[:897] + "…"
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    if not lines:
        return "> ****"
    if len(lines) == 1:
        return f"> **{lines[0]}**"
    return "\n".join(f"> **{ln}**" for ln in lines)


def _build_strike_preview_description(kind_here: str, parsed: dict[str, str], outcome: str | None) -> str:
    """Описание embed: заголовки **жирным**, строки ниже как blockquote (> **…**); markdown в именах полей Discord часто не рисуется."""
    chunks: list[str] = []

    enemy_f = parsed.get("enemy")
    if enemy_f:
        lbl = "Противник" if kind_here == "scored_against_us" else "Кому забили"
        chunks.append(f"**{lbl}**\n{_strike_md_value(enemy_f[:300])}")

    at_time = parsed.get("at_time")
    if at_time:
        chunks.append(f"**Время терры**\n{_strike_md_value(at_time)}")

    fmt_xy = parsed.get("format_xy")
    if fmt_xy:
        chunks.append(f"**Сколько на сколько**\n{_strike_md_value(fmt_xy)}")

    rules_only = _rules_tail_after_formats(parsed.get("extras") or "")
    if rules_only:
        chunks.append(f"**Условия**\n{_strike_md_value(rules_only)}")

    if outcome == "win":
        chunks.append(f"**Итог боя**\n{_strike_md_value('Победа')}")
    elif outcome == "loss":
        chunks.append(f"**Итог боя**\n{_strike_md_value('Проигрыш')}")

    body = "\n\n".join(chunks)
    if len(body) > 4096:
        body = body[:4095] + "…"
    return body


def parse_rp_followup_outcome(text: str) -> str | None:
    """Второе сообщение: явная победа или проигрыш (отдельной строкой / после точки)."""
    raw = (text or "").strip()
    if not raw:
        return None
    low = raw.lower().replace("ё", "е")
    compact = re.sub(r"\s+", " ", low).strip()
    compact = compact.lstrip(".").strip()

    # победа / выиграли / вин (+ опечатки)
    win_hits = (
        r"\bпобеда\b",
        r"\bпобедили\b",
        r"\bпобедил\w*\b",
        r"\bвыиграл\w*\b",
        r"\bвыигрыва\w*",  # «Выигрывает в бою…»
        r"\bпобежда\w*",  # «Побеждает в бою…»
        r"\bвин\b",
        r"\bвыиграли\b",
    )
    for pat in win_hits:
        if re.search(pat, compact, flags=re.IGNORECASE):
            return "win"

    loss_hits = (
        r"\bпроигрыш\b",
        r"\bпроиграл\w*\b",
        r"\bпроигрыва\w*",  # «Проигрывает в бою…»
        r"\bпоражен\b",
        r"\bпроиграли\b",
        r"\bлуз\b",
        r"\bвы\s+проиграл",
    )
    for pat in loss_hits:
        if re.search(pat, compact, flags=re.IGNORECASE):
            return "loss"

    return None


def _norm_wh_frag(s: str) -> str:
    t = (s or "").lower().replace("ё", "е")
    t = re.sub(r"\s+", " ", t).strip().rstrip(".,;:\"'»«„“").strip()
    return t


def _warehouse_maybe_same(place_a: str, place_b: str) -> bool:
    """Локация из «забили войну за X» vs «за X» во второй строке (Milton)."""
    x, y = _norm_wh_frag(place_a), _norm_wh_frag(place_b)
    if not x or not y:
        return True
    return x == y or x in y or y in x


def parse_milton_fight_outcome_line(text: str) -> dict[str, str] | None:
    """
    Milton, второе сообщение: «Проигрывает в бою #0 за Ресторан KOI» /
    «Выигрывает / Побеждает в бою #… за …» (не только «за склад …»).
    """
    raw = (text or "").strip().strip("\"'«»„“")
    if not raw:
        return None
    low = raw.lower().replace("ё", "е")
    compact = re.sub(r"\s+", " ", low).strip()

    def _cw(s: str) -> str:
        return _norm_wh_frag(s)

    m = re.search(r"проигрывает\s+в\s*бою\s*#\s*(\d+)\s+за\s+(?:склад\s+)?(.+)", compact, flags=re.IGNORECASE)
    if m:
        wh_raw = m.group(2).strip().rstrip(".,;:\"'»«„").strip()
        return {"outcome": "loss", "fight_no": m.group(1).strip(), "warehouse": wh_raw}

    m = re.search(r"(?:выигрывает|побеждает)\s+в\s*бою\s*#\s*(\d+)\s+за\s+(?:склад\s+)?(.+)", compact, flags=re.IGNORECASE)
    if m:
        wh_raw = m.group(2).strip().rstrip(".,;:\"'»«„").strip()
        return {"outcome": "win", "fight_no": m.group(1).strip(), "warehouse": wh_raw}

    return None


def try_dual_segment_strike_message(raw: str) -> tuple[dict[str, str], str, str, str] | None:
    """
    Одно сообщение вида «…на 22:30. победа»: до точки — строка забитого, после — итог.
    """
    s = (raw or "").strip()
    dot = s.rfind(".")
    if dot <= 0:
        return None
    before = s[:dot].strip()
    after = s[dot + 1 :].strip()
    if not before or not after:
        return None
    oc = parse_rp_followup_outcome(after)
    if oc is None:
        return None
    strike = parse_gta_rp_war_line(before)
    if strike is None or strike.get("kind") not in PENDING_STRIKE_KINDS:
        return None
    return (strike, before, after, oc)


def parse_gta_rp_war_line(text: str) -> dict[str, str] | None:
    src = (text or "").strip().strip("\"'«»„“")
    if not src:
        return None
    low = src.lower().replace("ё", "е")
    compact = re.sub(r"\s+", " ", low).strip()

    m = re.search(
        r"^ваша организация забила\s+(.+?)\s+войну за\s+(?:склад\s+)?(.+?)\s+на\s+(\d{1,2}:\d{2})(.*?)$",
        compact,
        flags=re.IGNORECASE,
    )
    if m:
        if not _strike_triggers_allow(compact):
            return None
        extra = _clean_extra_fragment(m.group(4))
        fmt = _extract_format_xy(compact)
        row = {
            "kind": "scored_for_us",
            "title": "✅ Вы забили войну",
            "enemy": m.group(1).strip(),
            "warehouse": m.group(2).strip(),
            "at_time": m.group(3).strip(),
            "extras": extra,
        }
        if fmt:
            row["format_xy"] = fmt
        return row

    m = re.search(
        r"^(.+?)\s+забили вашей организации войну за\s+(?:склад\s+)?(.+?)\s+на\s+(\d{1,2}:\d{2})(.*?)$",
        compact,
        flags=re.IGNORECASE,
    )
    if m:
        if not _strike_triggers_allow(compact):
            return None
        extra = _clean_extra_fragment(m.group(4))
        fmt = _extract_format_xy(compact)
        row = {
            "kind": "scored_against_us",
            "title": "❌ Вам забили войну",
            "enemy": m.group(1).strip(),
            "warehouse": m.group(2).strip(),
            "at_time": m.group(3).strip(),
            "extras": extra,
        }
        if fmt:
            row["format_xy"] = fmt
        return row

    m = re.search(r"удерживает склад\s+(.+?)\s+в\s*бою\s*#\s*(\d+)", compact, flags=re.IGNORECASE)
    if m:
        return {
            "kind": "won_fight",
            "title": "✅ Выигрыш в бою",
            "warehouse": m.group(1).strip(),
            "fight_no": m.group(2).strip(),
        }

    m_m = parse_milton_fight_outcome_line(src)
    if m_m:
        fk = "won_fight" if m_m["outcome"] == "win" else "lost_fight"
        ttl = "✅ Выигрыш в бою" if m_m["outcome"] == "win" else "❌ Проигрыш в бою"
        return {
            "kind": fk,
            "title": ttl,
            "fight_no": m_m["fight_no"],
            "warehouse": m_m["warehouse"],
        }

    m = re.search(r"проигрывает\s+в\s*бою\s*#\s*(\d+)\s+за\s+склад\s+(.+)", compact, flags=re.IGNORECASE)
    if m:
        return {
            "kind": "lost_fight",
            "title": "❌ Проигрыш в бою",
            "fight_no": m.group(1).strip(),
            "warehouse": m.group(2).strip(),
        }

    m = re.search(r"захватывает склад\s+(.+?)\s+в бою\s*#\s*(\d+)", compact, flags=re.IGNORECASE)
    if m:
        return {
            "kind": "fight_started",
            "title": "⚔️ Захват начался",
            "warehouse": m.group(1).strip(),
            "fight_no": m.group(2).strip(),
        }

    return None


def build_discord_rp_embed(
    *,
    parsed: dict[str, str],
    source_text: str,
    outcome: str | None = None,
    second_text: str | None = None,
) -> discord.Embed:
    EMBED_COLOR = discord.Color.from_rgb(0, 0, 0)
    e = discord.Embed(
        title=parsed.get("title", "Событие"),
        color=EMBED_COLOR,
    )
    kind_here = parsed.get("kind") or ""

    if kind_here in STRIKE_PREVIEW_KINDS:
        desc_block = _build_strike_preview_description(kind_here, parsed, outcome)
        if desc_block.strip():
            e.description = desc_block

    else:
        warehouse = parsed.get("warehouse")
        if warehouse:
            e.add_field(name="Склад", value=warehouse, inline=True)
        fight_no = parsed.get("fight_no")
        if fight_no:
            e.add_field(name="Бой", value=f"#{fight_no}", inline=True)
        enemy = parsed.get("enemy")
        if enemy:
            e.add_field(name="Противник", value=enemy, inline=True)
        at_time = parsed.get("at_time")
        if at_time:
            e.add_field(name="Время", value=at_time, inline=True)
        if outcome == "win":
            e.add_field(name="Итог боя", value="Победа", inline=False)
        elif outcome == "loss":
            e.add_field(name="Итог боя", value="Проигрыш", inline=False)
        tg_block = source_text[:700] if second_text else source_text[:900]
        e.add_field(name="Исходное уведомление (TG)", value=tg_block, inline=False)

    if second_text and kind_here not in STRIKE_PREVIEW_KINDS:
        st = second_text.strip()
        if st:
            e.add_field(name="Итог (второе сообщение TG)", value=st[:900], inline=False)
    return e


def _normalize_raw_message(msg) -> str:
    txt = getattr(msg, "text", None) or getattr(msg, "message", "") or ""
    return str(txt).strip()


async def tg_userbot_rp_bridge_loop(discord_client: discord.Client) -> None:
    await discord_client.wait_until_ready()

    api_id = config.TELEGRAM_API_ID
    api_hash = config.TELEGRAM_API_HASH
    session_name = config.TELEGRAM_SESSION_NAME
    target_dc = config.TG_RP_DISCORD_CHANNEL_ID
    want_chat_id = config.TG_SOURCE_CHAT_ID

    # Обратная совместимость: старое имя переменной
    if target_dc is None:
        target_dc = config.TG_WAR_DISCORD_CHANNEL_ID

    if not api_id or not api_hash or not session_name or not target_dc:
        return

    tg = TelegramClient(session_name, api_id, api_hash)

    try:
        await tg.connect()
        if not await tg.is_user_authorized():
            phone_buf = getattr(config, "TELEGRAM_PHONE", "").strip()

            async def phone_cb() -> str:
                nonlocal phone_buf
                if phone_buf:
                    p = phone_buf
                    phone_buf = ""
                    return p
                return input("Telegram номер телефона (с +): ").strip()

            async def password_cb() -> str:
                return input("Telegram пароль (2FA, если включён): ").strip()

            await tg.start(phone=phone_cb, password=password_cb)
    except EOFError:
        print("[tg_userbot_rp_bridge] нужен первый вход в Telegram: запустите бота в консоли (интерактив)")
        await tg.disconnect()
        return
    except Exception as e:
        print(f"[tg_userbot_rp_bridge] ошибка авторизации Telegram: {e}")
        try:
            await tg.disconnect()
        except Exception:
            pass
        return

    sub = (config.TG_CHAT_TITLE_SUBSTRING or "").strip().lower()

    pending_score: dict[int, dict[str, Any]] = {}
    pending_tasks: dict[int, asyncio.Task[None]] = {}
    strike_gen_serial: dict[int, int] = {}
    pair_lock = asyncio.Lock()

    def _save_pair_state() -> None:
        serial_obj = {str(int(cid)): int(gen) for cid, gen in strike_gen_serial.items()}
        pending_obj: dict[str, dict[str, Any]] = {}
        for cid, payload in pending_score.items():
            parsed = payload.get("parsed")
            text1 = payload.get("text1")
            gen = payload.get("gen")
            created_ts = payload.get("created_ts")
            if not isinstance(parsed, dict) or not isinstance(text1, str):
                continue
            try:
                gen_int = int(gen)
            except (TypeError, ValueError):
                continue
            try:
                created_int = int(created_ts)
            except (TypeError, ValueError):
                created_int = int(time.time())
            pending_obj[str(int(cid))] = {
                "parsed": parsed,
                "text1": text1,
                "gen": gen_int,
                "created_ts": created_int,
            }
        set_tg_bridge_pair_state(
            state={
                "strike_gen_serial": serial_obj,
                "pending_score": pending_obj,
            }
        )

    async def _discord_text_channel():
        discord_ch = discord_client.get_channel(int(target_dc))
        if discord_ch is None:
            try:
                discord_ch = await discord_client.fetch_channel(int(target_dc))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        if not isinstance(discord_ch, (discord.TextChannel, discord.Thread)):
            return None
        return discord_ch

    async def post_strike_to_discord(
        *,
        parsed: dict[str, str],
        first_text: str,
        outcome: str | None,
        second_text: str | None,
    ) -> None:
        discord_ch = await _discord_text_channel()
        if discord_ch is None:
            return
        embed = build_discord_rp_embed(
            parsed=parsed,
            source_text=first_text,
            outcome=outcome,
            second_text=second_text,
        )
        try:
            await discord_ch.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    def _cancel_timer(cid_int: int) -> None:
        task = pending_tasks.pop(cid_int, None)
        if task is not None and not task.done():
            task.cancel()

    async def _timeout_then_post_without_outcome(cid_int: int, gen: int, delay_s: float | None = None) -> None:
        try:
            await asyncio.sleep(PAIR_OUTCOME_SECONDS if delay_s is None else max(0.0, float(delay_s)))
        except asyncio.CancelledError:
            return
        async with pair_lock:
            pdata = pending_score.get(cid_int)
            if pdata is None or int(pdata["gen"]) != gen:
                return
            pending_score.pop(cid_int, None)
            pending_tasks.pop(cid_int, None)
            _save_pair_state()
        await post_strike_to_discord(
            parsed=pdata["parsed"],
            first_text=pdata["text1"],
            outcome=None,
            second_text=None,
        )

    # Restore pending pair state and timers so restarts do not lose the chain.
    raw_state = get_tg_bridge_pair_state()
    raw_serial = raw_state.get("strike_gen_serial", {}) if isinstance(raw_state, dict) else {}
    if isinstance(raw_serial, dict):
        for key, value in raw_serial.items():
            try:
                strike_gen_serial[int(key)] = int(value)
            except (TypeError, ValueError):
                continue
    raw_pending = raw_state.get("pending_score", {}) if isinstance(raw_state, dict) else {}
    if isinstance(raw_pending, dict):
        now_ts = int(time.time())
        for key, payload in raw_pending.items():
            try:
                cid_int = int(key)
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            parsed = payload.get("parsed")
            text1 = payload.get("text1")
            gen = payload.get("gen")
            created_ts = payload.get("created_ts")
            if not isinstance(parsed, dict) or not isinstance(text1, str):
                continue
            try:
                gen_int = int(gen)
            except (TypeError, ValueError):
                continue
            try:
                created_int = int(created_ts)
            except (TypeError, ValueError):
                created_int = now_ts
            pending_score[cid_int] = {
                "parsed": parsed,
                "text1": text1,
                "gen": gen_int,
                "created_ts": created_int,
            }
            remaining = max(0.0, float(PAIR_OUTCOME_SECONDS - max(0, now_ts - created_int)))
            pending_tasks[cid_int] = asyncio.create_task(_timeout_then_post_without_outcome(cid_int, gen_int, remaining))

    @tg.on(events.NewMessage)
    async def handler(event: events.NewMessage.Event) -> None:
        chat = await event.get_chat()
        cid = getattr(chat, "id", None)
        if want_chat_id is not None:
            try:
                want = int(want_chat_id)
            except (TypeError, ValueError):
                want = 0
            if want and cid is not None and int(cid) != want:
                return

        raw = _normalize_raw_message(event.message)
        if sub:
            title = getattr(chat, "title", None)
            username = getattr(chat, "username", None)
            blob = " ".join(str(x).lower() for x in [title, username, getattr(chat, "usernames", "")] if x).lower()
            if sub not in blob and sub not in raw.lower():
                return

        cid_int = int(cid) if cid is not None else 0

        dual = try_dual_segment_strike_message(raw)
        if dual is not None:
            strike_p, bef, aft, oc_dual = dual
            await post_strike_to_discord(
                parsed=strike_p,
                first_text=bef,
                outcome=oc_dual,
                second_text=aft,
            )
            return

        fo_struct = parse_milton_fight_outcome_line(raw)
        pdata_struct_done: dict[str, Any] | None = None
        outcome_struct_done: str | None = None
        async with pair_lock:
            if cid_int in pending_score and fo_struct is not None:
                pdata_live = pending_score[cid_int]
                wh_live = pdata_live["parsed"].get("warehouse") or ""
                fo_wh = fo_struct.get("warehouse") or ""
                loc_ok = _warehouse_maybe_same(wh_live, fo_wh) if config.TG_RP_PAIR_MATCH_LOCATION else True
                if loc_ok:
                    _cancel_timer(cid_int)
                    pdata_struct_done = pending_score.pop(cid_int, None)
                    outcome_struct_done = fo_struct["outcome"]
                    _save_pair_state()

        if pdata_struct_done is not None and outcome_struct_done is not None:
            merged_p = dict(pdata_struct_done["parsed"])
            if fo_struct is not None and fo_struct.get("fight_no"):
                merged_p["fight_no"] = str(fo_struct["fight_no"])
            await post_strike_to_discord(
                parsed=merged_p,
                first_text=pdata_struct_done["text1"],
                outcome=outcome_struct_done,
                second_text=raw,
            )
            return

        oc_lex = parse_rp_followup_outcome(raw)
        pdata_lex_done: dict[str, Any] | None = None
        async with pair_lock:
            if cid_int in pending_score and oc_lex is not None and fo_struct is None:
                _cancel_timer(cid_int)
                pdata_lex_done = pending_score.pop(cid_int, None)
                _save_pair_state()

        if pdata_lex_done is not None and oc_lex is not None:
            await post_strike_to_discord(
                parsed=pdata_lex_done["parsed"],
                first_text=pdata_lex_done["text1"],
                outcome=oc_lex,
                second_text=raw,
            )
            return

        parsed = parse_gta_rp_war_line(raw)
        if parsed is None:
            return

        kind = parsed.get("kind") or ""

        if kind not in PENDING_STRIKE_KINDS:
            await post_strike_to_discord(
                parsed=parsed,
                first_text=raw,
                outcome=None,
                second_text=None,
            )
            return

        flushed_old: dict[str, Any] | None = None
        async with pair_lock:
            if cid_int in pending_score:
                _cancel_timer(cid_int)
                flushed_old = pending_score.pop(cid_int, None)
            strike_gen_serial[cid_int] = strike_gen_serial.get(cid_int, 0) + 1
            gen = int(strike_gen_serial[cid_int])
            pending_score[cid_int] = {
                "parsed": parsed,
                "text1": raw,
                "gen": gen,
                "created_ts": int(time.time()),
            }
            _cancel_timer(cid_int)
            t = asyncio.create_task(_timeout_then_post_without_outcome(cid_int, gen))
            pending_tasks[cid_int] = t
            _save_pair_state()

        if flushed_old is not None:
            await post_strike_to_discord(
                parsed=flushed_old["parsed"],
                first_text=flushed_old["text1"],
                outcome=None,
                second_text=None,
            )

    try:
        while not discord_client.is_closed():
            await asyncio.sleep(1)
    finally:
        try:
            await tg.disconnect()
        except Exception:
            pass


def spawn_telegram_userbot_rp_bridge(discord_client: discord.Client) -> None:
    discord_client.loop.create_task(tg_userbot_rp_bridge_loop(discord_client))
