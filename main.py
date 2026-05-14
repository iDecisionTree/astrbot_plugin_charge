import asyncio
from datetime import datetime, timedelta
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.star import Context, Star, register

try:
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path
except Exception:
    def get_astrbot_data_path():
        return str(Path(__file__).resolve().parent)

def num_to_chinese(num_str: str) -> str:
    mapping = {
        '0': '零', '1': '一', '2': '二', '3': '三', '4': '四',
        '5': '五', '6': '六', '7': '七', '8': '八', '9': '九'
    }
    return mapping.get(num_str, num_str)


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _date_key(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now()).strftime("%Y-%m-%d")

class ChargeAPI:
    BASE_URL = "https://yktydfw.nwu.edu.cn"
    KEYBOARD_URL = f"{BASE_URL}/berserker-secure/keyboard"
    AUTH_URL = f"{BASE_URL}/berserker-auth/oauth/token"
    QUERY_URL = f"{BASE_URL}/charge/feeitem/getThirdData"

    BASIC_AUTH = "bW9iaWxlX3NlcnZpY2VfcGxhdGZvcm06bW9iaWxlX3NlcnZpY2VfcGxhdGZvcm1fc2VjcmV0"

    @staticmethod
    async def _get_keyboard_mapping(client: httpx.AsyncClient) -> Optional[Dict]:
        try:
            resp = await client.get(ChargeAPI.KEYBOARD_URL, params={
                "type": "Standard",
                "order": "0",
                "synAccessSource": "h5"
            })
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return {
                "numberKeyboard": data.get("numberKeyboard", ""),
                "lowerLetterKeyboard": data.get("lowerLetterKeyboard", ""),
                "upperLetterKeyboard": data.get("upperLetterKeyboard", ""),
                "symbolKeyboard": data.get("symbolKeyboard", ""),
                "uuid": data.get("uuid", "")
            }
        except Exception as e:
            logger.error(f"获取键盘映射失败: {e}")
            return None

    @staticmethod
    def _encrypt_password(password: str, mapping: Dict) -> Optional[str]:
        try:
            num_kb = mapping["numberKeyboard"]
            lower_kb = mapping["lowerLetterKeyboard"]
            upper_kb = mapping["upperLetterKeyboard"]
            sym_kb = mapping["symbolKeyboard"]
            uuid = mapping["uuid"]

            original_symbols = [
                '!', '"', '#', '$', '%', '&', '\'', '(', ')', '*', '+', ',', '-', '.', '/',
                '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', ':', ';', '<', '=', '>', '?',
                '@', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O',
                'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z', '[', '\\'
            ]
            symbol_map = {}
            for i, ch in enumerate(original_symbols):
                if i < len(sym_kb):
                    symbol_map[ch] = sym_kb[i]

            encrypted_chars = []
            for ch in password:
                if ch.isdigit():
                    idx = ord(ch) - ord('0')
                    if 0 <= idx < len(num_kb):
                        encrypted_chars.append(num_kb[idx])
                    else:
                        encrypted_chars.append(ch)
                elif ch.islower():
                    idx = ord(ch) - ord('a')
                    if 0 <= idx < len(lower_kb):
                        encrypted_chars.append(lower_kb[idx])
                    else:
                        encrypted_chars.append(ch)
                elif ch.isupper():
                    idx = ord(ch) - ord('A')
                    if 0 <= idx < len(upper_kb):
                        encrypted_chars.append(upper_kb[idx])
                    else:
                        encrypted_chars.append(ch)
                elif ch in symbol_map:
                    encrypted_chars.append(symbol_map[ch])
                else:
                    encrypted_chars.append(ch)
            encrypted = "".join(encrypted_chars)
            return f"{encrypted}$1${uuid}"
        except Exception as e:
            logger.error(f"密码加密失败: {e}")
            return None

    @staticmethod
    async def login(username: str, password: str, client: httpx.AsyncClient) -> Optional[str]:
        mapping = await ChargeAPI._get_keyboard_mapping(client)
        if not mapping:
            return None

        encrypted_pwd = ChargeAPI._encrypt_password(password, mapping)
        if not encrypted_pwd:
            return None

        try:
            headers = {
                "Authorization": f"Basic {ChargeAPI.BASIC_AUTH}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            data = {
                "username": username,
                "password": encrypted_pwd,
                "grant_type": "password",
                "scope": "all",
                "loginForm": "h5",
                "logintype": "snoNew",
                "device_token": "h5",
                "synAccessSource": "h5",
            }
            resp = await client.post(ChargeAPI.AUTH_URL, headers=headers, data=data)
            resp.raise_for_status()
            token = resp.json().get("access_token")
            if token:
                logger.info(f"用户 {username} 登录成功")
                return token
            else:
                logger.error("登录响应中未找到 access_token")
                return None
        except Exception as e:
            logger.error(f"登录提交失败: {e}")
            return None

    @staticmethod
    async def query_charge(build_room_id: str, token: str, client: httpx.AsyncClient) -> Optional[float]:
        try:
            headers = {"synjones-auth": f"bearer {token}"}

            if len(build_room_id) < 3:
                logger.error(f"房间号 {build_room_id} 格式错误，至少需要3位")
                return None
            build_id = build_room_id[:-3]
            floor_id = build_room_id[-3]
            room_id = build_room_id[-2:]

            form = {"feeitemid": "411", "type": "select", "level": "0"}
            resp = await client.post(ChargeAPI.QUERY_URL, headers=headers, data=form)
            resp.raise_for_status()
            data_obj = resp.json().get("map", {}).get("data")
            if data_obj is None:
                logger.error("level0 响应缺少 map.data")
                return None
            if isinstance(data_obj, str):
                campus_list = json.loads(data_obj)
            else:
                campus_list = data_obj
            campus = next((item["value"] for item in campus_list if item["name"] == "长安校区"), None)
            if not campus:
                logger.error("未找到长安校区")
                return None

            form = {"feeitemid": "411", "type": "select", "level": "1", "campus": campus}
            resp = await client.post(ChargeAPI.QUERY_URL, headers=headers, data=form)
            resp.raise_for_status()
            data_obj = resp.json().get("map", {}).get("data")
            if isinstance(data_obj, str):
                build_list = json.loads(data_obj)
            else:
                build_list = data_obj
            build_name = f"{build_id}号楼"
            build = next((item["value"] for item in build_list if item["name"] == build_name), None)
            if not build:
                logger.error(f"未找到楼栋 {build_name}")
                return None

            form = {"feeitemid": "411", "type": "select", "level": "2", "campus": campus, "build": build}
            resp = await client.post(ChargeAPI.QUERY_URL, headers=headers, data=form)
            resp.raise_for_status()
            data_obj = resp.json().get("map", {}).get("data")
            if isinstance(data_obj, str):
                floor_list = json.loads(data_obj)
            else:
                floor_list = data_obj
            floor_name = f"{num_to_chinese(floor_id)}层"
            floor = next((item["value"] for item in floor_list if item["name"] == floor_name), None)
            if not floor:
                logger.error(f"未找到楼层 {floor_name}")
                return None

            form = {
                "feeitemid": "411", "type": "select", "level": "3",
                "campus": campus, "build": build, "floor": floor
            }
            resp = await client.post(ChargeAPI.QUERY_URL, headers=headers, data=form)
            resp.raise_for_status()
            data_obj = resp.json().get("map", {}).get("data")
            if isinstance(data_obj, str):
                room_list = json.loads(data_obj)
            else:
                room_list = data_obj
            room_name = f"c{build_room_id}"
            room = next((item["value"] for item in room_list if item["name"] == room_name), None)
            if not room:
                logger.error(f"未找到房间 {room_name}")
                return None

            form = {
                "feeitemid": "411", "type": "IEC", "level": "4",
                "campus": campus, "build": build, "floor": floor, "room": room
            }
            resp = await client.post(ChargeAPI.QUERY_URL, data=form)
            resp.raise_for_status()
            ele_data = resp.json().get("map", {}).get("data", {})
            power = ele_data.get("elelastdataSyl")
            if power is None:
                logger.error("level4 响应中未找到 elelastdataSyl")
                return None
            return float(power)
        except Exception as e:
            logger.error(f"查询电费失败: {e}")
            return None


