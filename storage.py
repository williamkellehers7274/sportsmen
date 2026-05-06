from __future__ import annotations

import json
import os
import time
import threading
from pathlib import Path
from typing import Any


def _resolve_data_dir() -> Path:
    env_dir = os.getenv("BOT_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser()

    # On Windows, prefer project-local storage by default.
    if os.name == "nt":
        return Path(__file__).resolve().parent / "data"

    # Try common persistent locations used by container hostings.
    for candidate in (Path("/data/bot-carti"), Path("/data")):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except Exception:
            continue

    # Fallback to project-local folder (works locally, but may be ephemeral in containers).
    return Path(__file__).resolve().parent / "data"


_DATA_DIR = _resolve_data_dir()
_BINDINGS_FILE = _DATA_DIR / "bindings.json"
_PROJECT_BINDINGS_FILE = Path(__file__).resolve().parent / "data" / "bindings.json"
_STORAGE_LOCK_FILE = _DATA_DIR / ".storage.lock"
_INSTANCE_LOCK_FILE = _DATA_DIR / ".bot.instance.lock"
_UPDATED_TS_KEY = "__storage_updated_ts"
_LOCAL_RW_LOCK = threading.RLock()


def _ensure_files() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if _BINDINGS_FILE.exists():
        return
    _BINDINGS_FILE.write_text(json.dumps({_UPDATED_TS_KEY: int(time.time())}, ensure_ascii=False), encoding="utf-8")


def _read_bindings_payload() -> dict[str, Any]:
    if not _BINDINGS_FILE.exists():
        return {}
    try:
        raw = json.loads(_BINDINGS_FILE.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _read_project_bindings_payload() -> dict[str, Any]:
    if _PROJECT_BINDINGS_FILE.resolve() == _BINDINGS_FILE.resolve():
        return {}
    if not _PROJECT_BINDINGS_FILE.exists():
        return {}
    try:
        raw = json.loads(_PROJECT_BINDINGS_FILE.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _payload_without_meta(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k != _UPDATED_TS_KEY}


def _payload_updated_ts(data: dict[str, Any]) -> int:
    try:
        return int(data.get(_UPDATED_TS_KEY, 0))
    except (TypeError, ValueError):
        return 0


def _read_json() -> dict[str, Any]:
    with _LOCAL_RW_LOCK:
        _ensure_files()
        data = _read_bindings_payload()
        if _payload_without_meta(data):
            return data

        # Safety net: if runtime data dir is different and empty, recover from project-local JSON once.
        project_data = _read_project_bindings_payload()
        if _payload_without_meta(project_data):
            _write_json(project_data)
            return project_data
        return data if data else {}


def _write_json(obj: dict[str, Any]) -> None:
    with _LOCAL_RW_LOCK:
        _ensure_files()
        _acquire_file_lock(_STORAGE_LOCK_FILE)
        try:
            safe_obj = dict(obj)
            safe_obj[_UPDATED_TS_KEY] = int(time.time())
            payload = json.dumps(safe_obj, ensure_ascii=False)
            tmp = _BINDINGS_FILE.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(_BINDINGS_FILE)
        finally:
            _release_file_lock(_STORAGE_LOCK_FILE)


def _acquire_file_lock(path: Path, *, timeout_sec: float = 10.0) -> None:
    started = time.time()
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            os.close(fd)
            return
        except FileExistsError:
            if time.time() - started >= timeout_sec:
                raise RuntimeError(f"Storage lock timeout: {path}")
            time.sleep(0.05)


def _release_file_lock(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def acquire_instance_lock_or_raise() -> None:
    _ensure_files()
    _acquire_file_lock(_INSTANCE_LOCK_FILE, timeout_sec=0.2)


def release_instance_lock() -> None:
    _release_file_lock(_INSTANCE_LOCK_FILE)


def set_destination_channel_id(*, guild_id: int, channel_id: int) -> None:
    data = _read_json()
    data[str(guild_id)] = int(channel_id)
    _write_json(data)


def get_destination_channel_id(*, guild_id: int) -> int | None:
    data = _read_json()
    raw = data.get(str(guild_id))
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_reports_channel_id(*, guild_id: int, channel_id: int) -> None:
    data = _read_json()
    data[f"{guild_id}:reports_channel_id"] = int(channel_id)
    _write_json(data)


def get_reports_channel_id(*, guild_id: int) -> int | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:reports_channel_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_logs_channel_id(*, guild_id: int, channel_id: int) -> None:
    data = _read_json()
    data[f"{guild_id}:logs_channel_id"] = int(channel_id)
    _write_json(data)


def get_logs_channel_id(*, guild_id: int) -> int | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:logs_channel_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_reports_panel_message_id(*, guild_id: int, channel_id: int, message_id: int) -> None:
    data = _read_json()
    data[f"{guild_id}:reports_panel"] = {"channel_id": int(channel_id), "message_id": int(message_id)}
    _write_json(data)


def get_reports_panel_message_id(*, guild_id: int) -> tuple[int, int] | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:reports_panel")
    if not isinstance(raw, dict):
        return None
    try:
        return int(raw["channel_id"]), int(raw["message_id"])
    except Exception:
        return None


def set_report_types(*, guild_id: int, types: list[dict[str, Any]]) -> None:
    data = _read_json()
    key = f"{guild_id}:report_types"
    clean: list[dict[str, Any]] = []
    for item in types:
        if not isinstance(item, dict):
            continue
        raw_key = str(item.get("key", "")).strip().lower()
        raw_key = "".join(ch for ch in raw_key if ch.isalnum() or ch == "_")[:32]
        label = str(item.get("label", "")).strip()[:100]
        desc = str(item.get("desc", "")).strip()[:100]
        try:
            reward = int(item.get("reward", 0))
        except (TypeError, ValueError):
            continue
        if not raw_key or not label or reward <= 0:
            continue
        clean.append({"key": raw_key, "label": label, "desc": desc, "reward": reward})
    data[key] = clean
    _write_json(data)


def get_report_types(*, guild_id: int) -> list[dict[str, Any]]:
    data = _read_json()
    raw = data.get(f"{guild_id}:report_types", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip().lower()
        key = "".join(ch for ch in key if ch.isalnum() or ch == "_")[:32]
        label = str(item.get("label", "")).strip()[:100]
        desc = str(item.get("desc", "")).strip()[:100]
        try:
            reward = int(item.get("reward", 0))
        except (TypeError, ValueError):
            continue
        if not key or not label or reward <= 0:
            continue
        out.append({"key": key, "label": label, "desc": desc, "reward": reward})
    return out


def next_ticket_id(*, guild_id: int) -> int:
    data = _read_json()
    key = f"{guild_id}:ticket_counter"
    current = data.get(key, 0)
    try:
        current_int = int(current)
    except (TypeError, ValueError):
        current_int = 0
    new_val = current_int + 1
    data[key] = new_val
    _write_json(data)
    return new_val


def set_panel_message_id(*, guild_id: int, channel_id: int, message_id: int) -> None:
    data = _read_json()
    data[f"{guild_id}:panel"] = {"channel_id": int(channel_id), "message_id": int(message_id)}
    _write_json(data)


def get_panel_message_id(*, guild_id: int) -> tuple[int, int] | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:panel")
    if not isinstance(raw, dict):
        return None
    try:
        return int(raw["channel_id"]), int(raw["message_id"])
    except Exception:
        return None


def set_ticket_view_role_ids(*, guild_id: int, role_ids: list[int]) -> None:
    data = _read_json()
    data[f"{guild_id}:ticket_view_roles"] = [int(x) for x in role_ids]
    _write_json(data)


def get_ticket_view_role_ids(*, guild_id: int) -> list[int]:
    data = _read_json()
    raw = data.get(f"{guild_id}:ticket_view_roles", [])
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for x in raw:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def set_call_category_id(*, guild_id: int, category_id: int | None) -> None:
    data = _read_json()
    key = f"{guild_id}:call_category_id"
    if category_id is None:
        data.pop(key, None)
    else:
        data[key] = int(category_id)
    _write_json(data)


def get_call_category_id(*, guild_id: int) -> int | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:call_category_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_role_ping_notify_binding(*, guild_id: int, category_id: int | None, role_id: int | None) -> None:
    data = _read_json()
    key = f"{guild_id}:role_ping_notify_binding"
    if category_id is None or role_id is None:
        data.pop(key, None)
    else:
        data[key] = {"category_id": int(category_id), "role_id": int(role_id)}
    _write_json(data)


def get_role_ping_notify_binding(*, guild_id: int) -> tuple[int, int] | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:role_ping_notify_binding")
    if not isinstance(raw, dict):
        return None
    try:
        return int(raw.get("category_id")), int(raw.get("role_id"))
    except (TypeError, ValueError):
        return None


def set_voice_lobby_channel_id(*, guild_id: int, channel_id: int | None) -> None:
    data = _read_json()
    key = f"{guild_id}:voice_lobby_channel_id"
    if channel_id is None:
        data.pop(key, None)
    else:
        data[key] = int(channel_id)
    _write_json(data)


def get_voice_lobby_channel_id(*, guild_id: int) -> int | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:voice_lobby_channel_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_temp_voice_owner_id(*, guild_id: int, channel_id: int, owner_id: int) -> None:
    data = _read_json()
    key = f"{guild_id}:temp_voice_owners"
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        raw = {}
    raw[str(int(channel_id))] = int(owner_id)
    data[key] = raw
    _write_json(data)


def get_temp_voice_owner_id(*, guild_id: int, channel_id: int) -> int | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:temp_voice_owners", {})
    if not isinstance(raw, dict):
        return None
    owner = raw.get(str(int(channel_id)))
    if owner is None:
        return None
    try:
        return int(owner)
    except (TypeError, ValueError):
        return None


def remove_temp_voice_owner_id(*, guild_id: int, channel_id: int) -> None:
    data = _read_json()
    key = f"{guild_id}:temp_voice_owners"
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        return
    raw.pop(str(int(channel_id)), None)
    data[key] = raw
    _write_json(data)


def set_voice_hub_panel_message_id(*, guild_id: int, channel_id: int, message_id: int) -> None:
    data = _read_json()
    data[f"{guild_id}:voice_hub_panel"] = {"channel_id": int(channel_id), "message_id": int(message_id)}
    _write_json(data)


def get_voice_hub_panel_message_id(*, guild_id: int) -> tuple[int, int] | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:voice_hub_panel")
    if not isinstance(raw, dict):
        return None
    try:
        return int(raw["channel_id"]), int(raw["message_id"])
    except Exception:
        return None


def set_portfolio_category_id(*, guild_id: int, category_id: int | None) -> None:
    data = _read_json()
    key = f"{guild_id}:portfolio_category_id"
    if category_id is None:
        data.pop(key, None)
    else:
        data[key] = int(category_id)
    _write_json(data)


def get_portfolio_category_id(*, guild_id: int) -> int | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:portfolio_category_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def get_portfolio_profile(*, guild_id: int, user_id: int) -> dict[str, Any]:
    data = _read_json()
    raw = data.get(f"{guild_id}:portfolio_profiles", {})
    if not isinstance(raw, dict):
        return {}
    prof = raw.get(str(int(user_id)), {})
    return prof if isinstance(prof, dict) else {}


def set_portfolio_profile(*, guild_id: int, user_id: int, profile: dict[str, Any]) -> None:
    data = _read_json()
    key = f"{guild_id}:portfolio_profiles"
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        raw = {}
    raw[str(int(user_id))] = profile
    data[key] = raw
    _write_json(data)


def set_tier_role_id(*, guild_id: int, tier: int, role_id: int | None) -> None:
    data = _read_json()
    key = f"{guild_id}:tier_roles"
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        raw = {}
    tkey = str(int(tier))
    if role_id is None:
        raw.pop(tkey, None)
    else:
        raw[tkey] = int(role_id)
    data[key] = raw
    _write_json(data)


def get_tier_role_id(*, guild_id: int, tier: int) -> int | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:tier_roles", {})
    if not isinstance(raw, dict):
        return None
    rid = raw.get(str(int(tier)))
    if rid is None:
        return None
    try:
        return int(rid)
    except (TypeError, ValueError):
        return None


def set_rank_role_id(*, guild_id: int, rank: int, role_id: int | None) -> None:
    data = _read_json()
    key = f"{guild_id}:rank_roles"
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        raw = {}
    rkey = str(int(rank))
    if role_id is None:
        raw.pop(rkey, None)
    else:
        raw[rkey] = int(role_id)
    data[key] = raw
    _write_json(data)


def get_rank_role_id(*, guild_id: int, rank: int) -> int | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:rank_roles", {})
    if not isinstance(raw, dict):
        return None
    rid = raw.get(str(int(rank)))
    if rid is None:
        return None
    try:
        return int(rid)
    except (TypeError, ValueError):
        return None


def set_portfolio_channel_owner_id(*, guild_id: int, channel_id: int, owner_id: int) -> None:
    data = _read_json()
    key = f"{guild_id}:portfolio_channel_owners"
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        raw = {}
    raw[str(int(channel_id))] = int(owner_id)
    data[key] = raw
    _write_json(data)


def get_portfolio_channel_owner_id(*, guild_id: int, channel_id: int) -> int | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:portfolio_channel_owners", {})
    if not isinstance(raw, dict):
        return None
    owner = raw.get(str(int(channel_id)))
    if owner is None:
        return None
    try:
        return int(owner)
    except (TypeError, ValueError):
        return None


def set_accept_role_id(*, guild_id: int, role_id: int | None) -> None:
    data = _read_json()
    key = f"{guild_id}:accept_role_id"
    if role_id is None:
        data.pop(key, None)
    else:
        data[key] = int(role_id)
    _write_json(data)


def get_accept_role_id(*, guild_id: int) -> int | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:accept_role_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _accept_role_type_key(application_type: str) -> str:
    t = (application_type or "").strip().upper()
    if t in {"RP", "VZP"}:
        return t
    if t in {"CAPT/BIZ", "CAPT_BIZ", "CAPTBIZ"}:
        return "CAPT_BIZ"
    # для строк типа "Capt/Biz"
    if "CAPT" in t or "BIZ" in t:
        return "CAPT_BIZ"
    return t or "RP"


def _application_type_key(application_type: str) -> str:
    t = (application_type or "").strip().upper()
    if t in {"RP", "VZP"}:
        return t
    if t in {"CAPT/BIZ", "CAPT_BIZ", "CAPTBIZ"}:
        return "CAPT_BIZ"
    if "CAPT" in t or "BIZ" in t:
        return "CAPT_BIZ"
    return t or "RP"


def set_accept_role_id_for_type(*, guild_id: int, application_type: str, role_id: int | None) -> None:
    data = _read_json()
    t = _accept_role_type_key(application_type)
    key = f"{guild_id}:accept_role_id:{t}"
    if role_id is None:
        data.pop(key, None)
    else:
        data[key] = int(role_id)
    _write_json(data)


def get_accept_role_id_for_type(*, guild_id: int, application_type: str) -> int | None:
    data = _read_json()
    t = _accept_role_type_key(application_type)
    raw = data.get(f"{guild_id}:accept_role_id:{t}")
    if raw is None:
        # fallback на старую общую настройку (если тип ещё не настроен)
        raw = data.get(f"{guild_id}:accept_role_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_applications_enabled_for_type(*, guild_id: int, application_type: str, enabled: bool) -> None:
    data = _read_json()
    t = _application_type_key(application_type)
    data[f"{guild_id}:applications_enabled:{t}"] = bool(enabled)
    _write_json(data)


def get_applications_enabled_for_type(*, guild_id: int, application_type: str) -> bool:
    data = _read_json()
    t = _application_type_key(application_type)
    raw = data.get(f"{guild_id}:applications_enabled:{t}")
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on", "enable", "enabled"}
    if isinstance(raw, (int, float)):
        return bool(raw)
    return True


def set_daily_message_config(
    *,
    guild_id: int,
    channel_id: int | None = None,
    hour: int | None = None,
    minute: int | None = None,
    text: str | None = None,
) -> None:
    data = _read_json()
    key = f"{guild_id}:daily_message"
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        raw = {}
    if channel_id is not None:
        raw["channel_id"] = int(channel_id)
    if hour is not None:
        raw["hour"] = int(hour)
    if minute is not None:
        raw["minute"] = int(minute)
    if text is not None:
        raw["text"] = str(text)
    data[key] = raw
    _write_json(data)


def clear_daily_message_config(*, guild_id: int) -> None:
    data = _read_json()
    data.pop(f"{guild_id}:daily_message", None)
    data.pop(f"{guild_id}:daily_message_last", None)
    _write_json(data)


def get_daily_message_config(*, guild_id: int) -> dict[str, Any]:
    data = _read_json()
    raw = data.get(f"{guild_id}:daily_message", {})
    return raw if isinstance(raw, dict) else {}


def set_daily_message_last_sent(*, guild_id: int, ymd: str | None) -> None:
    data = _read_json()
    key = f"{guild_id}:daily_message_last"
    if not ymd:
        data.pop(key, None)
    else:
        data[key] = str(ymd)
    _write_json(data)


def get_daily_message_last_sent(*, guild_id: int) -> str | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:daily_message_last")
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def get_daily_message_entries(*, guild_id: int) -> list[dict[str, Any]]:
    data = _read_json()
    raw = data.get(f"{guild_id}:daily_message_entries", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            entry_id = int(item.get("id"))
            channel_id = int(item.get("channel_id"))
            hour = int(item.get("hour"))
            minute = int(item.get("minute"))
        except (TypeError, ValueError):
            continue
        text = str(item.get("text") or "").strip()
        if entry_id <= 0 or channel_id <= 0 or hour < 0 or hour > 23 or minute < 0 or minute > 59 or not text:
            continue
        out.append(
            {
                "id": entry_id,
                "channel_id": channel_id,
                "hour": hour,
                "minute": minute,
                "text": text,
            }
        )
    out.sort(key=lambda x: (int(x["hour"]), int(x["minute"]), int(x["id"])))
    return out


def add_daily_message_entry(*, guild_id: int, channel_id: int, hour: int, minute: int, text: str) -> int:
    data = _read_json()
    entries = get_daily_message_entries(guild_id=guild_id)
    seq_key = f"{guild_id}:daily_message_entries_seq"
    try:
        seq = int(data.get(seq_key, 0))
    except (TypeError, ValueError):
        seq = 0
    new_id = seq + 1
    entries.append(
        {
            "id": int(new_id),
            "channel_id": int(channel_id),
            "hour": int(hour),
            "minute": int(minute),
            "text": str(text).strip(),
        }
    )
    data[f"{guild_id}:daily_message_entries"] = entries
    data[seq_key] = int(new_id)
    _write_json(data)
    return int(new_id)


def remove_daily_message_entry(*, guild_id: int, entry_id: int) -> bool:
    data = _read_json()
    entries = get_daily_message_entries(guild_id=guild_id)
    kept = [x for x in entries if int(x.get("id", 0)) != int(entry_id)]
    removed = len(kept) != len(entries)
    data[f"{guild_id}:daily_message_entries"] = kept
    sent_key = f"{guild_id}:daily_message_sent_map"
    sent_raw = data.get(sent_key, {})
    if isinstance(sent_raw, dict):
        sent_raw.pop(str(int(entry_id)), None)
        data[sent_key] = sent_raw
    _write_json(data)
    return removed


def clear_daily_message_entries(*, guild_id: int) -> None:
    data = _read_json()
    data.pop(f"{guild_id}:daily_message_entries", None)
    data.pop(f"{guild_id}:daily_message_entries_seq", None)
    data.pop(f"{guild_id}:daily_message_sent_map", None)
    _write_json(data)


def get_daily_message_sent_map(*, guild_id: int) -> dict[int, str]:
    data = _read_json()
    raw = data.get(f"{guild_id}:daily_message_sent_map", {})
    if not isinstance(raw, dict):
        return {}
    out: dict[int, str] = {}
    for k, v in raw.items():
        try:
            eid = int(k)
        except (TypeError, ValueError):
            continue
        ymd = str(v or "").strip()
        if eid > 0 and ymd:
            out[eid] = ymd
    return out


def set_daily_message_sent_for_entry(*, guild_id: int, entry_id: int, ymd: str | None) -> None:
    data = _read_json()
    key = f"{guild_id}:daily_message_sent_map"
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        raw = {}
    if not ymd:
        raw.pop(str(int(entry_id)), None)
    else:
        raw[str(int(entry_id))] = str(ymd)
    data[key] = raw
    _write_json(data)


def set_afk(*, guild_id: int, user_id: int, until_ts: int, reason: str) -> None:
    data = _read_json()
    key = f"{guild_id}:afk"
    afk_obj = data.get(key, {})
    if not isinstance(afk_obj, dict):
        afk_obj = {}
    afk_obj[str(int(user_id))] = {"until_ts": int(until_ts), "reason": str(reason)}
    data[key] = afk_obj
    _write_json(data)


def clear_afk(*, guild_id: int, user_id: int) -> None:
    data = _read_json()
    key = f"{guild_id}:afk"
    afk_obj = data.get(key, {})
    if not isinstance(afk_obj, dict):
        return
    afk_obj.pop(str(int(user_id)), None)
    data[key] = afk_obj
    _write_json(data)


def get_afk_map(*, guild_id: int) -> dict[int, dict[str, Any]]:
    data = _read_json()
    raw = data.get(f"{guild_id}:afk", {})
    if not isinstance(raw, dict):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for uid, payload in raw.items():
        try:
            uid_int = int(uid)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            out[uid_int] = payload
    return out


def set_afk_panel_message_id(*, guild_id: int, channel_id: int, message_id: int) -> None:
    data = _read_json()
    data[f"{guild_id}:afk_panel"] = {"channel_id": int(channel_id), "message_id": int(message_id)}
    _write_json(data)


def get_afk_panel_message_id(*, guild_id: int) -> tuple[int, int] | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:afk_panel")
    if not isinstance(raw, dict):
        return None
    try:
        return int(raw["channel_id"]), int(raw["message_id"])
    except Exception:
        return None


def set_vacation(
    *,
    guild_id: int,
    user_id: int,
    until_ts: int,
    reason: str,
    duration_text: str,
    removed_role_ids: list[int] | None = None,
) -> None:
    data = _read_json()
    key = f"{guild_id}:vacation"
    obj = data.get(key, {})
    if not isinstance(obj, dict):
        obj = {}
    obj[str(int(user_id))] = {
        "until_ts": int(until_ts),
        "reason": str(reason),
        "duration_text": str(duration_text),
        "removed_role_ids": [int(x) for x in (removed_role_ids or [])],
    }
    data[key] = obj
    _write_json(data)


def clear_vacation(*, guild_id: int, user_id: int) -> None:
    data = _read_json()
    key = f"{guild_id}:vacation"
    obj = data.get(key, {})
    if not isinstance(obj, dict):
        return
    obj.pop(str(int(user_id)), None)
    data[key] = obj
    _write_json(data)


def get_vacation_map(*, guild_id: int) -> dict[int, dict[str, Any]]:
    data = _read_json()
    raw = data.get(f"{guild_id}:vacation", {})
    if not isinstance(raw, dict):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for uid, payload in raw.items():
        try:
            uid_int = int(uid)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            out[uid_int] = payload
    return out


def set_vacation_panel_message_id(*, guild_id: int, channel_id: int, message_id: int) -> None:
    data = _read_json()
    data[f"{guild_id}:vacation_panel"] = {"channel_id": int(channel_id), "message_id": int(message_id)}
    _write_json(data)


def get_vacation_panel_message_id(*, guild_id: int) -> tuple[int, int] | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:vacation_panel")
    if not isinstance(raw, dict):
        return None
    try:
        return int(raw["channel_id"]), int(raw["message_id"])
    except Exception:
        return None


def set_vacation_channel_id(*, guild_id: int, channel_id: int) -> None:
    data = _read_json()
    data[f"{guild_id}:vacation_channel_id"] = int(channel_id)
    _write_json(data)


def get_vacation_channel_id(*, guild_id: int) -> int | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:vacation_channel_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_vacation_role_id(*, guild_id: int, role_id: int | None) -> None:
    data = _read_json()
    key = f"{guild_id}:vacation_role_id"
    if role_id is None:
        data.pop(key, None)
    else:
        data[key] = int(role_id)
    _write_json(data)


def get_vacation_role_id(*, guild_id: int) -> int | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:vacation_role_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_vacation_remove_role_ids(*, guild_id: int, role_ids: list[int]) -> None:
    data = _read_json()
    data[f"{guild_id}:vacation_remove_role_ids"] = [int(x) for x in role_ids]
    _write_json(data)


def get_vacation_remove_role_ids(*, guild_id: int) -> list[int]:
    data = _read_json()
    raw = data.get(f"{guild_id}:vacation_remove_role_ids", [])
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for x in raw:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def get_points_map(*, guild_id: int) -> dict[int, float]:
    data = _read_json()
    raw = data.get(f"{guild_id}:points", {})
    if not isinstance(raw, dict):
        return {}
    out: dict[int, float] = {}
    for uid, balance in raw.items():
        try:
            uid_int = int(uid)
            bal = float(balance)
        except (TypeError, ValueError):
            continue
        out[uid_int] = max(0.0, bal)
    return out


def get_user_points(*, guild_id: int, user_id: int) -> float:
    return float(get_points_map(guild_id=guild_id).get(int(user_id), 0.0))


def set_user_points(*, guild_id: int, user_id: int, points: float) -> float:
    data = _read_json()
    key = f"{guild_id}:points"
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        raw = {}
    safe_points = max(0.0, float(points))
    raw[str(int(user_id))] = safe_points
    data[key] = raw
    _write_json(data)
    return safe_points


def add_user_points(*, guild_id: int, user_id: int, delta: float) -> float:
    current = get_user_points(guild_id=guild_id, user_id=user_id)
    new_val = max(0.0, current + float(delta))
    return set_user_points(guild_id=guild_id, user_id=user_id, points=new_val)


def get_pending_reports(*, guild_id: int, user_id: int) -> list[dict[str, Any]]:
    data = _read_json()
    raw = data.get(f"{guild_id}:pending_reports", {})
    if not isinstance(raw, dict):
        return []
    user_raw = raw.get(str(int(user_id)), [])
    if not isinstance(user_raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in user_raw:
        if isinstance(item, dict):
            out.append(item)
    return out


def add_pending_report(
    *,
    guild_id: int,
    user_id: int,
    review_message_id: int,
    report_type: str,
    report_url: str,
    created_ts: int,
) -> None:
    data = _read_json()
    key = f"{guild_id}:pending_reports"
    obj = data.get(key, {})
    if not isinstance(obj, dict):
        obj = {}
    user_key = str(int(user_id))
    current = obj.get(user_key, [])
    if not isinstance(current, list):
        current = []
    current.append(
        {
            "review_message_id": int(review_message_id),
            "type": str(report_type),
            "url": str(report_url),
            "created_ts": int(created_ts),
        }
    )
    obj[user_key] = current
    data[key] = obj
    _write_json(data)


def remove_pending_report(*, guild_id: int, user_id: int, review_message_id: int) -> None:
    data = _read_json()
    key = f"{guild_id}:pending_reports"
    obj = data.get(key, {})
    if not isinstance(obj, dict):
        return
    user_key = str(int(user_id))
    current = obj.get(user_key, [])
    if not isinstance(current, list):
        return
    kept: list[dict[str, Any]] = []
    for item in current:
        if not isinstance(item, dict):
            continue
        try:
            mid = int(item.get("review_message_id"))
        except (TypeError, ValueError):
            continue
        if mid != int(review_message_id):
            kept.append(item)
    obj[user_key] = kept
    data[key] = obj
    _write_json(data)


def set_shop_orders_channel_id(*, guild_id: int, channel_id: int) -> None:
    data = _read_json()
    data[f"{guild_id}:shop_orders_channel_id"] = int(channel_id)
    _write_json(data)


def get_shop_orders_channel_id(*, guild_id: int) -> int | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:shop_orders_channel_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_shop_items(*, guild_id: int, items: list[dict[str, Any]]) -> None:
    data = _read_json()
    key = f"{guild_id}:shop_items"
    clean: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        try:
            price = int(item.get("price", 0))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        clean.append({"name": name[:100], "price": price})
    data[key] = clean
    _write_json(data)


def get_shop_items(*, guild_id: int) -> list[dict[str, Any]]:
    data = _read_json()
    raw = data.get(f"{guild_id}:shop_items", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        try:
            price = int(item.get("price", 0))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        out.append({"name": name, "price": price})
    return out


def set_shop_panel_message_id(*, guild_id: int, channel_id: int, message_id: int) -> None:
    data = _read_json()
    data[f"{guild_id}:shop_panel"] = {"channel_id": int(channel_id), "message_id": int(message_id)}
    _write_json(data)


def get_shop_panel_message_id(*, guild_id: int) -> tuple[int, int] | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:shop_panel")
    if not isinstance(raw, dict):
        return None
    try:
        return int(raw["channel_id"]), int(raw["message_id"])
    except Exception:
        return None


def set_promo_channel_id(*, guild_id: int, channel_id: int) -> None:
    data = _read_json()
    data[f"{guild_id}:promo_channel_id"] = int(channel_id)
    _write_json(data)


def get_promo_channel_id(*, guild_id: int) -> int | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:promo_channel_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_stream_announce_channel_id(*, guild_id: int, channel_id: int) -> None:
    data = _read_json()
    data[f"{guild_id}:stream_announce_channel_id"] = int(channel_id)
    _write_json(data)


def get_stream_announce_channel_id(*, guild_id: int) -> int | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:stream_announce_channel_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_stream_announce_user_ids(*, guild_id: int, user_ids: list[int]) -> None:
    data = _read_json()
    data[f"{guild_id}:stream_announce_user_ids"] = [int(x) for x in user_ids]
    _write_json(data)


def get_stream_announce_user_ids(*, guild_id: int) -> list[int]:
    data = _read_json()
    raw = data.get(f"{guild_id}:stream_announce_user_ids", [])
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for x in raw:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def set_giveaway_notify_role_ids(*, guild_id: int, role_ids: list[int]) -> None:
    data = _read_json()
    data[f"{guild_id}:giveaway_notify_role_ids"] = [int(x) for x in role_ids]
    _write_json(data)


def get_giveaway_notify_role_ids(*, guild_id: int) -> list[int]:
    data = _read_json()
    raw = data.get(f"{guild_id}:giveaway_notify_role_ids", [])
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for x in raw:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def set_stream_announce_twitch_map(*, guild_id: int, mapping: dict[int, str]) -> None:
    data = _read_json()
    cleaned: dict[str, str] = {}
    for uid, login in mapping.items():
        try:
            user_id = int(uid)
        except (TypeError, ValueError):
            continue
        tw = str(login).strip().lower()
        if not tw:
            continue
        cleaned[str(user_id)] = tw[:50]
    data[f"{guild_id}:stream_announce_twitch_map"] = cleaned
    _write_json(data)


def get_stream_announce_twitch_map(*, guild_id: int) -> dict[int, str]:
    data = _read_json()
    raw = data.get(f"{guild_id}:stream_announce_twitch_map", {})
    if not isinstance(raw, dict):
        return {}
    out: dict[int, str] = {}
    for k, v in raw.items():
        try:
            uid = int(k)
        except (TypeError, ValueError):
            continue
        tw = str(v).strip().lower()
        if not tw:
            continue
        out[uid] = tw
    return out

def set_promo_panel_message_id(*, guild_id: int, channel_id: int, message_id: int) -> None:
    data = _read_json()
    data[f"{guild_id}:promo_panel"] = {"channel_id": int(channel_id), "message_id": int(message_id)}
    _write_json(data)


def get_promo_panel_message_id(*, guild_id: int) -> tuple[int, int] | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:promo_panel")
    if not isinstance(raw, dict):
        return None
    try:
        return int(raw["channel_id"]), int(raw["message_id"])
    except Exception:
        return None


def set_attack_def_cooldown_config(*, guild_id: int, att_minutes: int | None = None, deff_minutes: int | None = None) -> None:
    data = _read_json()
    key = f"{guild_id}:attack_def_cooldown_config"
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        raw = {}
    if att_minutes is not None:
        raw["att_minutes"] = max(1, int(att_minutes))
    if deff_minutes is not None:
        raw["deff_minutes"] = max(1, int(deff_minutes))
    data[key] = raw
    _write_json(data)


def get_attack_def_cooldown_config(*, guild_id: int) -> dict[str, int]:
    data = _read_json()
    raw = data.get(f"{guild_id}:attack_def_cooldown_config", {})
    if not isinstance(raw, dict):
        raw = {}
    try:
        att_minutes = max(1, int(raw.get("att_minutes", 120)))
    except (TypeError, ValueError):
        att_minutes = 120
    try:
        deff_minutes = max(1, int(raw.get("deff_minutes", 120)))
    except (TypeError, ValueError):
        deff_minutes = 120
    return {"att_minutes": att_minutes, "deff_minutes": deff_minutes}


def set_attack_def_cooldown_until(
    *,
    guild_id: int,
    att_until_ts: int | None = None,
    deff_until_ts: int | None = None,
) -> None:
    data = _read_json()
    key = f"{guild_id}:attack_def_cooldown_until"
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        raw = {}
    if att_until_ts is not None:
        raw["att_until_ts"] = int(att_until_ts)
    if deff_until_ts is not None:
        raw["deff_until_ts"] = int(deff_until_ts)
    data[key] = raw
    _write_json(data)


def get_attack_def_cooldown_until(*, guild_id: int) -> dict[str, int]:
    data = _read_json()
    raw = data.get(f"{guild_id}:attack_def_cooldown_until", {})
    if not isinstance(raw, dict):
        raw = {}
    out: dict[str, int] = {}
    for key in ("att_until_ts", "deff_until_ts"):
        val = raw.get(key)
        try:
            iv = int(val)
        except (TypeError, ValueError):
            continue
        if iv > 0:
            out[key] = iv
    return out


def set_attack_def_panel_message_id(*, guild_id: int, channel_id: int, message_id: int) -> None:
    data = _read_json()
    data[f"{guild_id}:attack_def_panel"] = {"channel_id": int(channel_id), "message_id": int(message_id)}
    _write_json(data)


def get_attack_def_panel_message_id(*, guild_id: int) -> tuple[int, int] | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:attack_def_panel")
    if not isinstance(raw, dict):
        return None
    try:
        return int(raw["channel_id"]), int(raw["message_id"])
    except Exception:
        return None


def set_contracts_channel_id(*, guild_id: int, channel_id: int) -> None:
    data = _read_json()
    data[f"{guild_id}:contracts_channel_id"] = int(channel_id)
    _write_json(data)


def get_contracts_channel_id(*, guild_id: int) -> int | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:contracts_channel_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_contracts_panel_message_id(*, guild_id: int, channel_id: int, message_id: int) -> None:
    data = _read_json()
    data[f"{guild_id}:contracts_panel"] = {"channel_id": int(channel_id), "message_id": int(message_id)}
    _write_json(data)


def get_contracts_panel_message_id(*, guild_id: int) -> tuple[int, int] | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:contracts_panel")
    if not isinstance(raw, dict):
        return None
    try:
        return int(raw["channel_id"]), int(raw["message_id"])
    except Exception:
        return None


def set_giveaway_state(*, guild_id: int, message_id: int, payload: dict[str, Any]) -> None:
    data = _read_json()
    key = f"{guild_id}:giveaways"
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        raw = {}
    raw[str(int(message_id))] = payload
    data[key] = raw
    _write_json(data)


def get_giveaway_state(*, guild_id: int, message_id: int) -> dict[str, Any] | None:
    data = _read_json()
    raw = data.get(f"{guild_id}:giveaways", {})
    if not isinstance(raw, dict):
        return None
    payload = raw.get(str(int(message_id)))
    if not isinstance(payload, dict):
        return None
    return payload


def remove_giveaway_state(*, guild_id: int, message_id: int) -> None:
    data = _read_json()
    key = f"{guild_id}:giveaways"
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        return
    raw.pop(str(int(message_id)), None)
    data[key] = raw
    _write_json(data)


def get_pending_shop_orders(*, guild_id: int, user_id: int) -> list[dict[str, Any]]:
    data = _read_json()
    raw = data.get(f"{guild_id}:pending_shop_orders", {})
    if not isinstance(raw, dict):
        return []
    user_raw = raw.get(str(int(user_id)), [])
    if not isinstance(user_raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in user_raw:
        if isinstance(item, dict):
            out.append(item)
    return out


def add_pending_shop_order(
    *,
    guild_id: int,
    user_id: int,
    review_message_id: int,
    item_name: str,
    price: float,
    created_ts: int,
    debited: bool = False,
) -> None:
    data = _read_json()
    key = f"{guild_id}:pending_shop_orders"
    obj = data.get(key, {})
    if not isinstance(obj, dict):
        obj = {}
    user_key = str(int(user_id))
    current = obj.get(user_key, [])
    if not isinstance(current, list):
        current = []
    current.append(
        {
            "review_message_id": int(review_message_id),
            "item": str(item_name),
            "price": float(price),
            "created_ts": int(created_ts),
            "debited": bool(debited),
        }
    )
    obj[user_key] = current
    data[key] = obj
    _write_json(data)


def remove_pending_shop_order(*, guild_id: int, user_id: int, review_message_id: int) -> None:
    data = _read_json()
    key = f"{guild_id}:pending_shop_orders"
    obj = data.get(key, {})
    if not isinstance(obj, dict):
        return
    user_key = str(int(user_id))
    current = obj.get(user_key, [])
    if not isinstance(current, list):
        return
    kept: list[dict[str, Any]] = []
    for item in current:
        if not isinstance(item, dict):
            continue
        try:
            mid = int(item.get("review_message_id"))
        except (TypeError, ValueError):
            continue
        if mid != int(review_message_id):
            kept.append(item)
    obj[user_key] = kept
    data[key] = obj
    _write_json(data)


def get_giveaway_states_for_guild(*, guild_id: int) -> dict[int, dict[str, Any]]:
    data = _read_json()
    raw = data.get(f"{guild_id}:giveaways", {})
    if not isinstance(raw, dict):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for key, payload in raw.items():
        try:
            message_id = int(key)
        except (TypeError, ValueError):
            continue
        if message_id <= 0 or not isinstance(payload, dict):
            continue
        out[message_id] = payload
    return out


def set_twitch_live_state_by_guild(*, state: dict[int, list[int] | set[int]]) -> None:
    data = _read_json()
    key = "runtime:twitch_live_state_by_guild"
    cleaned: dict[str, list[int]] = {}
    for guild_id, user_ids in state.items():
        try:
            gid = int(guild_id)
        except (TypeError, ValueError):
            continue
        items = user_ids if isinstance(user_ids, (list, set, tuple)) else []
        uniq: list[int] = []
        seen: set[int] = set()
        for uid in items:
            try:
                uid_int = int(uid)
            except (TypeError, ValueError):
                continue
            if uid_int <= 0 or uid_int in seen:
                continue
            seen.add(uid_int)
            uniq.append(uid_int)
        cleaned[str(gid)] = uniq
    data[key] = cleaned
    _write_json(data)


def get_twitch_live_state_by_guild() -> dict[int, set[int]]:
    data = _read_json()
    raw = data.get("runtime:twitch_live_state_by_guild", {})
    if not isinstance(raw, dict):
        return {}
    out: dict[int, set[int]] = {}
    for guild_id, payload in raw.items():
        try:
            gid = int(guild_id)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, list):
            continue
        ids: set[int] = set()
        for uid in payload:
            try:
                uid_int = int(uid)
            except (TypeError, ValueError):
                continue
            if uid_int > 0:
                ids.add(uid_int)
        out[gid] = ids
    return out


def set_daily_menu_message_ids(*, mapping: dict[tuple[int, int], int]) -> None:
    data = _read_json()
    key = "runtime:daily_menu_message_ids"
    cleaned: dict[str, int] = {}
    for pair, message_id in mapping.items():
        if not isinstance(pair, tuple) or len(pair) != 2:
            continue
        try:
            guild_id = int(pair[0])
            user_id = int(pair[1])
            mid = int(message_id)
        except (TypeError, ValueError):
            continue
        if guild_id <= 0 or user_id <= 0 or mid <= 0:
            continue
        cleaned[f"{guild_id}:{user_id}"] = mid
    data[key] = cleaned
    _write_json(data)


def get_daily_menu_message_ids() -> dict[tuple[int, int], int]:
    data = _read_json()
    raw = data.get("runtime:daily_menu_message_ids", {})
    if not isinstance(raw, dict):
        return {}
    out: dict[tuple[int, int], int] = {}
    for pair_key, message_id in raw.items():
        if not isinstance(pair_key, str):
            continue
        parts = pair_key.split(":", 1)
        if len(parts) != 2:
            continue
        try:
            guild_id = int(parts[0])
            user_id = int(parts[1])
            mid = int(message_id)
        except (TypeError, ValueError):
            continue
        if guild_id > 0 and user_id > 0 and mid > 0:
            out[(guild_id, user_id)] = mid
    return out


def set_tg_bridge_pair_state(*, state: dict[str, Any]) -> None:
    data = _read_json()
    key = "runtime:tg_bridge_pair_state"
    if isinstance(state, dict):
        data[key] = state
    else:
        data.pop(key, None)
    _write_json(data)


def get_tg_bridge_pair_state() -> dict[str, Any]:
    data = _read_json()
    raw = data.get("runtime:tg_bridge_pair_state", {})
    return raw if isinstance(raw, dict) else {}


def get_storage_debug_info() -> dict[str, Any]:
    _ensure_files()
    current = _read_bindings_payload()
    project = _read_project_bindings_payload()
    return {
        "data_dir": str(_DATA_DIR),
        "bindings_file": str(_BINDINGS_FILE),
        "project_bindings_file": str(_PROJECT_BINDINGS_FILE),
        "current_keys": len(_payload_without_meta(current)),
        "project_keys": len(_payload_without_meta(project)),
    }


def get_storage_guild_key_count(*, guild_id: int) -> int:
    data = _read_json()
    prefix = f"{int(guild_id)}"
    count = 0
    for key in data.keys():
        try:
            skey = str(key)
        except Exception:
            continue
        if skey == prefix or skey.startswith(prefix + ":"):
            count += 1
    return count

