from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import httpx
import json
from typing import Dict, Optional, Tuple

def num_to_chinese(num_str: str) -> str:
    mapping = {
        '0': '零', '1': '一', '2': '二', '3': '三', '4': '四',
        '5': '五', '6': '六', '7': '七', '8': '八', '9': '九'
    }
    return mapping.get(num_str, num_str)

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
            client.headers.update(headers)

            if len(build_room_id) < 3:
                logger.error(f"房间号 {build_room_id} 格式错误，至少需要3位")
                return None
            build_id = build_room_id[:-3]
            floor_id = build_room_id[-3]
            room_id = build_room_id[-2:]

            form = {"feeitemid": "411", "type": "select", "level": "0"}
            resp = await client.post(ChargeAPI.QUERY_URL, data=form)
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
            resp = await client.post(ChargeAPI.QUERY_URL, data=form)
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
            resp = await client.post(ChargeAPI.QUERY_URL, data=form)
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
            resp = await client.post(ChargeAPI.QUERY_URL, data=form)
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
        finally:
            if "synjones-auth" in client.headers:
                del client.headers["synjones-auth"]

@register("charge_query", "YourName", "电费查询插件，支持自动登录重试", "1.0.0")
class ChargePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.global_cred: Optional[Dict] = None
        self.client = httpx.AsyncClient(timeout=30.0)

    async def initialize(self):
        logger.info("电费查询插件已加载")

    async def terminate(self):
        await self.client.aclose()

    async def _re_login(self) -> Optional[str]:
        if not self.global_cred or not self.global_cred.get("username") or not self.global_cred.get("password"):
            logger.warning("未设置登录凭据，无法重登")
            return None
        token = await ChargeAPI.login(self.global_cred["username"], self.global_cred["password"], self.client)
        if token:
            self.global_cred["token"] = token
            logger.info("重登成功")
            return token
        else:
            logger.error("重登失败")
            return None

    async def _query_with_retry(self, room_id: str) -> Tuple[Optional[float], str]:
        if not self.global_cred or not self.global_cred.get("token"):
            return None, "请先使用 `/c login 账号 密码` 登录"

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

    @filter.command("c")
    async def handle_charge_command(self, event: AstrMessageEvent):
        message = event.message_str.strip()
        parts = message.split()
        if len(parts) < 2:
            yield event.plain_result("用法:\n/c login <账号> <密码>   - 设置默认账号密码\n/c <房间号>        - 查询电费")
            return

        sub_cmd = parts[1]

        if sub_cmd == "login":
            if len(parts) < 4:
                yield event.plain_result("用法: /c login <账号> <密码>")
                return
            username = parts[2]
            password = parts[3]
            token = await ChargeAPI.login(username, password, self.client)
            if token:
                self.global_cred = {
                    "username": username,
                    "password": password,
                    "token": token
                }
                yield event.plain_result(f"登录成功，账号 {username} 已保存")
            else:
                yield event.plain_result("登录失败，请检查账号密码或网络")
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