def _normalize_account(username: str, password: str) -> Dict[str, str]:
    return {"username": username, "password": password}


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None

@register("charge_query", "YourName", "电费查询", "1.0.0")
class ChargePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.plugin_data_dir = self._resolve_plugin_data_dir()
        self.accounts_file = self.plugin_data_dir / "charge_accounts.json"
        self.legacy_accounts_file = Path(__file__).resolve().with_name("charge_accounts.json")
        self.analysis_file = self.plugin_data_dir / "charge_analysis.json"
        self.global_cred: Optional[Dict] = None
        self.saved_accounts: List[Dict[str, str]] = self._load_saved_accounts()
        self.analysis_store: Dict[str, Any] = self._load_analysis_store()
        self.client = httpx.AsyncClient(timeout=30.0)
        self.scheduler_task: Optional[asyncio.Task] = None

    def _resolve_plugin_data_dir(self) -> Path:
        base_path: Path
        if get_astrbot_data_path is not None:
            try:
                base_path = Path(get_astrbot_data_path())
            except Exception:
                base_path = Path(__file__).resolve().parent
        else:
            base_path = Path(__file__).resolve().parent

        plugin_dir = base_path / "plugin_data" / "astrbot_plugin_charge"
        plugin_dir.mkdir(parents=True, exist_ok=True)
        return plugin_dir

    def _load_saved_accounts(self) -> List[Dict[str, str]]:
        source_file = self.accounts_file if self.accounts_file.exists() else self.legacy_accounts_file
        if not source_file.exists():
            return []

        try:
            raw = json.loads(source_file.read_text(encoding="utf-8"))
            accounts = raw.get("accounts", []) if isinstance(raw, dict) else []
            result: List[Dict[str, str]] = []
            for item in accounts:
                if not isinstance(item, dict):
                    continue
                username = str(item.get("username", "")).strip()
                password = str(item.get("password", ""))
                if username and password:
                    result.append({"username": username, "password": password})

            if source_file == self.legacy_accounts_file and result:
                self._save_accounts()

            return result
        except Exception as e:
            logger.error(f"加载已保存账号失败: {e}")
            return []

    def _save_accounts(self) -> None:
        try:
            payload = {"accounts": self.saved_accounts}
            self.accounts_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"保存账号失败: {e}")

    def _load_analysis_store(self) -> Dict[str, Any]:
        default_store: Dict[str, Any] = {"rooms": {}}
        if not self.analysis_file.exists():
            return default_store

        try:
            raw = json.loads(self.analysis_file.read_text(encoding="utf-8"))
            rooms = raw.get("rooms") if isinstance(raw, dict) else None
            if isinstance(rooms, dict):
                normalized_rooms: Dict[str, Any] = {}
                for room_id, record in rooms.items():
                    if not isinstance(room_id, str):
                        continue
                    normalized_rooms[room_id] = self._normalize_room_record(room_id, record)
                return {"rooms": normalized_rooms}

            if isinstance(raw, dict):
                normalized_rooms = {}
                for room_id, record in raw.items():
                    if not isinstance(room_id, str):
                        continue
                    normalized_rooms[room_id] = self._normalize_room_record(room_id, record)
                return {"rooms": normalized_rooms}

            return default_store
        except Exception as e:
            logger.error(f"加载分析数据失败: {e}")
            return default_store

    def _normalize_room_record(self, room_id: str, record: Any) -> Dict[str, Any]:
        now = _iso_now()
        normalized: Dict[str, Any] = {
            "room_id": room_id,
            "created_at": now,
            "history": [],
        }

        if isinstance(record, dict):
            normalized["created_at"] = str(record.get("created_at") or record.get("added_at") or now)
            history = record.get("history", [])
            if isinstance(history, list):
                for item in history:
                    if not isinstance(item, dict):
                        continue
                    date = str(item.get("date", "")).strip()
                    if not date:
                        continue
                    entry: Dict[str, Any] = {
                        "date": date,
                        "power": _safe_float(item.get("power")),
                        "queried_at": str(item.get("queried_at") or item.get("updated_at") or ""),
                        "status": str(item.get("status") or "ok"),
                    }
                    if item.get("error") is not None:
                        entry["error"] = str(item.get("error"))
                    normalized["history"].append(entry)

        normalized["history"].sort(key=lambda x: str(x.get("date", "")))
        return normalized

    def _save_analysis_store(self) -> None:
        try:
            self.plugin_data_dir.mkdir(parents=True, exist_ok=True)
            tmp_file = self.analysis_file.with_suffix(".tmp")
            tmp_file.write_text(json.dumps(self.analysis_store, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_file.replace(self.analysis_file)
        except Exception as e:
            logger.error(f"保存分析数据失败: {e}")

    def _get_room_record(self, room_id: str) -> Optional[Dict[str, Any]]:
        rooms = self.analysis_store.setdefault("rooms", {})
        record = rooms.get(room_id)
        if isinstance(record, dict):
            record.setdefault("room_id", room_id)
            record.setdefault("created_at", _iso_now())
            record.setdefault("history", [])
            return record
        return None

    def _is_room_tracked(self, room_id: str) -> bool:
        return self._get_room_record(room_id) is not None

    def _track_room(self, room_id: str) -> Tuple[bool, str]:
        room_id = room_id.strip()
        if not room_id.isdigit() or len(room_id) < 3:
            return False, "房间号格式错误，应为至少3位数字，例如 12301"

        rooms = self.analysis_store.setdefault("rooms", {})
        if room_id in rooms:
            return False, f"房间 {room_id} 已经添加过了"

        rooms[room_id] = {
            "room_id": room_id,
            "created_at": _iso_now(),
            "history": [],
        }
        self._save_analysis_store()
        return True, f"已添加房间 {room_id}，之后每天晚上 22:00 会自动记录一次电量"

    def _upsert_room_history(
        self,
        room_id: str,
        power: Optional[float],
        queried_at: Optional[datetime] = None,
        status: str = "ok",
        error: Optional[str] = None,
    ) -> None:
        record = self._get_room_record(room_id)
        if record is None:
            return

        queried_at = queried_at or datetime.now()
        entry: Dict[str, Any] = {
            "date": _date_key(queried_at),
            "power": power,
            "queried_at": queried_at.isoformat(timespec="seconds"),
            "status": status,
        }
        if error:
            entry["error"] = error

        history = record.setdefault("history", [])
        for idx, item in enumerate(history):
            if str(item.get("date", "")) == entry["date"]:
                history[idx] = entry
                break
        else:
            history.append(entry)

        history.sort(key=lambda x: str(x.get("date", "")))
        self._save_analysis_store()

    def _get_room_history(self, room_id: str) -> List[Dict[str, Any]]:
        record = self._get_room_record(room_id)
        if not record:
            return []
        history = record.get("history", [])
        if not isinstance(history, list):
            return []
        result: List[Dict[str, Any]] = []
        for item in history:
            if isinstance(item, dict):
                result.append(item)
        return result

    def _get_valid_history(self, room_id: str) -> List[Dict[str, Any]]:
        history = self._get_room_history(room_id)
        result: List[Dict[str, Any]] = []
        for item in history:
            power = _safe_float(item.get("power"))
            if power is None:
                continue
            result.append({
                "date": str(item.get("date", "")),
                "power": power,
                "queried_at": str(item.get("queried_at", "")),
                "status": str(item.get("status", "ok")),
            })
        result.sort(key=lambda x: x["date"])
        return result

    def _build_recent_series(self, room_id: str, limit: int = 7) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], List[Optional[float]]]:
        valid_history = self._get_valid_history(room_id)
        if not valid_history:
            return [], None, []

        cutoff_date = (datetime.now().date() - timedelta(days=limit - 1))

        def _parse_history_date(item: Dict[str, Any]) -> Optional[datetime.date]:
            try:
                return datetime.strptime(str(item.get("date", "")), "%Y-%m-%d").date()
            except Exception:
                return None

        recent = [item for item in valid_history if (_parse_history_date(item) is not None and _parse_history_date(item) >= cutoff_date)]
        previous = None
        if recent:
            first_recent_date = _parse_history_date(recent[0])
            for candidate in reversed(valid_history):
                candidate_date = _parse_history_date(candidate)
                if candidate_date is not None and first_recent_date is not None and candidate_date < first_recent_date:
                    previous = candidate
                    break

        consumptions: List[Optional[float]] = []
        for idx, item in enumerate(recent):
            current_power = _safe_float(item.get("power"))
            if idx == 0:
                if previous is None:
                    consumptions.append(None)
                else:
                    previous_power = _safe_float(previous.get("power"))
                    consumptions.append(previous_power - current_power if previous_power is not None and current_power is not None else None)
            else:
                prev_power = _safe_float(recent[idx - 1].get("power"))
                consumptions.append(prev_power - current_power if prev_power is not None and current_power is not None else None)

        return recent, previous, consumptions

    def _build_analysis_summary(self, room_id: str) -> Tuple[Optional[str], Optional[str]]:
        if not self._is_room_tracked(room_id):
            return None, f"该房间还没有被添加，请先使用 `/c analyze add {room_id}`"

        recent, previous, consumptions = self._build_recent_series(room_id)
        if not recent:
            return None, f"房间 {room_id} 已添加，但还没有历史数据"

        powers = [item["power"] for item in recent]
        latest_power = powers[-1]
        first_power = powers[0]
        net_change = latest_power - first_power
        net_consumed = first_power - latest_power
        valid_consumptions = [value for value in consumptions if value is not None]
        avg_consumption = sum(valid_consumptions) / len(valid_consumptions) if valid_consumptions else None
        max_consumption = max(valid_consumptions) if valid_consumptions else None
        min_power = min(powers)
        max_power = max(powers)

        trend = "基本持平"
        if latest_power < first_power:
            trend = "整体下降"
        elif latest_power > first_power:
            trend = "整体回升"

        lines = [
            f"房间 {room_id} 近 {len(recent)} 天电量分析：",
            f"- 最新剩余电量：{latest_power:.2f} 度",
            f"- 近段区间净变化：{net_change:+.2f} 度（净消耗 {net_consumed:.2f} 度）",
            f"- 最高剩余电量：{max_power:.2f} 度",
            f"- 最低剩余电量：{min_power:.2f} 度",
            f"- 趋势判断：{trend}",
        ]

        if avg_consumption is not None:
            lines.append(f"- 日均消耗：{avg_consumption:.2f} 度")
        if max_consumption is not None:
            lines.append(f"- 单日最大消耗：{max_consumption:.2f} 度")
        if any(value is not None and value < 0 for value in consumptions):
            lines.append("- 注意：出现剩余电量回升，可能是充值或数据波动")
        if latest_power <= 20:
            lines.append("- 提醒：剩余电量较低，建议尽快关注")
        if previous is None:
            lines.append("- 说明：当前历史记录不足以计算完整的首日消耗，后续数据会自动补齐")

        return "\n".join(lines), None

    def _build_analysis_chart(self, room_id: str) -> Tuple[Optional[Path], Optional[str]]:
        recent, previous, consumptions = self._build_recent_series(room_id)
        if not recent:
            return None, f"房间 {room_id} 暂无可用于绘图的历史数据"

        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except Exception as e:
            return None, f"绘图依赖不可用：{e}"

        dates = [item["date"] for item in recent]
        powers = [item["power"] for item in recent]
        consumption_x = dates
        consumption_y = consumptions

        try:
            plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 9), constrained_layout=True)

            ax1.plot(dates, powers, marker="o", linewidth=2, color="#2F6FED")
            ax1.set_title(f"房间 {room_id} 近七天剩余电量")
            ax1.set_ylabel("剩余电量（度）")
            ax1.grid(True, linestyle="--", alpha=0.35)

            if any(value is not None for value in consumption_y):
                ax2.plot(consumption_x, consumption_y, marker="o", linewidth=2, color="#E67E22")
                ax2.axhline(0, color="#666666", linewidth=1, linestyle="--", alpha=0.6)
                ax2.set_title("近七天每天消耗电量")
                ax2.set_ylabel("消耗电量（度）")
                ax2.grid(True, linestyle="--", alpha=0.35)
            else:
                ax2.text(0.5, 0.5, "暂无足够数据绘制消耗曲线", ha="center", va="center", fontsize=13)
                ax2.set_axis_off()

            for ax in (ax1, ax2):
                if ax.get_visible():
                    ax.tick_params(axis="x", rotation=30)

            fig.suptitle(f"房间 {room_id} 电量分析", fontsize=16)
            chart_path = self.plugin_data_dir / f"analysis_{room_id}.png"
            fig.savefig(chart_path, dpi=200)
            plt.close(fig)
            return chart_path, None
        except Exception as e:
            logger.error(f"生成分析图失败: {e}")
            return None, f"生成分析图失败：{e}"

    async def _run_nightly_analysis(self) -> None:
        rooms = list(self.analysis_store.get("rooms", {}).keys())
        if not rooms:
            logger.info("当前没有已添加的分析房间，跳过夜间任务")
            return

        logger.info(f"开始夜间电量采集，共 {len(rooms)} 个房间")
        for room_id in rooms:
            power, err_msg = await self._query_with_retry(room_id)
            if power is not None:
                self._upsert_room_history(room_id, power, datetime.now(), status="ok")
                logger.info(f"夜间采集成功：{room_id} => {power}")
            else:
                self._upsert_room_history(room_id, None, datetime.now(), status="failed", error=err_msg)
                logger.warning(f"夜间采集失败：{room_id}，{err_msg}")

    async def _collect_all_tracked_rooms(self) -> Tuple[int, int, List[str]]:
        rooms = list(self.analysis_store.get("rooms", {}).keys())
        if not rooms:
            return 0, 0, ["当前没有已添加的分析房间，请先使用 `/c analyze add <房间号>` 添加"]

        success_count = 0
        failed_count = 0
        lines = [f"开始立即采集 {len(rooms)} 个房间的电量数据："]
        for room_id in rooms:
            power, err_msg = await self._query_with_retry(room_id)
            if power is not None:
                self._upsert_room_history(room_id, power, datetime.now(), status="ok")
                success_count += 1
                lines.append(f"- {room_id}：{power:.2f} 度")
            else:
                self._upsert_room_history(room_id, None, datetime.now(), status="failed", error=err_msg)
                failed_count += 1
                lines.append(f"- {room_id}：采集失败（{err_msg}）")

        lines.append(f"采集完成：成功 {success_count} 个，失败 {failed_count} 个")
        return success_count, failed_count, lines

    async def _nightly_loop(self) -> None:
        while True:
            try:
                now = datetime.now()
                target = now.replace(hour=22, minute=0, second=0, microsecond=0)
                if now >= target:
                    target += timedelta(days=1)

                await asyncio.sleep(max((target - now).total_seconds(), 1.0))
                await self._run_nightly_analysis()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"夜间任务异常: {e}")
                await asyncio.sleep(60)

    def _upsert_account(self, username: str, password: str) -> None:
        username = username.strip()
        if not username:
            return

        for account in self.saved_accounts:
            if account.get("username") == username:
                account["password"] = password
                self._save_accounts()
                return

        self.saved_accounts.append(_normalize_account(username, password))
        self._save_accounts()

    def _list_accounts(self) -> str:
        if not self.saved_accounts:
            return "当前没有已保存的账号"

        lines = ["已保存账号列表："]
        for index, account in enumerate(self.saved_accounts, start=1):
            lines.append(f"{index}. {account.get('username', '')}")
        return "\n".join(lines)

    def _remove_account(self, identifier: str) -> Tuple[bool, str]:
        identifier = identifier.strip()
        if not identifier:
            return False, "请输入要删除的账号名或序号"

        target_index: Optional[int] = None
        if identifier.isdigit():
            index = int(identifier)
            if 1 <= index <= len(self.saved_accounts):
                target_index = index - 1
        else:
            for idx, account in enumerate(self.saved_accounts):
                if account.get("username") == identifier:
                    target_index = idx
                    break

        if target_index is None:
            return False, f"未找到账号：{identifier}"

        removed = self.saved_accounts.pop(target_index)
        self._save_accounts()

        if self.global_cred and self.global_cred.get("username") == removed.get("username"):
            self.global_cred = None

        return True, f"已删除账号：{removed.get('username', '')}"

    def _clear_accounts(self) -> Tuple[bool, str]:
        if not self.saved_accounts:
            return True, "当前没有已保存的账号"

        count = len(self.saved_accounts)
        self.saved_accounts.clear()
        self._save_accounts()
        self.global_cred = None
        return True, f"已清空 {count} 个已保存账号"

    def _get_random_saved_account(self) -> Optional[Dict[str, str]]:
        if not self.saved_accounts:
            return None
        return random.choice(self.saved_accounts)

    async def initialize(self):
        logger.info("电费查询插件已加载")
        logger.info(f"已加载 {len(self.saved_accounts)} 个保存的账号")
        logger.info(f"已加载 {len(self.analysis_store.get('rooms', {}))} 个分析房间")
        if self.scheduler_task is None or self.scheduler_task.done():
            self.scheduler_task = asyncio.create_task(self._nightly_loop())

    async def terminate(self):
        if self.scheduler_task and not self.scheduler_task.done():
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                pass
        await self.client.aclose()

    async def _re_login(self) -> Optional[str]:
        account = self._get_random_saved_account()
        if not account:
            logger.warning("未保存任何登录凭据，无法重登")
            return None

        username = account["username"]
        password = account["password"]
        logger.info(f"尝试使用随机账号 {username} 自动登录")
        token = await ChargeAPI.login(username, password, self.client)
        if token:
            self.global_cred = {"username": username, "password": password, "token": token}
            logger.info("重登成功")
            return token
        else:
            logger.error("自动登录失败")
            return None

    async def _query_with_retry(self, room_id: str) -> Tuple[Optional[float], str]:
        if not self.global_cred or not self.global_cred.get("token"):
            new_token = await self._re_login()
            if not new_token:
                return None, "请先使用 `/c login <账号> <密码>` 登录"
            self.global_cred["token"] = new_token

        token = self.global_cred["token"]
        power = await ChargeAPI.query_charge(room_id, token, self.client)
        if power is not None:
            return power, ""

        logger.info("查询失败，尝试重新登录")
        new_token = await self._re_login()
        if not new_token:
            return None, "登录凭据无效或网络错误，请重新使用 `/c login` 设置账号密码"

        power = await ChargeAPI.query_charge(room_id, new_token, self.client)
        if power is not None:
            return power, ""
        else:
            return None, "查询失败，请检查房间号是否正确或稍后再试"

    def _help_text(self) -> str:
        return (
            "用法:\n"
            "/c login <账号> <密码>        - 保存账号密码并登录\n"
            "/c help                     - 显示帮助\n"
            "/c account list              - 查看已保存账号\n"
            "/c account remove <账号|序号> - 删除已保存账号\n"
            "/c account clear             - 清空所有已保存账号\n"
            "/c analyze add <房间号>      - 添加分析房间并开启每日 22:00 采集\n"
            "/c analyze all               - 立即采集所有已添加房间\n"
            "/c analyze <房间号>          - 查看近七天分析图表\n"
            "/c <房间号>                  - 查询电费"
        )

    async def _handle_analyze_command(self, event: AstrMessageEvent, parts: List[str]):
        if len(parts) < 3:
            yield event.plain_result("用法:\n/c analyze add <房间号>  - 添加分析房间\n/c analyze all            - 立即采集所有已添加房间\n/c analyze <房间号>      - 查看近七天分析图表")
            return

        action = parts[2]
        if action == "add":
            if len(parts) < 4:
                yield event.plain_result("用法: /c analyze add <房间号>")
                return
            success, msg = self._track_room(parts[3])
            yield event.plain_result(msg)
            return

        if action == "all":
            _, _, lines = await self._collect_all_tracked_rooms()
            yield event.plain_result("\n".join(lines))
            return

        room_id = action
        if not room_id.isdigit() or len(room_id) < 3:
            yield event.plain_result("房间号格式错误，应为至少3位数字，例如 12301")
            return

        if not self._is_room_tracked(room_id):
            yield event.plain_result(f"该房间还没有被添加，请先使用 `/c analyze add {room_id}`")
            return

        summary, summary_error = self._build_analysis_summary(room_id)
        chart_path, chart_error = self._build_analysis_chart(room_id)

        if summary:
            yield event.plain_result(summary)
        elif summary_error:
            yield event.plain_result(summary_error)

        if chart_path and chart_path.exists():
            yield event.image_result(str(chart_path))
        elif chart_error:
            yield event.plain_result(chart_error)

    @filter.command("c")
    async def handle_charge_command(self, event: AstrMessageEvent):
        message = event.message_str.strip()
        parts = message.split()
        if len(parts) < 2:
            yield event.plain_result(self._help_text())
            return

        sub_cmd = parts[1]

        if sub_cmd == "help":
            yield event.plain_result(self._help_text())
            return

        if sub_cmd == "analyze":
            async for result in self._handle_analyze_command(event, parts):
                yield result
            return

        if sub_cmd == "login":
            if len(parts) < 4:
                yield event.plain_result("用法: /c login <账号> <密码>")
                return
            username = parts[2]
            password = parts[3]
            token = await ChargeAPI.login(username, password, self.client)
            if token:
                self._upsert_account(username, password)
                self.global_cred = {
                    "username": username,
                    "password": password,
                    "token": token
                }
                yield event.plain_result(f"登录成功，账号 {username} 已保存")
            else:
                yield event.plain_result("登录失败，请检查账号密码或网络")
            return

        if sub_cmd == "account":
            if len(parts) < 3:
                yield event.plain_result("用法:\n/c account list\n/c account remove <账号|序号>\n/c account clear")
                return

            action = parts[2]
            if action == "list":
                yield event.plain_result(self._list_accounts())
                return

            if action == "remove":
                if len(parts) < 4:
                    yield event.plain_result("用法: /c account remove <账号|序号>")
                    return
                success, msg = self._remove_account(parts[3])
                yield event.plain_result(msg)
                return

            if action == "clear":
                success, msg = self._clear_accounts()
                yield event.plain_result(msg)
                return

            yield event.plain_result("用法:\n/c account list\n/c account remove <账号|序号>\n/c account clear")
            return

        room_id = sub_cmd
        if not room_id.isdigit() or len(room_id) < 3:
            yield event.plain_result("房间号格式错误，应为至少3位数字，例如 12301")
            return

        power, err_msg = await self._query_with_retry(room_id)
        if power is not None:
            yield event.plain_result(f"房间 {room_id} 当前剩余电量: {power} 度")
        else:
            yield event.plain_result(err_msg)