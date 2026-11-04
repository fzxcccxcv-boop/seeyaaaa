import os
import re
import ast
import sys
import json
import time
import shutil
import threading
import subprocess
import importlib.util
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List, Set

import psutil
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ============================================================================
# 🌸 WINDOWS RDP UTF-8 CONSOLE & SUBPROCESS COMPATIBILITY PATCH
# ============================================================================
IS_WINDOWS = os.name == "nt"
if IS_WINDOWS:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ============================================================================
# 🌸 PATHS & AUTOMATIC JSON FILE GENERATOR
# ============================================================================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
SESSIONS_FILE = os.path.join(BASE_DIR, "sessions.json")
PACKAGES_MAP_FILE = os.path.join(BASE_DIR, "packages_map.json")
WORKSPACES_DIR = os.path.join(BASE_DIR, "workspaces")
PAYLOAD_DIR = os.path.join(BASE_DIR, "engine_payload")
DEFAULT_MASTER_SCRIPT = os.path.join(PAYLOAD_DIR, "master_script.py")

os.makedirs(WORKSPACES_DIR, exist_ok=True)
os.makedirs(PAYLOAD_DIR, exist_ok=True)

DEFAULT_CONFIG_JSON = {
    "master_bot_token": os.environ.get("MASTER_BOT_TOKEN", "YOUR_HOSTER_BOT_TOKEN_HERE"),
    "super_owner_id": int(os.environ.get("SUPER_OWNER_ID", "123456789")),
    "bot_brand": "sidbotxhoster",
    "master_owner_tag": "@s1dfr",
    "max_bots_per_user": 10,
    "max_ram_mb_per_bot": 150,
    "max_cpu_percent_per_bot": 85.0,
    "max_log_bytes": 2097152,
    "colored_buttons_enabled": True,
    "button_styles": {
        "action_main": "primary",
        "action_positive": "success",
        "action_destructive": "danger",
    },
}

DEFAULT_PACKAGES_MAP_JSON = {
    "telebot": "pyTelegramBotAPI",
    "telegram": "python-telegram-bot",
    "pyrogram": "pyrogram",
    "telethon": "Telethon",
    "aiogram": "aiogram",
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "bs4": "beautifulsoup4",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
    "dotenv": "python-dotenv",
    "Crypto": "pycryptodome",
    "fitz": "PyMuPDF",
    "dateutil": "python-dateutil",
    "dns": "dnspython",
    "serial": "pyserial",
    "jwt": "PyJWT",
    "websocket": "websocket-client",
    "nacl": "PyNaCl",
    "git": "GitPython",
}


def ensure_static_json_files() -> Tuple[Dict[str, Any], Dict[str, str]]:
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG_JSON, f, indent=2, ensure_ascii=False)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = DEFAULT_CONFIG_JSON.copy()

    if not os.path.exists(PACKAGES_MAP_FILE):
        with open(PACKAGES_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_PACKAGES_MAP_JSON, f, indent=2, ensure_ascii=False)
    try:
        with open(PACKAGES_MAP_FILE, "r", encoding="utf-8") as f:
            pkg_map = json.load(f)
    except Exception:
        pkg_map = DEFAULT_PACKAGES_MAP_JSON.copy()

    return cfg, pkg_map


CONFIG_DATA, IMPORT_TO_PYPI_MAP = ensure_static_json_files()

MASTER_BOT_TOKEN = os.environ.get("MASTER_BOT_TOKEN") or CONFIG_DATA.get("master_bot_token", "YOUR_HOSTER_BOT_TOKEN_HERE")
SUPER_OWNER_ID = int(os.environ.get("SUPER_OWNER_ID") or CONFIG_DATA.get("super_owner_id", 123456789))
BOT_BRAND = CONFIG_DATA.get("bot_brand", "sidbotxhoster")
MASTER_OWNER_TAG = CONFIG_DATA.get("master_owner_tag", "@s1dfr")
MAX_BOTS_PER_USER = int(CONFIG_DATA.get("max_bots_per_user", 10))
MAX_RAM_MB_PER_BOT = int(CONFIG_DATA.get("max_ram_mb_per_bot", 150))
MAX_CPU_PERCENT_PER_BOT = float(CONFIG_DATA.get("max_cpu_percent_per_bot", 85.0))
MAX_LOG_BYTES = int(CONFIG_DATA.get("max_log_bytes", 2 * 1024 * 1024))

HOSTER_BOOT_TIME = time.time()
bot = telebot.TeleBot(MASTER_BOT_TOKEN, parse_mode="HTML", threaded=True, num_threads=12)

USER_STATES: Dict[int, Dict[str, Any]] = {}
ACTIVE_PROCESSES: Dict[str, subprocess.Popen] = {}
PROCESS_LOCK = threading.RLock()


# ============================================================================
# 🌸 WINDOWS RDP SAFE FILE & DIRECTORY HELPERS
# ============================================================================
def windows_safe_replace(src: str, dst: str, retries: int = 5):
    for attempt in range(retries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == retries - 1:
                shutil.copy2(src, dst)
                try:
                    os.remove(src)
                except Exception:
                    pass
            else:
                time.sleep(0.08)


def windows_safe_rmtree(path: str, retries: int = 5):
    if not path or not os.path.exists(path):
        return
    for _ in range(retries):
        try:
            shutil.rmtree(path)
            return
        except Exception:
            time.sleep(0.15)
    shutil.rmtree(path, ignore_errors=True)


# ============================================================================
# 🌸 TELEGRAM BOT API COLORED INLINE BUTTON ENGINE
# ============================================================================
class SakuraButton(InlineKeyboardButton):
    def __init__(
        self,
        text: str,
        style: Optional[str] = None,
        icon_custom_emoji_id: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(text=text, **kwargs)
        self.style = style
        self.icon_custom_emoji_id = icon_custom_emoji_id

    def to_dict(self) -> dict:
        payload = super().to_dict()
        if self.style in ("primary", "success", "danger"):
            payload["style"] = self.style
        if self.icon_custom_emoji_id:
            payload["icon_custom_emoji_id"] = str(self.icon_custom_emoji_id)
        return payload


# ============================================================================
# 🌸 DEFAULT MASTER SCRIPT GENERATOR (HOSTED ON USER BOTS)
# ============================================================================
def ensure_default_master_script():
    if os.path.exists(DEFAULT_MASTER_SCRIPT):
        return
    default_code = f'''import os
import sys
import time
import platform
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Auto-injected by {BOT_BRAND}
BOT_TOKEN = os.environ.get("BOT_TOKEN", "__BOT_TOKEN__")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
HOSTER_NAME = os.environ.get("HOSTER_NAME", "{BOT_BRAND}")
MASTER_OWNER = os.environ.get("MASTER_OWNER", "{MASTER_OWNER_TAG}")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
START_TIME = time.time()

class ColoredButton(InlineKeyboardButton):
    def __init__(self, text: str, style: str = None, **kwargs):
        super().__init__(text=text, **kwargs)
        self.style = style
    def to_dict(self) -> dict:
        d = super().to_dict()
        if self.style in ("primary", "success", "danger"):
            d["style"] = self.style
        return d

def get_uptime() -> str:
    s = int(time.time() - START_TIME)
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{{h}}h {{m}}m {{sec}}s"

def is_owner(uid: int) -> bool:
    return int(uid) == int(OWNER_ID)

def main_kb(uid: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        ColoredButton("🌸 Ping", callback_data="ping", style="success"),
        ColoredButton("💮 Bot Status", callback_data="info", style="primary"),
        ColoredButton("📊 System Stats", callback_data="stats", style="primary"),
        ColoredButton("ℹ️ Help & About", callback_data="help", style="primary"),
    )
    if is_owner(uid):
        kb.add(ColoredButton("👑 Script Owner Panel", callback_data="owner_panel", style="danger"))
    return kb

@bot.message_handler(commands=["start", "help"])
def start_cmd(message):
    uid = message.from_user.id
    role = "👑 <b>Bot Owner</b>" if is_owner(uid) else "🌷 <b>User</b>"
    text = (
        f"╭─── 🌸 <b>Hosted by {{HOSTER_NAME}}</b> 🌸 ───╮\\n"
        f"│ 👤 <b>Welcome,</b> {{message.from_user.first_name}}!\\n"
        f"│ 🆔 <b>Your ID:</b> <code>{{uid}}</code>\\n"
        f"│ 👑 <b>Owner ID:</b> <code>{{OWNER_ID}}</code>\\n"
        f"│ 🎖️ <b>Role:</b> {{role}}\\n"
        f"│ ⛩️ <b>Hoster:</b> {{MASTER_OWNER}}\\n"
        f"╰──────────────────────────────╯"
    )
    bot.send_message(message.chat.id, text, reply_markup=main_kb(uid))

@bot.message_handler(commands=["owner", "admin", "panel"])
def owner_cmd(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, f"🥀 <b>Access Denied!</b> Only Owner (<code>{{OWNER_ID}}</code>) can execute this.")
        return
    bot.reply_to(
        message,
        f"🌸 <b>Owner Session Active</b>\\n"
        f"• <b>Owner ID:</b> <code>{{OWNER_ID}}</code>\\n"
        f"• <b>Uptime:</b> <code>{{get_uptime()}}</code>\\n"
        f"• <b>Powered By:</b> <code>{{HOSTER_NAME}}</code> ({{MASTER_OWNER}})"
    )

@bot.callback_query_handler(func=lambda c: True)
def cb_handler(call):
    uid = call.from_user.id
    if call.data == "ping":
        bot.answer_callback_query(call.id, f"🌸 Pong! Uptime: {{get_uptime()}}", show_alert=True)
    elif call.data == "info":
        me = bot.get_me()
        bot.answer_callback_query(
            call.id,
            f"🤖 @{{me.username}} | Owner: {{OWNER_ID}} | Hosted by {{HOSTER_NAME}} ({{MASTER_OWNER}})",
            show_alert=True,
        )
    elif call.data == "stats":
        bot.answer_callback_query(
            call.id,
            f"📊 Python: {{platform.python_version()}} | Uptime: {{get_uptime()}} | PID: {{os.getpid()}}",
            show_alert=True,
        )
    elif call.data == "help":
        bot.answer_callback_query(
            call.id,
            f"ℹ️ This is a hosted bot running on {{HOSTER_NAME}} cloud engine.\\n"
            f"Owner: {{OWNER_ID}} | Master: {{MASTER_OWNER}}",
            show_alert=True,
        )
    elif call.data == "owner_panel":
        if not is_owner(uid):
            bot.answer_callback_query(call.id, "🥀 Owner Only!", show_alert=True)
            return
        bot.answer_callback_query(
            call.id,
            f"👑 Full Owner Control Verified! PID: {{os.getpid()}} | Python {{platform.python_version()}}",
            show_alert=True,
        )

if __name__ == "__main__":
    print(f"[🌸 Hosted Bot Online] Polling started for Owner ID {{OWNER_ID}}...")
    bot.infinity_polling(timeout=20, long_polling_timeout=10, skip_pending=True)
'''
    with open(DEFAULT_MASTER_SCRIPT, "w", encoding="utf-8") as f:
        f.write(default_code)


# ============================================================================
# 🌸 ATOMIC JSON SESSION & PERFORMANCE DATABASE
# ============================================================================
class SakuraSessionManager:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.lock = threading.RLock()
        self._ensure_initialized()

    def _ensure_initialized(self):
        with self.lock:
            if not os.path.exists(self.filepath):
                default_data = {
                    "system": {
                        "bot_name": BOT_BRAND,
                        "master_owner": MASTER_OWNER_TAG,
                        "theme": "sakura",
                        "hosting_enabled": True,
                        "auto_restart": True,
                        "auto_pip_install": True,
                        "auto_brand_bots": True,
                        "colored_buttons": True,
                        "max_bots_per_user": MAX_BOTS_PER_USER,
                        "max_ram_mb_per_bot": MAX_RAM_MB_PER_BOT,
                        "max_cpu_percent_per_bot": MAX_CPU_PERCENT_PER_BOT,
                        "oom_kills_count": 0,
                        "master_script_path": DEFAULT_MASTER_SCRIPT,
                        "total_deployments": 0,
                        "last_updated": datetime.now().isoformat(),
                    },
                    "users": {},
                }
                self._write_atomic(default_data)

    def _write_atomic(self, data: Dict[str, Any]):
        data["system"]["last_updated"] = datetime.now().isoformat()
        temp_file = f"{self.filepath}.tmp"
        backup_file = f"{self.filepath}.bak"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        if os.path.exists(self.filepath):
            try:
                shutil.copy2(self.filepath, backup_file)
            except Exception:
                pass
        windows_safe_replace(temp_file, self.filepath)

    def _sync_user_workspace_json(self, user_obj: Dict[str, Any]):
        try:
            sdir = user_obj.get("session_dir")
            if sdir:
                os.makedirs(sdir, exist_ok=True)
                ujson_path = os.path.join(sdir, "user_session.json")
                with open(ujson_path, "w", encoding="utf-8") as f:
                    json.dump(user_obj, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def load(self) -> Dict[str, Any]:
        with self.lock:
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sys_cfg = data.setdefault("system", {})
                sys_cfg.setdefault("auto_pip_install", True)
                sys_cfg.setdefault("auto_brand_bots", True)
                sys_cfg.setdefault("colored_buttons", True)
                sys_cfg.setdefault("master_owner", MASTER_OWNER_TAG)
                sys_cfg.setdefault("max_bots_per_user", MAX_BOTS_PER_USER)
                sys_cfg.setdefault("max_ram_mb_per_bot", MAX_RAM_MB_PER_BOT)
                sys_cfg.setdefault("max_cpu_percent_per_bot", MAX_CPU_PERCENT_PER_BOT)
                sys_cfg.setdefault("oom_kills_count", 0)
                sys_cfg.setdefault("total_deployments", 0)
                return data
            except Exception:
                backup_file = f"{self.filepath}.bak"
                if os.path.exists(backup_file):
                    try:
                        with open(backup_file, "r", encoding="utf-8") as f:
                            return json.load(f)
                    except Exception:
                        pass
                self._ensure_initialized()
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)

    def save(self, data: Dict[str, Any]):
        with self.lock:
            self._write_atomic(data)

    def register_user(self, user: telebot.types.User) -> Dict[str, Any]:
        with self.lock:
            data = self.load()
            uid = str(user.id)
            username = f"@{user.username}" if user.username else "NoUsername"
            full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "User"

            user_workspace = os.path.join(WORKSPACES_DIR, f"user_{uid}")
            os.makedirs(user_workspace, exist_ok=True)

            if uid not in data["users"]:
                data["users"][uid] = {
                    "user_id": int(uid),
                    "username": username,
                    "full_name": full_name,
                    "default_owner_chat_id": int(uid),
                    "session_dir": user_workspace,
                    "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "bots": {},
                }
            else:
                data["users"][uid]["username"] = username
                data["users"][uid]["full_name"] = full_name
                data["users"][uid]["session_dir"] = user_workspace

            self.save(data)
            self._sync_user_workspace_json(data["users"][uid])
            return data["users"][uid]

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self.load()["users"].get(str(user_id))

    def get_system_config(self) -> Dict[str, Any]:
        return self.load()["system"]

    def update_system_config(self, **kwargs):
        with self.lock:
            data = self.load()
            for k, v in kwargs.items():
                data["system"][k] = v
            self.save(data)

    def increment_deployments(self):
        with self.lock:
            data = self.load()
            data["system"]["total_deployments"] = data["system"].get("total_deployments", 0) + 1
            self.save(data)

    def add_or_update_bot(self, user_id: int, bot_id: str, bot_meta: Dict[str, Any]):
        with self.lock:
            data = self.load()
            uid = str(user_id)
            if uid in data["users"]:
                data["users"][uid]["bots"][str(bot_id)] = bot_meta
                self.save(data)
                self._sync_user_workspace_json(data["users"][uid])

    def remove_bot(self, user_id: int, bot_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            data = self.load()
            uid = str(user_id)
            if uid in data["users"] and str(bot_id) in data["users"][uid]["bots"]:
                removed = data["users"][uid]["bots"].pop(str(bot_id))
                self.save(data)
                self._sync_user_workspace_json(data["users"][uid])
                return removed
            return None

    def delete_entire_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self.lock:
            data = self.load()
            uid = str(user_id)
            if uid in data["users"]:
                removed_user = data["users"].pop(uid)
                self.save(data)
                return removed_user
            return None


ensure_default_master_script()
db = SakuraSessionManager(SESSIONS_FILE)


# ============================================================================
# 🌸 AST PACKAGE SCANNER, AUTO-PIP & MINI TERMINAL ENGINE
# ============================================================================
def get_stdlib_modules() -> Set[str]:
    stdlib = set(sys.builtin_module_names)
    if hasattr(sys, "stdlib_module_names"):
        stdlib.update(sys.stdlib_module_names)
    stdlib.update({
        "os", "sys", "re", "json", "time", "datetime", "math", "random",
        "threading", "subprocess", "shutil", "pathlib", "typing", "collections",
        "itertools", "functools", "asyncio", "logging", "sqlite3", "hashlib",
        "base64", "urllib", "http", "socket", "ssl", "csv", "io", "copy",
        "traceback", "platform", "signal", "uuid", "tempfile", "zipfile",
        "tarfile", "gzip", "pickle", "struct", "ctypes", "enum", "dataclasses",
        "abc", "contextlib", "inspect", "importlib", "ast", "queue", "string",
        "winreg", "msvcrt", "winsound", "ntpath", "__future__"
    })
    return stdlib


def scan_missing_packages_from_code(py_code: str) -> List[str]:
    imported_roots: Set[str] = set()
    try:
        tree = ast.parse(py_code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_pkg = alias.name.split(".")[0].strip()
                    if root_pkg:
                        imported_roots.add(root_pkg)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:
                    root_pkg = node.module.split(".")[0].strip()
                    if root_pkg:
                        imported_roots.add(root_pkg)
    except Exception:
        for match in re.finditer(r"^\s*(?:import|from)\s+([a-zA-Z0-9_]+)", py_code, re.MULTILINE):
            imported_roots.add(match.group(1))

    stdlib = get_stdlib_modules()
    missing_pypi_packages: List[str] = []

    for mod in sorted(imported_roots):
        if mod in stdlib or mod.startswith("_"):
            continue
        spec = importlib.util.find_spec(mod)
        if spec is None:
            pypi_name = IMPORT_TO_PYPI_MAP.get(mod, mod)
            if pypi_name not in missing_pypi_packages:
                missing_pypi_packages.append(pypi_name)

    return missing_pypi_packages


def install_packages_pip(packages: List[str], timeout: int = 180) -> Tuple[bool, str]:
    if not packages:
        return True, "🌸 All required packages are already installed."
    cmd = [sys.executable, "-m", "pip", "install", "--no-cache-dir"] + packages
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creation_flags,
        )
        output = (proc.stdout + "\n" + proc.stderr).strip()
        return proc.returncode == 0, output[-3000:] if output else "Completed."
    except subprocess.TimeoutExpired:
        return False, f"🥀 Pip installation timed out after {timeout}s."
    except Exception as e:
        return False, f"🥀 Pip error: {e}"


def execute_terminal_command(raw_command: str, timeout: int = 120) -> Tuple[int, str]:
    cmd_str = raw_command.strip()
    if cmd_str.startswith("pip "):
        cmd_str = f'"{sys.executable}" -m {cmd_str}'
    elif cmd_str.startswith("python ") or cmd_str.startswith("python3 "):
        parts = cmd_str.split(" ", 1)
        cmd_str = f'"{sys.executable}" {parts[1] if len(parts) > 1 else ""}'

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0
    try:
        proc = subprocess.run(
            cmd_str,
            shell=True,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creation_flags,
        )
        combined = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        combined = combined.strip() or "✅ Command executed successfully (no stdout)."
        return proc.returncode, combined[-3500:]
    except subprocess.TimeoutExpired:
        return 124, f"🥀 Command timed out after {timeout} seconds."
    except Exception as e:
        return 1, f"🥀 Execution Error: {e}"


# ============================================================================
# 🌸 TELEGRAM BOT API AUTO-BRANDING & PRE-FLIGHT ENGINE
# ============================================================================
def validate_and_prepare_bot_token(
    token: str,
    owner_chat_id: int,
    apply_branding: bool = True,
) -> Tuple[bool, Optional[Dict[str, Any]], str, str]:
    token = token.strip()
    if not re.match(r"^\d{6,12}:[A-Za-z0-9_-]{30,50}$", token):
        return False, None, "Invalid token format. Expected `<bot_id>:<hash>`.", ""

    base_url = f"https://api.telegram.org/bot{token}"
    try:
        resp = requests.get(f"{base_url}/getMe", timeout=10)
        if resp.status_code != 200 or not resp.json().get("ok"):
            return False, None, resp.json().get("description", "Unauthorized token."), ""
        bot_info = resp.json()["result"]
    except Exception as e:
        return False, None, f"Telegram API unreachable: {e}", ""

    branding_status = []
    try:
        requests.post(
            f"{base_url}/deleteWebhook",
            json={"drop_pending_updates": True},
            timeout=6,
        )
        branding_status.append("Webhook cleared")
    except Exception:
        pass

    if apply_branding:
        description_text = (
            f"🌸 Hosted by {BOT_BRAND}\n"
            f"👑 Hoster Owner: {MASTER_OWNER_TAG}\n"
            f"🆔 Bot Admin ID: {owner_chat_id}\n"
            f"⚡ Powered by Sakura Real-Time Cloud Engine"
        )
        short_desc_text = f"🌸 Hosted by {BOT_BRAND} | 👑 Owner: {MASTER_OWNER_TAG}"
        try:
            r1 = requests.post(
                f"{base_url}/setMyDescription",
                json={"description": description_text},
                timeout=6,
            )
            r2 = requests.post(
                f"{base_url}/setMyShortDescription",
                json={"short_description": short_desc_text},
                timeout=6,
            )
            if r1.status_code == 200 and r2.status_code == 200:
                branding_status.append(f"Bio & Description branded ({BOT_BRAND} | {MASTER_OWNER_TAG})")
        except Exception:
            pass

    return True, bot_info, "Valid", " • ".join(branding_status)


# ============================================================================
# 🌸 SMART SCRIPT PATCHER & RDP-SAFE ISOLATED PROCESS ENGINE
# ============================================================================
def rotate_log_if_needed(log_path: str):
    try:
        if os.path.exists(log_path) and os.path.getsize(log_path) > MAX_LOG_BYTES:
            with open(log_path, "rb") as f:
                f.seek(-int(MAX_LOG_BYTES // 2), os.SEEK_END)
                tail = f.read()
            with open(log_path, "wb") as f:
                f.write("--- [🌸 Log Auto-Rotated by sidbotxhoster] ---\n".encode("utf-8") + tail)
    except Exception:
        pass


def build_isolated_runner(
    master_script_path: str,
    target_workspace: str,
    bot_token: str,
    owner_chat_id: int,
) -> str:
    os.makedirs(target_workspace, exist_ok=True)
    ensure_default_master_script()

    sys_cfg = db.get_system_config()
    max_ram_mb = int(sys_cfg.get("max_ram_mb_per_bot", MAX_RAM_MB_PER_BOT))

    src_path = master_script_path if os.path.exists(master_script_path) else DEFAULT_MASTER_SCRIPT
    with open(src_path, "r", encoding="utf-8", errors="ignore") as f:
        raw_code = f.read()

    # 1. Extract any `from __future__ import ...` lines so they stay at the very top of runner.py
    future_lines: List[str] = []
    remaining_lines: List[str] = []
    for line in raw_code.splitlines():
        if re.match(r"^\s*from\s+__future__\s+import\s+", line):
            future_lines.append(line)
        else:
            remaining_lines.append(line)
    patched = "\n".join(remaining_lines)

    # 2. Replace standard placeholders
    for placeholder in ("__BOT_TOKEN__", "YOUR_BOT_TOKEN_HERE", "YOUR_BOT_TOKEN", "BOT_TOKEN_HERE"):
        patched = patched.replace(placeholder, bot_token)
    patched = patched.replace("__OWNER_ID__", str(owner_chat_id))

    # 3. Replace ANY hardcoded Telegram Bot Token pattern anywhere in the script
    patched = re.sub(
        r'(["\'])\d{6,12}:[A-Za-z0-9_-]{30,50}(["\'])',
        lambda m: f"{m.group(1)}{bot_token}{m.group(2)}",
        patched,
    )

    # 4. Replace token variable assignments (case-insensitive, supports indentation & type hints)
    patched = re.sub(
        r'^(\s*(?:BOT_TOKEN|TOKEN|API_TOKEN|TELEGRAM_TOKEN|TG_TOKEN|BOT_KEY)\s*(?::\s*[^=]+)?=\s*)(?:["\'][^"\']*["\'])',
        lambda m: f'{m.group(1)}"{bot_token}"',
        patched,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    # 5. Replace Owner/Admin ID assignments (supports ints, strings, and single-item lists)
    patched = re.sub(
        r'^(\s*(?:OWNER_ID|ADMIN_ID|OWNER|ADMIN|SUDO_ID|MASTER_ID|OWNER_CHAT_ID)\s*(?::\s*[^=]+)?=\s*)(?:["\']?\d+["\']?)',
        lambda m: f"{m.group(1)}{owner_chat_id}",
        patched,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    patched = re.sub(
        r'^(\s*(?:OWNERS|ADMINS|ADMIN_IDS|OWNER_IDS|SUDO_USERS)\s*(?::\s*[^=]+)?=\s*)\[\s*\d+(?:\s*,\s*\d+)*\s*\]',
        lambda m: f"{m.group(1)}[{owner_chat_id}]",
        patched,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    future_header = ("\n".join(future_lines) + "\n") if future_lines else ""

    # 6. Runtime Bootstrap Header: Forces env vars, sys.path, unbuffered UTF-8 logs,
    #    and hooks TeleBot / PTB / Aiogram / Pyrogram so the hosted token is ALWAYS used!
    bootstrap_header = (
        f"{future_header}"
        f"# =====================================================================\n"
        f"# 🌸 {BOT_BRAND.upper()} ISOLATED SESSION RUNNER (RDP + LINUX)\n"
        f"# Hosted by {BOT_BRAND} | Master Owner: {MASTER_OWNER_TAG}\n"
        f"# Assigned Bot Owner Chat ID: {owner_chat_id} | RAM Cap: {max_ram_mb} MB\n"
        f"# =====================================================================\n"
        f"import os as _sid_os, sys as _sid_sys\n"
        f"_sid_payload_dir = {json.dumps(PAYLOAD_DIR)}\n"
        f"if _sid_payload_dir not in _sid_sys.path:\n"
        f"    _sid_sys.path.insert(0, _sid_payload_dir)\n"
        f"try:\n"
        f"    _sid_sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)\n"
        f"    _sid_sys.stderr.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)\n"
        f"except Exception:\n"
        f"    pass\n"
        f"_SID_FORCED_TOKEN = {json.dumps(bot_token)}\n"
        f"_SID_FORCED_OWNER = {int(owner_chat_id)}\n"
        f"_sid_os.environ['BOT_TOKEN'] = _SID_FORCED_TOKEN\n"
        f"_sid_os.environ['TOKEN'] = _SID_FORCED_TOKEN\n"
        f"_sid_os.environ['API_TOKEN'] = _SID_FORCED_TOKEN\n"
        f"_sid_os.environ['TELEGRAM_TOKEN'] = _SID_FORCED_TOKEN\n"
        f"_sid_os.environ['OWNER_ID'] = str(_SID_FORCED_OWNER)\n"
        f"_sid_os.environ['ADMIN_ID'] = str(_SID_FORCED_OWNER)\n"
        f"_sid_os.environ['SUDO_USERS'] = str(_SID_FORCED_OWNER)\n"
        f"_sid_os.environ['HOSTER_NAME'] = {json.dumps(BOT_BRAND)}\n"
        f"_sid_os.environ['MASTER_OWNER'] = {json.dumps(MASTER_OWNER_TAG)}\n"
        f"_sid_os.environ['MAX_RAM_MB'] = {json.dumps(str(max_ram_mb))}\n"
        f"# Runtime Hook: Ensure TeleBot / PTB / Aiogram always receive the hosted token\n"
        f"try:\n"
        f"    import telebot as _sid_tb\n"
        f"    _orig_tb_init = _sid_tb.TeleBot.__init__\n"
        f"    def _patched_tb_init(self, token=None, *args, **kwargs):\n"
        f"        return _orig_tb_init(self, _SID_FORCED_TOKEN, *args, **kwargs)\n"
        f"    _sid_tb.TeleBot.__init__ = _patched_tb_init\n"
        f"except Exception:\n"
        f"    pass\n"
        f"try:\n"
        f"    from telegram.ext import ApplicationBuilder as _sid_ab\n"
        f"    _orig_ab_token = _sid_ab.token\n"
        f"    def _patched_ab_token(self, token):\n"
        f"        return _orig_ab_token(self, _SID_FORCED_TOKEN)\n"
        f"    _sid_ab.token = _patched_ab_token\n"
        f"except Exception:\n"
        f"    pass\n"
        f"try:\n"
        f"    import aiogram as _sid_aio\n"
        f"    _orig_aio_init = _sid_aio.Bot.__init__\n"
        f"    def _patched_aio_init(self, token=None, *args, **kwargs):\n"
        f"        return _orig_aio_init(self, _SID_FORCED_TOKEN, *args, **kwargs)\n"
        f"    _sid_aio.Bot.__init__ = _patched_aio_init\n"
        f"except Exception:\n"
        f"    pass\n\n"
    )

    runner_path = os.path.join(target_workspace, "runner.py")
    with open(runner_path, "w", encoding="utf-8") as f:
        f.write(bootstrap_header + patched)

    session_meta_path = os.path.join(target_workspace, "session.json")
    with open(session_meta_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "bot_token": bot_token,
                "owner_id": owner_chat_id,
                "max_ram_mb": max_ram_mb,
                "hosted_by": BOT_BRAND,
                "master_owner": MASTER_OWNER_TAG,
                "workspace": target_workspace,
                "script_source": src_path,
                "updated_at": datetime.now().isoformat(),
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    return runner_path


def kill_process_tree(pid: Optional[int]):
    if not pid:
        return
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        parent.terminate()
        _, alive = psutil.wait_procs(children + [parent], timeout=3)
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
    except Exception:
        pass


def is_pid_running(pid: Optional[int]) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        proc = psutil.Process(pid)
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def get_process_telemetry(pid: Optional[int], started_ts: Optional[float]) -> Dict[str, Any]:
    if not is_pid_running(pid):
        return {
            "status": "🥀 Stopped",
            "cpu": "0.0%",
            "ram": "0.0 MB",
            "ram_mb_num": 0.0,
            "cpu_num": 0.0,
            "threads": 0,
            "uptime": "0s",
        }
    try:
        proc = psutil.Process(pid)
        cpu = proc.cpu_percent(interval=0.05)
        mem_bytes = proc.memory_info().rss
        threads = proc.num_threads()
        for child in proc.children(recursive=True):
            try:
                mem_bytes += child.memory_info().rss
                threads += child.num_threads()
            except Exception:
                pass
        ram_mb = mem_bytes / (1024 * 1024)
        uptime_sec = int(time.time() - (started_ts or proc.create_time()))
        h, rem = divmod(max(uptime_sec, 0), 3600)
        m, s = divmod(rem, 60)
        return {
            "status": "🌸 Running",
            "cpu": f"{cpu:.1f}%",
            "ram": f"{ram_mb:.2f} MB",
            "ram_mb_num": ram_mb,
            "cpu_num": cpu,
            "threads": threads,
            "uptime": f"{h}h {m}m {s}s",
        }
    except Exception:
        return {
            "status": "🥀 Stopped",
            "cpu": "0.0%",
            "ram": "0.0 MB",
            "ram_mb_num": 0.0,
            "cpu_num": 0.0,
            "threads": 0,
            "uptime": "0s",
        }


def start_user_bot_process(user_id: int, bot_id: str) -> Tuple[bool, str]:
    with PROCESS_LOCK:
        sys_cfg = db.get_system_config()
        if not sys_cfg.get("hosting_enabled", True) and int(user_id) != SUPER_OWNER_ID:
            return False, "🥀 Hoster is currently paused by the Master Owner."

        user_data = db.get_user(user_id)
        if not user_data or str(bot_id) not in user_data["bots"]:
            return False, "🥀 Bot session not found."

        bot_meta = user_data["bots"][str(bot_id)]
        current_pid = bot_meta.get("pid")
        if is_pid_running(current_pid):
            return True, f"🌸 @{bot_meta['bot_username']} is already running (PID: <code>{current_pid}</code>)."

        workspace = bot_meta["workspace"]
        bot_token = bot_meta["token"]
        owner_chat_id = int(bot_meta.get("owner_chat_id", user_id))
        master_script = sys_cfg.get("master_script_path", DEFAULT_MASTER_SCRIPT)

        try:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{bot_token}/deleteWebhook",
                    json={"drop_pending_updates": True},
                    timeout=5,
                )
            except Exception:
                pass

            runner_path = build_isolated_runner(
                master_script_path=master_script,
                target_workspace=workspace,
                bot_token=bot_token,
                owner_chat_id=owner_chat_id,
            )

            log_path = os.path.join(workspace, "runtime.log")
            rotate_log_if_needed(log_path)

            # Open runtime.log and pass handle directly to Popen so SyntaxErrors & tracebacks are captured
            log_fh = open(log_path, "a", encoding="utf-8", errors="replace", buffering=1)
            log_fh.write(
                f"\n--- [🌸 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"Starting @{bot_meta['bot_username']} | Owner ID: {owner_chat_id} | "
                f"Hosted by {BOT_BRAND} ({MASTER_OWNER_TAG}) ---\n"
            )
            log_fh.flush()

            env = os.environ.copy()
            env["BOT_TOKEN"] = bot_token
            env["TOKEN"] = bot_token
            env["API_TOKEN"] = bot_token
            env["TELEGRAM_TOKEN"] = bot_token
            env["OWNER_ID"] = str(owner_chat_id)
            env["ADMIN_ID"] = str(owner_chat_id)
            env["SUDO_USERS"] = str(owner_chat_id)
            env["HOSTER_NAME"] = BOT_BRAND
            env["MASTER_OWNER"] = MASTER_OWNER_TAG
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"

            creation_flags = 0
            if IS_WINDOWS:
                creation_flags = (
                    getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                )

            try:
                proc = subprocess.Popen(
                    [sys.executable, "-u", runner_path],
                    cwd=workspace,
                    env=env,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=creation_flags,
                )
            finally:
                # Close parent's file descriptor so child owns it and Windows RDP never locks runtime.log
                try:
                    log_fh.close()
                except Exception:
                    pass

            # Wait 2.5 seconds to verify the process doesn't crash on import/startup
            time.sleep(2.5)

            if not is_pid_running(proc.pid):
                bot_meta["pid"] = None
                bot_meta["status"] = "crashed"
                db.add_or_update_bot(user_id, bot_id, bot_meta)
                crash_tail = ""
                if os.path.exists(log_path):
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as rf:
                        crash_tail = "".join(rf.readlines()[-12:]).strip()[-600:]
                err_detail = f"\n<pre>{telebot.formatting.escape_html(crash_tail)}</pre>" if crash_tail else ""
                return False, f"🥀 Process crashed on startup. Check Live Logs:{err_detail}"

            ACTIVE_PROCESSES[f"{user_id}:{bot_id}"] = proc
            bot_meta["pid"] = proc.pid
            bot_meta["status"] = "running"
            bot_meta["started_at"] = time.time()
            db.add_or_update_bot(user_id, bot_id, bot_meta)
            return True, f"🌸 Started @{bot_meta['bot_username']} (PID: <code>{proc.pid}</code>)"
        except Exception as e:
            return False, f"🥀 Failed to spawn process: {e}"


def stop_user_bot_process(user_id: int, bot_id: str) -> Tuple[bool, str]:
    with PROCESS_LOCK:
        user_data = db.get_user(user_id)
        if not user_data or str(bot_id) not in user_data["bots"]:
            return False, "🥀 Bot session not found."

        bot_meta = user_data["bots"][str(bot_id)]
        pid = bot_meta.get("pid")
        kill_process_tree(pid)
        ACTIVE_PROCESSES.pop(f"{user_id}:{bot_id}", None)

        time.sleep(1.0)

        bot_meta["pid"] = None
        bot_meta["status"] = "stopped"
        bot_meta["started_at"] = None
        db.add_or_update_bot(user_id, bot_id, bot_meta)
        return True, f"🥀 Stopped @{bot_meta['bot_username']} cleanly."


def terminate_and_delete_bot_session(user_id: int, bot_id: str) -> Tuple[bool, str]:
    with PROCESS_LOCK:
        stop_user_bot_process(user_id, bot_id)
        removed = db.remove_bot(user_id, bot_id)
        if not removed:
            return False, "🥀 Session already terminated."
        workspace = removed.get("workspace")
        if workspace and os.path.exists(workspace):
            windows_safe_rmtree(workspace)
        return True, f"💀 Terminated & wiped session for @{removed.get('bot_username')}."


def terminate_entire_user_session(user_id: int) -> Tuple[int, str]:
    with PROCESS_LOCK:
        uinfo = db.get_user(user_id)
        if not uinfo:
            return 0, "🥀 User session not found."
        bots = list(uinfo.get("bots", {}).keys())
        for bid in bots:
            stop_user_bot_process(user_id, bid)
        user_dir = uinfo.get("session_dir") or os.path.join(WORKSPACES_DIR, f"user_{user_id}")
        if os.path.exists(user_dir):
            windows_safe_rmtree(user_dir)
        db.delete_entire_user(user_id)
        return len(bots), f"💥 Terminated user {user_id} and wiped {len(bots)} bot session(s)."


# ============================================================================
# 🌸 REAL-TIME WATCHDOG, PER-BOT RAM OOM KILLER & AUTO-HEAL THREAD
# ============================================================================
def watchdog_loop():
    cpu_strike_tracker: Dict[str, int] = {}

    while True:
        try:
            data = db.load()
            sys_cfg = data.get("system", {})
            hosting_on = sys_cfg.get("hosting_enabled", True)
            auto_restart = sys_cfg.get("auto_restart", True)
            max_ram_mb = float(sys_cfg.get("max_ram_mb_per_bot", MAX_RAM_MB_PER_BOT))
            max_cpu_pct = float(sys_cfg.get("max_cpu_percent_per_bot", MAX_CPU_PERCENT_PER_BOT))

            for uid, uinfo in data.get("users", {}).items():
                for bid, bmeta in uinfo.get("bots", {}).items():
                    desired = bmeta.get("status")
                    pid = bmeta.get("pid")
                    alive = is_pid_running(pid)
                    proc_key = f"{uid}:{bid}"

                    if not hosting_on and alive:
                        stop_user_bot_process(int(uid), bid)
                        continue

                    if alive:
                        tele = get_process_telemetry(pid, bmeta.get("started_at"))
                        used_ram = tele["ram_mb_num"]
                        used_cpu = tele["cpu_num"]

                        if used_ram > max_ram_mb:
                            stop_user_bot_process(int(uid), bid)
                            bmeta["status"] = "oom_stopped"
                            bmeta["pid"] = None
                            db.add_or_update_bot(int(uid), bid, bmeta)

                            db.update_system_config(
                                oom_kills_count=sys_cfg.get("oom_kills_count", 0) + 1
                            )

                            log_path = os.path.join(bmeta["workspace"], "runtime.log")
                            try:
                                with open(log_path, "a", encoding="utf-8", errors="replace") as lf:
                                    lf.write(
                                        f"\n[💀 SAKURA OOM GUARD — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                                        f"Bot @{bmeta['bot_username']} terminated: RAM usage ({used_ram:.2f} MB) "
                                        f"exceeded per-bot limit ({max_ram_mb:.0f} MB).\n"
                                    )
                            except Exception:
                                pass

                            alert_kb = InlineKeyboardMarkup(row_width=2)
                            alert_kb.add(
                                SakuraButton("▶️ Restart Bot", callback_data=f"bot_start:{bid}", style="success"),
                                SakuraButton("📜 View Logs", callback_data=f"bot_logs:{bid}", style="primary"),
                            )
                            try:
                                bot.send_message(
                                    int(uid),
                                    f"💀 <b>Sakura RAM Protection Triggered!</b>\n\n"
                                    f"Your hosted bot <b>@{bmeta['bot_username']}</b> was automatically stopped because it exceeded the per-bot memory cap.\n\n"
                                    f"• <b>Bot RAM Used:</b> <code>{used_ram:.2f} MB</code>\n"
                                    f"• <b>Allowed Limit:</b> <code>{max_ram_mb:.0f} MB</code>\n"
                                    f"• <b>Status:</b> <code>🥀 OOM Stopped (Auto-Restart Paused)</code>",
                                    reply_markup=alert_kb,
                                )
                            except Exception:
                                pass

                            if int(uid) != SUPER_OWNER_ID:
                                try:
                                    bot.send_message(
                                        SUPER_OWNER_ID,
                                        f"🛡️ <b>OOM Guard Killed a Runaway Bot</b>\n"
                                        f"• <b>User:</b> {uinfo.get('username')} (<code>{uid}</code>)\n"
                                        f"• <b>Bot:</b> @{bmeta['bot_username']} (<code>{bid}</code>)\n"
                                        f"• <b>Peak RAM:</b> <code>{used_ram:.2f} MB / {max_ram_mb:.0f} MB</code>",
                                    )
                                except Exception:
                                    pass
                            continue

                        if used_cpu > max_cpu_pct:
                            cpu_strike_tracker[proc_key] = cpu_strike_tracker.get(proc_key, 0) + 1
                            if cpu_strike_tracker[proc_key] >= 3:
                                cpu_strike_tracker[proc_key] = 0
                                stop_user_bot_process(int(uid), bid)
                                bmeta["status"] = "cpu_throttled"
                                bmeta["pid"] = None
                                db.add_or_update_bot(int(uid), bid, bmeta)
                                try:
                                    bot.send_message(
                                        int(uid),
                                        f"⚠️ <b>CPU Overload Protection!</b>\n"
                                        f"Bot <b>@{bmeta['bot_username']}</b> was paused for sustained CPU overload (<code>{used_cpu:.1f}%</code>).",
                                    )
                                except Exception:
                                    pass
                        else:
                            cpu_strike_tracker[proc_key] = 0

                    elif hosting_on and desired == "running" and not alive and auto_restart:
                        start_user_bot_process(int(uid), bid)

        except Exception as e:
            print(f"[Watchdog Notice] {e}")
        time.sleep(5)


# ============================================================================
# 🌸 SAKURA THEME UI & COLORFUL BUTTON RENDERERS
# ============================================================================
def sakura_header(title: str) -> str:
    return (
        f"╭─── 🌸 <b>{BOT_BRAND.upper()}</b> 🌸 ───╮\n"
        f"│ 💮 <b>{title}</b>\n"
        f"│ 👑 <b>Owner:</b> {MASTER_OWNER_TAG}\n"
        f"╰──────────────────────────────╯"
    )


def get_hoster_uptime() -> str:
    sec = int(time.time() - HOSTER_BOOT_TIME)
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return f"{d}d {h}h {m}m {s}s" if d else f"{h}h {m}m {s}s"


def build_main_menu(user_id: int) -> InlineKeyboardMarkup:
    user_data = db.get_user(user_id) or {"bots": {}}
    hosted_count = len(user_data.get("bots", {}))
    max_slots = db.get_system_config().get("max_bots_per_user", MAX_BOTS_PER_USER)

    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        SakuraButton("🌸 Host New Bot (Token + ID)", callback_data="menu_host_new", style="success"),
        SakuraButton(f"💮 My Hosted Bots ({hosted_count}/{max_slots})", callback_data="menu_my_bots", style="primary"),
    )
    kb.add(
        SakuraButton("🎐 My Session & Performance", callback_data="menu_user_session", style="primary"),
        SakuraButton("🔄 Refresh Dashboard", callback_data="menu_home", style="success"),
    )
    if int(user_id) == SUPER_OWNER_ID:
        kb.add(SakuraButton("👑 Sakura Master Owner Panel", callback_data="owner_home", style="danger"))
    return kb


def render_home_text(user: telebot.types.User) -> str:
    uinfo = db.register_user(user)
    sys_cfg = db.get_system_config()
    bots = uinfo.get("bots", {})
    running_count = sum(1 for b in bots.values() if is_pid_running(b.get("pid")))
    max_slots = sys_cfg.get("max_bots_per_user", MAX_BOTS_PER_USER)
    max_ram = sys_cfg.get("max_ram_mb_per_bot", MAX_RAM_MB_PER_BOT)
    host_status = "🌸 <b>ONLINE</b>" if sys_cfg.get("hosting_enabled", True) else "🥀 <b>MAINTENANCE (OFF)</b>"

    return (
        f"{sakura_header('Sakura Cloud Bot Hoster')}\n\n"
        f"🎐 <b>Welcome, {telebot.formatting.escape_html(user.first_name)}!</b>\n"
        f"Host up to <b>{max_slots} Telegram Bots</b> instantly. Every hosted bot runs inside your isolated session with your <b>Chat ID</b> locked in as the script <code>OWNER_ID</code>.\n\n"
        f"╭─── 🌷 <b>Your Isolated Session</b> ───╮\n"
        f"│ 🆔 <b>Your Owner ID:</b> <code>{uinfo['default_owner_chat_id']}</code>\n"
        f"│ 💮 <b>Hosted Bots:</b> <code>{len(bots)}/{max_slots}</code>\n"
        f"│ ⚡ <b>Running Now:</b> <code>{running_count}</code>\n"
        f"│ 🛡️ <b>RAM Quota / Bot:</b> <code>{max_ram} MB</code>\n"
        f"│ 🏷️ <b>Bot Branding:</b> <code>{BOT_BRAND} | {MASTER_OWNER_TAG}</code>\n"
        f"│ ⛩️ <b>Engine State:</b> {host_status}\n"
        f"╰────────────────────────────────╯\n\n"
        f"💡 <i>Instant Host: Send <code>&lt;CHAT_ID&gt; &lt;BOT_TOKEN&gt;</code> or just <code>&lt;BOT_TOKEN&gt;</code> directly in chat!</i>"
    )


def build_my_bots_keyboard(user_id: int) -> InlineKeyboardMarkup:
    uinfo = db.get_user(user_id) or {"bots": {}}
    bots = uinfo.get("bots", {})
    kb = InlineKeyboardMarkup(row_width=1)

    for bid, bmeta in bots.items():
        alive = is_pid_running(bmeta.get("pid"))
        badge = "🌸 Running" if alive else ("💀 OOM Stopped" if bmeta.get("status") == "oom_stopped" else "🥀 Stopped")
        btn_style = "success" if alive else "danger"
        kb.add(
            SakuraButton(
                f"{badge} | @{bmeta['bot_username']} (Owner: {bmeta['owner_chat_id']})",
                callback_data=f"bot_view:{bid}",
                style=btn_style,
            )
        )

    kb.row(
        SakuraButton("➕ Host New Bot", callback_data="menu_host_new", style="success"),
        SakuraButton("🔙 Main Menu", callback_data="menu_home", style="primary"),
    )
    return kb


def build_single_bot_keyboard(bot_id: str, alive: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=3)
    if alive:
        kb.add(
            SakuraButton("⏹️ Stop", callback_data=f"bot_stop:{bot_id}", style="danger"),
            SakuraButton("🔄 Restart", callback_data=f"bot_restart:{bot_id}", style="primary"),
            SakuraButton("📊 Stats", callback_data=f"bot_stats:{bot_id}", style="success"),
        )
    else:
        kb.add(
            SakuraButton("▶️ Start", callback_data=f"bot_start:{bot_id}", style="success"),
            SakuraButton("🔄 Restart", callback_data=f"bot_restart:{bot_id}", style="primary"),
            SakuraButton("📊 Stats", callback_data=f"bot_stats:{bot_id}", style="primary"),
        )
    kb.row(
        SakuraButton("📜 Live Logs", callback_data=f"bot_logs:{bot_id}", style="primary"),
        SakuraButton("🆔 Change Owner ID", callback_data=f"bot_setowner:{bot_id}", style="primary"),
    )
    kb.row(
        SakuraButton("🌸 Sync Bio Branding", callback_data=f"bot_rebrand:{bot_id}", style="success"),
        SakuraButton("🚪 Session Logout", callback_data=f"bot_logout:{bot_id}", style="danger"),
    )
    kb.row(SakuraButton("🔙 Back to My Bots", callback_data="menu_my_bots", style="primary"))
    return kb


def render_bot_control_card(user_id: int, bot_id: str) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    uinfo = db.get_user(user_id)
    if not uinfo or str(bot_id) not in uinfo.get("bots", {}):
        return "🥀 <b>Bot session no longer exists.</b>", build_my_bots_keyboard(user_id)

    bmeta = uinfo["bots"][str(bot_id)]
    pid = bmeta.get("pid")
    alive = is_pid_running(pid)
    tele = get_process_telemetry(pid, bmeta.get("started_at"))
    max_ram = db.get_system_config().get("max_ram_mb_per_bot", MAX_RAM_MB_PER_BOT)
    masked_token = f"{bmeta['token'][:10]}...{bmeta['token'][-6:]}"

    status_label = tele["status"]
    if not alive and bmeta.get("status") == "oom_stopped":
        status_label = "💀 OOM Stopped (Exceeded RAM Cap)"
    elif not alive and bmeta.get("status") == "crashed":
        status_label = "🥀 Crashed on Startup (Check Logs)"

    text = (
        f"{sakura_header('Bot Session Control Center')}\n\n"
        f"🤖 <b>Bot:</b> @{bmeta['bot_username']} (<code>{bot_id}</code>)\n"
        f"👑 <b>Script Owner ID:</b> <code>{bmeta['owner_chat_id']}</code>\n"
        f"🏷️ <b>Profile Branding:</b> <code>Hosted by {BOT_BRAND} | {MASTER_OWNER_TAG}</code>\n"
        f"🔑 <b>Token:</b> <code>{masked_token}</code>\n"
        f"📂 <b>Isolated Session:</b> <code>user_{user_id}/bot_{bot_id}</code>\n\n"
        f"╭─── ⚡ <b>Real-Time Process Telemetry</b> ───╮\n"
        f"│ 📡 <b>Status:</b> {status_label}\n"
        f"│ ⚙️ <b>PID:</b> <code>{pid or 'None'}</code> (Threads: <code>{tele['threads']}</code>)\n"
        f"│ 🧠 <b>Memory (RSS):</b> <code>{tele['ram']} / {max_ram} MB</code>\n"
        f"│ 💻 <b>CPU Usage:</b> <code>{tele['cpu']}</code>\n"
        f"│ ⏱️ <b>Uptime:</b> <code>{tele['uptime']}</code>\n"
        f"╰────────────────────────────────────╯"
    )
    return text, build_single_bot_keyboard(str(bot_id), alive)


# ============================================================================
# 🌸 SAKURA OWNER PANEL, SESSION MANAGER & PERFORMANCE RENDERERS
# ============================================================================
def render_owner_panel() -> Tuple[str, InlineKeyboardMarkup]:
    data = db.load()
    sys_cfg = data["system"]
    users = data.get("users", {})

    total_users = len(users)
    total_bots = sum(len(u.get("bots", {})) for u in users.values())
    running_bots = 0
    total_bot_ram = 0.0

    for u in users.values():
        for b in u.get("bots", {}).values():
            if is_pid_running(b.get("pid")):
                running_bots += 1
                t = get_process_telemetry(b.get("pid"), b.get("started_at"))
                total_bot_ram += t["ram_mb_num"]

    script_path = sys_cfg.get("master_script_path", DEFAULT_MASTER_SCRIPT)
    script_exists = os.path.exists(script_path)
    script_size = f"{os.path.getsize(script_path) / 1024:.1f} KB" if script_exists else "Missing"
    hosting_on = sys_cfg.get("hosting_enabled", True)
    auto_restart = sys_cfg.get("auto_restart", True)
    auto_pip = sys_cfg.get("auto_pip_install", True)
    max_ram = sys_cfg.get("max_ram_mb_per_bot", MAX_RAM_MB_PER_BOT)
    oom_kills = sys_cfg.get("oom_kills_count", 0)

    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(BASE_DIR)
    cpu_total = psutil.cpu_percent(interval=0.05)
    platform_tag = "Windows RDP" if IS_WINDOWS else "Linux Server"

    text = (
        f"{sakura_header('👑 Master Owner Command Center')}\n\n"
        f"🖥️ <b>Platform:</b> <code>{platform_tag}</code>\n"
        f"⛩️ <b>Hoster Engine:</b> {'🟢 <b>ONLINE</b>' if hosting_on else '🔴 <b>OFFLINE (Paused)</b>'}\n"
        f"🔁 <b>Watchdog:</b> {'🌸 ON' if auto_restart else '🥀 OFF'} | 📦 <b>Auto-Pip:</b> {'🌸 ON' if auto_pip else '🥀 OFF'}\n"
        f"🛡️ <b>Per-Bot RAM Limit:</b> <code>{max_ram} MB</code> (OOM Kills: <code>{oom_kills}</code>)\n"
        f"📜 <b>Active Script:</b> <code>{os.path.basename(script_path)}</code> ({script_size})\n\n"
        f"╭─── 📊 <b>Live RDP / Server Performance</b> ───╮\n"
        f"│ 👥 <b>Users:</b> <code>{total_users}</code> | 🤖 <b>Bots:</b> <code>{running_bots}/{total_bots}</code> active\n"
        f"│ 🧠 <b>Hosted Bots RAM:</b> <code>{total_bot_ram:.2f} MB</code>\n"
        f"│ 💻 <b>System CPU:</b> <code>{cpu_total:.1f}%</code> ({psutil.cpu_count()} vCPU)\n"
        f"│ 📟 <b>System RAM:</b> <code>{vm.percent}% ({vm.used // (1024*1024)}MB / {vm.total // (1024*1024)}MB)</code>\n"
        f"│ 💾 <b>Disk Free:</b> <code>{disk.free / (1024**3):.2f} GB</code> ({disk.percent}% used)\n"
        f"│ ⏱️ <b>Hoster Uptime:</b> <code>{get_hoster_uptime()}</code>\n"
        f"╰──────────────────────────────────────────╯"
    )

    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        SakuraButton(
            "🔴 Turn Hoster OFF" if hosting_on else "🟢 Turn Hoster ON",
            callback_data="own_toggle_hoster",
            style="danger" if hosting_on else "success",
        ),
        SakuraButton(
            f"🔁 Watchdog: {'ON' if auto_restart else 'OFF'}",
            callback_data="own_toggle_watchdog",
            style="success" if auto_restart else "danger",
        ),
    )
    kb.add(
        SakuraButton("📤 Upload Script (.py / req.txt)", callback_data="own_upload_script", style="primary"),
        SakuraButton("🔄 Redeploy All User Bots", callback_data="own_redeploy_all", style="success"),
    )
    kb.add(
        SakuraButton("💻 Sakura Mini Terminal & Pip", callback_data="own_terminal", style="primary"),
        SakuraButton(
            f"📦 Auto-Pip on Upload: {'ON' if auto_pip else 'OFF'}",
            callback_data="own_toggle_autopip",
            style="success" if auto_pip else "danger",
        ),
    )
    kb.add(
        SakuraButton(f"🛡️ Bot RAM Cap: {max_ram} MB", callback_data="own_cycle_ram_cap", style="primary"),
        SakuraButton(f"💀 OOM Kills: {oom_kills}", callback_data="own_perf_stats", style="danger"),
    )
    kb.add(
        SakuraButton("👥 Manage & Terminate Sessions", callback_data="own_manage_users", style="danger"),
        SakuraButton("📈 Deep Performance Stats", callback_data="own_perf_stats", style="primary"),
    )
    kb.add(
        SakuraButton("⚡ Start All Bots", callback_data="own_start_all", style="success"),
        SakuraButton("🛑 Stop All Bots", callback_data="own_stop_all", style="danger"),
    )
    kb.add(
        SakuraButton("🗄️ Export All JSON Files", callback_data="own_export_json", style="primary"),
        SakuraButton("🔙 User Dashboard", callback_data="menu_home", style="primary"),
    )
    return text, kb


def render_owner_user_list() -> Tuple[str, InlineKeyboardMarkup]:
    data = db.load()
    users = data.get("users", {})
    max_slots = data["system"].get("max_bots_per_user", MAX_BOTS_PER_USER)

    lines = [
        f"{sakura_header('👥 All User Sessions & Termination Manager')}\n",
        "<i>Select any user below to inspect their hosted bots, view RAM/CPU usage, or terminate their session:</i>\n",
    ]

    kb = InlineKeyboardMarkup(row_width=1)
    if not users:
        lines.append("🥀 <b>No user sessions exist yet.</b>")
    else:
        for idx, (u_id, u_info) in enumerate(users.items(), 1):
            ubots = u_info.get("bots", {})
            running = sum(1 for b in ubots.values() if is_pid_running(b.get("pid")))
            uname = u_info.get("username", "NoUsername")
            fname = telebot.formatting.escape_html(u_info.get("full_name", "User"))
            lines.append(
                f"<b>{idx}. {fname}</b> ({uname}) — <code>{u_id}</code>\n"
                f"   ╰ 🤖 Hosted: <b>{len(ubots)}/{max_slots}</b> | 🌸 Active: <b>{running}</b>"
            )
            kb.add(
                SakuraButton(
                    f"👤 {uname} ({u_id}) • {len(ubots)}/{max_slots} Bots (🌸 {running})",
                    callback_data=f"own_usr_view:{u_id}",
                    style="success" if running > 0 else "primary",
                )
            )

    kb.row(
        SakuraButton("🔄 Refresh List", callback_data="own_manage_users", style="success"),
        SakuraButton("👑 Owner Panel", callback_data="owner_home", style="primary"),
    )
    return "\n".join(lines)[:4000], kb


def render_owner_single_user_session(target_uid: str) -> Tuple[str, InlineKeyboardMarkup]:
    uinfo = db.get_user(int(target_uid))
    kb = InlineKeyboardMarkup(row_width=2)

    if not uinfo:
        kb.add(SakuraButton("🔙 Back to Users", callback_data="own_manage_users", style="primary"))
        return "🥀 <b>User session has been terminated or does not exist.</b>", kb

    bots = uinfo.get("bots", {})
    max_ram = db.get_system_config().get("max_ram_mb_per_bot", MAX_RAM_MB_PER_BOT)
    total_ram = 0.0
    total_cpu = 0.0
    bot_lines = []

    for idx, (bid, bmeta) in enumerate(bots.items(), 1):
        tele = get_process_telemetry(bmeta.get("pid"), bmeta.get("started_at"))
        total_ram += tele["ram_mb_num"]
        total_cpu += tele["cpu_num"]
        alive = is_pid_running(bmeta.get("pid"))
        bot_lines.append(
            f"<b>{idx}. @{bmeta['bot_username']}</b> (<code>{bid}</code>)\n"
            f"   ├ State: {tele['status']} | PID: <code>{bmeta.get('pid') or 'None'}</code>\n"
            f"   ╰ Owner ID: <code>{bmeta['owner_chat_id']}</code> | RAM: <code>{tele['ram']} / {max_ram} MB</code>"
        )
        kb.row(
            SakuraButton(
                f"{'⏹️ Stop' if alive else '▶️ Start'} @{bmeta['bot_username']}",
                callback_data=f"own_ubot_toggle:{target_uid}:{bid}",
                style="primary" if alive else "success",
            ),
            SakuraButton(
                f"💀 Terminate @{bmeta['bot_username']}",
                callback_data=f"own_ubot_kill:{target_uid}:{bid}",
                style="danger",
            ),
        )

    bots_section = "\n".join(bot_lines) if bot_lines else "<i>No bots currently hosted in this session.</i>"
    uname = uinfo.get("username", "User")
    text = (
        f"{sakura_header(f'👤 Session Inspector: {uname}')}\n\n"
        f"👤 <b>Name:</b> {telebot.formatting.escape_html(uinfo.get('full_name', 'User'))}\n"
        f"🆔 <b>User ID / Owner ID:</b> <code>{target_uid}</code>\n"
        f"📂 <b>Workspace:</b> <code>workspaces/user_{target_uid}/</code>\n"
        f"🧠 <b>Total User RAM:</b> <code>{total_ram:.2f} MB</code> | 💻 <b>CPU:</b> <code>{total_cpu:.1f}%</code>\n"
        f"📅 <b>Joined:</b> <code>{uinfo.get('joined_at')}</code>\n\n"
        f"🌸 <b>Hosted Bots ({len(bots)}/{MAX_BOTS_PER_USER}):</b>\n"
        f"{bots_section}"
    )

    kb.row(
        SakuraButton("▶️ Start All User Bots", callback_data=f"own_uall_start:{target_uid}", style="success"),
        SakuraButton("⏹️ Stop All User Bots", callback_data=f"own_uall_stop:{target_uid}", style="primary"),
    )
    kb.row(
        SakuraButton("💥 Terminate & Wipe Entire User Session", callback_data=f"own_ukill_all:{target_uid}", style="danger")
    )
    kb.row(
        SakuraButton("🔙 All Users", callback_data="own_manage_users", style="primary"),
        SakuraButton("👑 Owner Panel", callback_data="owner_home", style="primary"),
    )
    return text[:4000], kb


# ============================================================================
# 🌸 DEPLOYMENT WORKFLOW (AUTO-BRANDING + ISOLATED SESSION + AUTO-START)
# ============================================================================
def deploy_bot_for_user(
    chat_id: int,
    user: telebot.types.User,
    owner_chat_id: int,
    bot_token: str,
) -> None:
    uinfo = db.register_user(user)
    sys_cfg = db.get_system_config()

    if not sys_cfg.get("hosting_enabled", True) and int(user.id) != SUPER_OWNER_ID:
        bot.send_message(
            chat_id,
            "🥀 <b>Hosting Paused!</b>\nThe Master Owner has temporarily disabled new bot deployments.",
            reply_markup=build_main_menu(user.id),
        )
        return

    max_slots = sys_cfg.get("max_bots_per_user", MAX_BOTS_PER_USER)
    current_bots = uinfo.get("bots", {})

    wait_msg = bot.send_message(
        chat_id,
        f"🌸 <i>Validating Bot Token, branding profile with <b>{BOT_BRAND} ({MASTER_OWNER_TAG})</b> & launching isolated session...</i>",
    )

    valid, bot_info, err, brand_note = validate_and_prepare_bot_token(
        token=bot_token,
        owner_chat_id=owner_chat_id,
        apply_branding=sys_cfg.get("auto_brand_bots", True),
    )

    if not valid or not bot_info:
        bot.edit_message_text(
            f"🥀 <b>Token Validation Failed!</b>\nReason: <code>{err}</code>\n\n"
            f"Please copy a valid token from @BotFather and try again.",
            chat_id,
            wait_msg.message_id,
            reply_markup=build_main_menu(user.id),
        )
        return

    bot_id = str(bot_info["id"])
    bot_username = bot_info.get("username", f"bot_{bot_id}")

    if bot_id not in current_bots and len(current_bots) >= max_slots:
        bot.edit_message_text(
            f"🥀 <b>10-Bot Limit Reached ({len(current_bots)}/{max_slots})!</b>\n"
            f"You can host up to <b>{max_slots} bots</b>.\n"
            f"Go to <b>💮 My Hosted Bots</b> and click <b>🚪 Session Logout</b> on an existing bot to free a slot.",
            chat_id,
            wait_msg.message_id,
            reply_markup=build_main_menu(user.id),
        )
        return

    if bot_id in current_bots:
        stop_user_bot_process(user.id, bot_id)

    bot_workspace = os.path.join(WORKSPACES_DIR, f"user_{user.id}", f"bot_{bot_id}")
    os.makedirs(bot_workspace, exist_ok=True)

    bot_meta = {
        "bot_id": bot_id,
        "bot_username": bot_username,
        "bot_first_name": bot_info.get("first_name", "Bot"),
        "token": bot_token.strip(),
        "owner_chat_id": int(owner_chat_id),
        "hosted_by": BOT_BRAND,
        "master_owner": MASTER_OWNER_TAG,
        "workspace": bot_workspace,
        "pid": None,
        "status": "stopped",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "started_at": None,
    }
    db.add_or_update_bot(user.id, bot_id, bot_meta)
    db.increment_deployments()

    ok, start_msg = start_user_bot_process(user.id, bot_id)
    updated_uinfo = db.get_user(user.id)
    slots_used = len(updated_uinfo.get("bots", {}))

    card_text, card_kb = render_bot_control_card(user.id, bot_id)
    status_header = (
        f"✅ <b>Hosted Successfully! ({slots_used}/{max_slots} Slots)</b>\n"
        if ok
        else f"⚠️ <b>Bot Registered ({slots_used}/{max_slots} Slots), but Process Exited!</b>\n"
    )
    header_notice = (
        f"{status_header}"
        f"{start_msg}\n"
        f"🏷️ <b>Bot Bio Updated:</b> <code>Hosted by {BOT_BRAND} | Owner: {MASTER_OWNER_TAG}</code>\n"
        f"👑 <b>Your Script Owner ID:</b> <code>{owner_chat_id}</code>\n\n"
    )
    bot.edit_message_text(
        header_notice + card_text,
        chat_id,
        wait_msg.message_id,
        reply_markup=card_kb,
    )


# ============================================================================
# 🌸 MESSAGE HANDLERS (COMMANDS, SCRIPT/PACKAGE UPLOADS, MINI TERMINAL)
# ============================================================================
@bot.message_handler(commands=["start", "help", "menu"])
def handle_start(message: telebot.types.Message):
    USER_STATES.pop(message.from_user.id, None)
    text = render_home_text(message.from_user)
    bot.send_message(message.chat.id, text, reply_markup=build_main_menu(message.from_user.id))


@bot.message_handler(commands=["owner", "admin", "panel"])
def handle_owner_cmd(message: telebot.types.Message):
    if int(message.from_user.id) != SUPER_OWNER_ID:
        bot.reply_to(message, f"🥀 <b>Access Denied!</b> Master Owner ({MASTER_OWNER_TAG}) only.")
        return
    USER_STATES.pop(message.from_user.id, None)
    text, kb = render_owner_panel()
    bot.send_message(message.chat.id, text, reply_markup=kb)


@bot.message_handler(commands=["setram"])
def handle_setram_cmd(message: telebot.types.Message):
    if int(message.from_user.id) != SUPER_OWNER_ID:
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        bot.reply_to(message, "🛡️ <b>Usage:</b> <code>/setram 200</code> (Sets per-bot RAM cap in MB)")
        return
    new_mb = max(32, min(int(parts[1]), 4096))
    db.update_system_config(max_ram_mb_per_bot=new_mb)
    bot.reply_to(message, f"🌸 <b>Per-Bot RAM Limit updated to <code>{new_mb} MB</code>!</b>")


@bot.message_handler(commands=["term", "sh", "pip"])
def handle_quick_terminal_cmd(message: telebot.types.Message):
    if int(message.from_user.id) != SUPER_OWNER_ID:
        return
    parts = (message.text or "").split(" ", 1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(
            message,
            "💻 <b>Usage:</b>\n"
            "• <code>/pip install requests aiohttp</code>\n"
            "• <code>/term pip list</code>\n"
            "• <code>/sh dir</code> (or <code>ls -la</code>)",
        )
        return

    cmd_type = parts[0].lstrip("/").lower()
    raw_arg = parts[1].strip()
    full_cmd = f"pip {raw_arg}" if cmd_type == "pip" and not raw_arg.startswith("pip ") else raw_arg

    wait = bot.reply_to(message, f"💻 <i>Executing:</i> <code>{telebot.formatting.escape_html(full_cmd)}</code> ...")
    code, output = execute_terminal_command(full_cmd)
    status_icon = "🌸" if code == 0 else f"🥀 (Exit {code})"
    bot.edit_message_text(
        f"{status_icon} <b>Terminal Output:</b>\n"
        f"<b>$</b> <code>{telebot.formatting.escape_html(full_cmd)}</code>\n\n"
        f"<pre>{telebot.formatting.escape_html(output)}</pre>",
        message.chat.id,
        wait.message_id,
    )


@bot.message_handler(content_types=["document"])
def handle_document_upload(message: telebot.types.Message):
    uid = message.from_user.id
    if int(uid) != SUPER_OWNER_ID:
        return

    doc = message.document
    fname = doc.file_name or ""

    if not (fname.endswith(".py") or fname.endswith(".txt") or fname.endswith(".json")):
        bot.reply_to(
            message,
            "🥀 <b>Unsupported File!</b> Upload a <code>.py</code> master script, <code>requirements.txt</code>, or <code>packages_map.json</code>.",
        )
        return

    wait_msg = bot.reply_to(message, f"🌸 <i>Downloading <code>{fname}</code> & processing...</i>")

    try:
        file_info = bot.get_file(doc.file_id)
        downloaded_bytes = bot.download_file(file_info.file_path)
        content_str = downloaded_bytes.decode("utf-8", errors="ignore")

        if fname.endswith(".json"):
            parsed_json = json.loads(content_str)
            if fname == "packages_map.json":
                with open(PACKAGES_MAP_FILE, "w", encoding="utf-8") as f:
                    json.dump(parsed_json, f, indent=2, ensure_ascii=False)
                IMPORT_TO_PYPI_MAP.update(parsed_json)
                msg_note = "Updated <code>packages_map.json</code> successfully!"
            else:
                db.save(parsed_json)
                msg_note = "Updated <code>sessions.json</code> database successfully!"
            kb = InlineKeyboardMarkup()
            kb.add(SakuraButton("👑 Back to Owner Panel", callback_data="owner_home", style="primary"))
            bot.edit_message_text(f"🌸 {msg_note}", message.chat.id, wait_msg.message_id, reply_markup=kb)
            return

        if fname.endswith(".txt"):
            req_path = os.path.join(PAYLOAD_DIR, "requirements_uploaded.txt")
            with open(req_path, "wb") as f:
                f.write(downloaded_bytes)

            pkgs = [
                line.strip()
                for line in content_str.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            ok, pip_out = install_packages_pip(pkgs)
            kb = InlineKeyboardMarkup()
            kb.add(SakuraButton("👑 Back to Owner Panel", callback_data="owner_home", style="primary"))
            bot.edit_message_text(
                f"{'🌸' if ok else '🥀'} <b>Requirements File Processed ({len(pkgs)} packages)</b>\n\n"
                f"<pre>{telebot.formatting.escape_html(pip_out[-3000:])}</pre>",
                message.chat.id,
                wait_msg.message_id,
                reply_markup=kb,
            )
            return

        os.makedirs(PAYLOAD_DIR, exist_ok=True)
        with open(DEFAULT_MASTER_SCRIPT, "wb") as f:
            f.write(downloaded_bytes)

        db.update_system_config(master_script_path=DEFAULT_MASTER_SCRIPT)
        USER_STATES.pop(uid, None)

        missing_pkgs = scan_missing_packages_from_code(content_str)
        auto_pip = db.get_system_config().get("auto_pip_install", True)
        pip_report = "🌸 <b>All imported packages are already installed!</b>"

        if missing_pkgs:
            if auto_pip:
                bot.edit_message_text(
                    f"📦 <i>Detected missing packages: <code>{', '.join(missing_pkgs)}</code>\n"
                    f"Auto-installing via pip now...</i>",
                    message.chat.id,
                    wait_msg.message_id,
                )
                ok, out = install_packages_pip(missing_pkgs)
                pip_report = (
                    f"{'✅' if ok else '⚠️'} <b>Auto-Installed Missing Packages:</b> <code>{', '.join(missing_pkgs)}</code>\n"
                    f"<pre>{telebot.formatting.escape_html(out[-1500:])}</pre>"
                )
            else:
                pip_report = (
                    f"⚠️ <b>Missing Packages Detected:</b> <code>{', '.join(missing_pkgs)}</code>\n"
                    f"<i>Tap the green button below to install them automatically.</i>"
                )

        kb = InlineKeyboardMarkup(row_width=1)
        if missing_pkgs and not auto_pip:
            kb.add(
                SakuraButton(
                    f"📦 Install Missing ({', '.join(missing_pkgs)[:28]})",
                    callback_data=f"own_pip_missing:{','.join(missing_pkgs)}",
                    style="success",
                )
            )
        kb.add(
            SakuraButton("🔄 Redeploy All User Bots Now", callback_data="own_redeploy_all", style="success"),
            SakuraButton("💻 Open Sakura Terminal", callback_data="own_terminal", style="primary"),
            SakuraButton("👑 Back to Owner Panel", callback_data="owner_home", style="primary"),
        )

        bot.edit_message_text(
            f"🌸 <b>Master Script Uploaded & Activated!</b>\n\n"
            f"• <b>File:</b> <code>{fname}</code> ({len(downloaded_bytes)/1024:.1f} KB)\n"
            f"• <b>Target Path:</b> <code>engine_payload/master_script.py</code>\n"
            f"• <b>Auto-Branding:</b> <code>Hosted by {BOT_BRAND} | {MASTER_OWNER_TAG}</code>\n\n"
            f"{pip_report}",
            message.chat.id,
            wait_msg.message_id,
            reply_markup=kb,
        )
    except Exception as e:
        bot.edit_message_text(
            f"🥀 <b>Upload Failed:</b> <code>{e}</code>",
            message.chat.id,
            wait_msg.message_id,
        )


@bot.message_handler(content_types=["text"])
def handle_text_input(message: telebot.types.Message):
    uid = message.from_user.id
    text = (message.text or "").strip()
    state = USER_STATES.get(uid, {})
    mode = state.get("mode")

    if int(uid) == SUPER_OWNER_ID and mode == "owner_terminal":
        wait = bot.reply_to(
            message,
            f"💻 <i>Running in Sakura Terminal:</i> <code>{telebot.formatting.escape_html(text)}</code> ...",
        )
        code, output = execute_terminal_command(text)
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            SakuraButton("📦 pip list", callback_data="own_term_cmd:pip list", style="primary"),
            SakuraButton("👑 Exit Terminal", callback_data="owner_home", style="danger"),
        )
        status_badge = "🟢 Exit 0" if code == 0 else f"🔴 Exit {code}"
        bot.edit_message_text(
            f"{sakura_header('💻 Sakura Mini Terminal')}\n\n"
            f"<b>$</b> <code>{telebot.formatting.escape_html(text)}</code> ({status_badge})\n\n"
            f"<pre>{telebot.formatting.escape_html(output)}</pre>\n\n"
            f"💡 <i>Send another command (e.g. <code>pip install &lt;pkg&gt;</code>) or tap Exit Terminal.</i>",
            message.chat.id,
            wait.message_id,
            reply_markup=kb,
        )
        return

    if mode == "await_chat_id":
        token_match = re.search(r"(\d{6,12}:[A-Za-z0-9_-]{30,50})", text)
        if token_match:
            token = token_match.group(1)
            prefix = text.replace(token, "").strip()
            owner_cid = int(prefix) if prefix.lstrip("-").isdigit() else uid
            USER_STATES.pop(uid, None)
            deploy_bot_for_user(message.chat.id, message.from_user, owner_cid, token)
            return

        if not text.lstrip("-").isdigit():
            bot.reply_to(
                message,
                "🥀 <b>Invalid Chat ID!</b> Send a numeric Telegram Chat ID or tap <b>💮 Use My Chat ID</b>.",
            )
            return

        owner_cid = int(text)
        USER_STATES[uid] = {"mode": "await_bot_token", "owner_chat_id": owner_cid}
        kb = InlineKeyboardMarkup()
        kb.add(SakuraButton("✖️ Cancel", callback_data="menu_home", style="danger"))
        bot.reply_to(
            message,
            f"🌸 <b>Script Owner Chat ID Locked:</b> <code>{owner_cid}</code>\n\n"
            f"🔑 <b>Step 2/2:</b> Now send your <b>Bot Token</b> from @BotFather to start hosting!",
            reply_markup=kb,
        )
        return

    if mode == "await_bot_token":
        owner_cid = int(state.get("owner_chat_id", uid))
        USER_STATES.pop(uid, None)
        deploy_bot_for_user(message.chat.id, message.from_user, owner_cid, text)
        return

    if mode == "await_new_owner_id":
        bot_id = state.get("bot_id")
        if not text.lstrip("-").isdigit():
            bot.reply_to(message, "🥀 Please send a valid numeric Chat ID.")
            return
        new_owner_id = int(text)
        USER_STATES.pop(uid, None)
        uinfo = db.get_user(uid)
        if uinfo and str(bot_id) in uinfo.get("bots", {}):
            bmeta = uinfo["bots"][str(bot_id)]
            bmeta["owner_chat_id"] = new_owner_id
            db.add_or_update_bot(uid, str(bot_id), bmeta)
            stop_user_bot_process(uid, str(bot_id))
            ok, msg = start_user_bot_process(uid, str(bot_id))
            card_text, card_kb = render_bot_control_card(uid, str(bot_id))
            bot.send_message(
                message.chat.id,
                f"🌸 <b>Updated Script Owner ID to <code>{new_owner_id}</code> & Restarted!</b>\n{msg}\n\n{card_text}",
                reply_markup=card_kb,
            )
        return

    token_match = re.search(r"(\d{6,12}:[A-Za-z0-9_-]{30,50})", text)
    if token_match:
        token = token_match.group(1)
        remainder = text.replace(token, "").strip().strip(":|,")
        owner_cid = int(remainder) if remainder and remainder.lstrip("-").isdigit() else uid
        deploy_bot_for_user(message.chat.id, message.from_user, owner_cid, token)
        return

    bot.send_message(
        message.chat.id,
        render_home_text(message.from_user),
        reply_markup=build_main_menu(uid),
    )


# ============================================================================
# 🌸 INLINE BUTTON CALLBACK ROUTER
# ============================================================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call: telebot.types.CallbackQuery):
    uid = call.from_user.id
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    data = call.data

    if data == "menu_home":
        USER_STATES.pop(uid, None)
        bot.edit_message_text(
            render_home_text(call.from_user),
            chat_id,
            msg_id,
            reply_markup=build_main_menu(uid),
        )
        bot.answer_callback_query(call.id, "🌸 Refreshed")

    elif data == "menu_host_new":
        uinfo = db.register_user(call.from_user)
        max_slots = db.get_system_config().get("max_bots_per_user", MAX_BOTS_PER_USER)
        if len(uinfo.get("bots", {})) >= max_slots:
            bot.answer_callback_query(
                call.id,
                f"🥀 You reached the {max_slots}/{max_slots} bot limit! Logout a bot first.",
                show_alert=True,
            )
            return

        USER_STATES[uid] = {"mode": "await_chat_id"}
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            SakuraButton(
                f"💮 Use My Chat ID ({uid}) as Owner ID",
                callback_data=f"host_use_my_id:{uid}",
                style="success",
            ),
            SakuraButton("🔙 Cancel", callback_data="menu_home", style="danger"),
        )
        bot.edit_message_text(
            f"{sakura_header('Deploy New Hosted Bot')}\n\n"
            f"🆔 <b>Step 1/2: Set Script Owner Chat ID</b>\n\n"
            f"• Tap <b>💮 Use My Chat ID ({uid})</b> to give yourself full owner permissions on the hosted bot.\n"
            f"• Or send any custom numeric <b>Chat ID</b>.\n"
            f"• Or directly send <code>&lt;CHAT_ID&gt; &lt;BOT_TOKEN&gt;</code> in one message!",
            chat_id,
            msg_id,
            reply_markup=kb,
        )
        bot.answer_callback_query(call.id)

    elif data.startswith("host_use_my_id:"):
        owner_cid = int(data.split(":")[1])
        USER_STATES[uid] = {"mode": "await_bot_token", "owner_chat_id": owner_cid}
        kb = InlineKeyboardMarkup()
        kb.add(SakuraButton("🔙 Cancel", callback_data="menu_home", style="danger"))
        bot.edit_message_text(
            f"{sakura_header('Deploy New Hosted Bot')}\n\n"
            f"👑 <b>Owner Chat ID Locked:</b> <code>{owner_cid}</code>\n"
            f"🏷️ <b>Auto-Bio Branding:</b> <code>Hosted by {BOT_BRAND} | {MASTER_OWNER_TAG}</code>\n\n"
            f"🔑 <b>Step 2/2: Send Your Bot Token</b>\n"
            f"Paste your Bot Token from @BotFather below to start hosting in real time!",
            chat_id,
            msg_id,
            reply_markup=kb,
        )
        bot.answer_callback_query(call.id, f"🌸 Owner ID set to {owner_cid}")

    elif data == "menu_my_bots":
        USER_STATES.pop(uid, None)
        uinfo = db.register_user(call.from_user)
        bots = uinfo.get("bots", {})
        max_slots = db.get_system_config().get("max_bots_per_user", MAX_BOTS_PER_USER)
        max_ram = db.get_system_config().get("max_ram_mb_per_bot", MAX_RAM_MB_PER_BOT)

        if not bots:
            text = (
                f"{sakura_header('My Hosted Bots (0/10)')}\n\n"
                f"🥀 You haven't hosted any bots yet.\n"
                f"Tap <b>➕ Host New Bot</b> below to deploy your first bot!"
            )
        else:
            lines = [f"{sakura_header(f'My Hosted Bots ({len(bots)}/{max_slots})')}\n"]
            for idx, (bid, bmeta) in enumerate(bots.items(), 1):
                tele = get_process_telemetry(bmeta.get("pid"), bmeta.get("started_at"))
                lines.append(
                    f"<b>{idx}. @{bmeta['bot_username']}</b> — {tele['status']}\n"
                    f"   ├ 👑 Owner: <code>{bmeta['owner_chat_id']}</code> | ⚙️ PID: <code>{bmeta.get('pid') or 'N/A'}</code>\n"
                    f"   ╰ 🧠 RAM: <code>{tele['ram']} / {max_ram} MB</code> | ⏱️ Up: <code>{tele['uptime']}</code>"
                )
            lines.append("\n👇 <i>Select a bot below for full controls, logs, stats, or session logout:</i>")
            text = "\n".join(lines)

        bot.edit_message_text(text, chat_id, msg_id, reply_markup=build_my_bots_keyboard(uid))
        bot.answer_callback_query(call.id)

    elif data == "menu_user_session":
        uinfo = db.register_user(call.from_user)
        bots = uinfo.get("bots", {})
        running = sum(1 for b in bots.values() if is_pid_running(b.get("pid")))
        total_ram = sum(
            get_process_telemetry(b.get("pid"), b.get("started_at"))["ram_mb_num"]
            for b in bots.values()
        )
        max_slots = db.get_system_config().get("max_bots_per_user", MAX_BOTS_PER_USER)

        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            SakuraButton("▶️ Start All My Bots", callback_data="usr_start_all", style="success"),
            SakuraButton("⏹️ Stop All My Bots", callback_data="usr_stop_all", style="primary"),
        )
        kb.add(
            SakuraButton("🚪 Logout & Wipe All My Sessions", callback_data="usr_logout_all", style="danger"),
            SakuraButton("🔙 Main Menu", callback_data="menu_home", style="primary"),
        )
        text = (
            f"{sakura_header('My Session & Performance')}\n\n"
            f"👤 <b>User:</b> {telebot.formatting.escape_html(uinfo['full_name'])} ({uinfo['username']})\n"
            f"🆔 <b>Default Owner ID:</b> <code>{uinfo['default_owner_chat_id']}</code>\n"
            f"📂 <b>Isolated Path:</b> <code>workspaces/user_{uid}/</code>\n"
            f"💮 <b>Slots Used:</b> <code>{len(bots)}/{max_slots}</code> (🌸 <code>{running}</code> running)\n"
            f"🧠 <b>Session Memory Usage:</b> <code>{total_ram:.2f} MB</code>\n"
            f"📅 <b>Created:</b> <code>{uinfo['joined_at']}</code>"
        )
        bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
        bot.answer_callback_query(call.id)

    elif data == "usr_start_all":
        uinfo = db.get_user(uid) or {"bots": {}}
        started = sum(1 for bid in list(uinfo.get("bots", {}).keys()) if start_user_bot_process(uid, bid)[0])
        bot.answer_callback_query(call.id, f"🌸 Started {started} bot(s)!", show_alert=True)
        call.data = "menu_user_session"
        handle_callbacks(call)

    elif data == "usr_stop_all":
        uinfo = db.get_user(uid) or {"bots": {}}
        for bid in list(uinfo.get("bots", {}).keys()):
            stop_user_bot_process(uid, bid)
        bot.answer_callback_query(call.id, "🥀 Stopped all your bots.", show_alert=True)
        call.data = "menu_user_session"
        handle_callbacks(call)

    elif data == "usr_logout_all":
        uinfo = db.get_user(uid) or {"bots": {}}
        count = len(uinfo.get("bots", {}))
        for bid in list(uinfo.get("bots", {}).keys()):
            terminate_and_delete_bot_session(uid, bid)
        bot.answer_callback_query(call.id, f"🚪 Logged out & wiped {count} session(s)!", show_alert=True)
        call.data = "menu_home"
        handle_callbacks(call)

    elif data.startswith("bot_view:"):
        bid = data.split(":")[1]
        text, kb = render_bot_control_card(uid, bid)
        bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
        bot.answer_callback_query(call.id)

    elif data.startswith("bot_start:"):
        bid = data.split(":")[1]
        ok, msg = start_user_bot_process(uid, bid)
        text, kb = render_bot_control_card(uid, bid)
        bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
        bot.answer_callback_query(call.id, re.sub(r"<[^>]+>", "", msg)[:180], show_alert=not ok)

    elif data.startswith("bot_stop:"):
        bid = data.split(":")[1]
        ok, msg = stop_user_bot_process(uid, bid)
        text, kb = render_bot_control_card(uid, bid)
        bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
        bot.answer_callback_query(call.id, re.sub(r"<[^>]+>", "", msg)[:180])

    elif data.startswith("bot_restart:"):
        bid = data.split(":")[1]
        stop_user_bot_process(uid, bid)
        ok, msg = start_user_bot_process(uid, bid)
        text, kb = render_bot_control_card(uid, bid)
        bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
        bot.answer_callback_query(
            call.id,
            "🔄 Bot Restarted!" if ok else re.sub(r"<[^>]+>", "", msg)[:180],
            show_alert=not ok,
        )

    elif data.startswith("bot_stats:"):
        bid = data.split(":")[1]
        text, kb = render_bot_control_card(uid, bid)
        try:
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
        except Exception:
            pass
        bot.answer_callback_query(call.id, "📊 Real-time metrics refreshed!")

    elif data.startswith("bot_rebrand:"):
        bid = data.split(":")[1]
        uinfo = db.get_user(uid)
        if uinfo and bid in uinfo.get("bots", {}):
            bmeta = uinfo["bots"][bid]
            validate_and_prepare_bot_token(bmeta["token"], bmeta["owner_chat_id"], apply_branding=True)
            bot.answer_callback_query(
                call.id,
                f"🌸 Bot description updated: Hosted by {BOT_BRAND} | Owner {MASTER_OWNER_TAG}",
                show_alert=True,
            )

    elif data.startswith("bot_logs:"):
        bid = data.split(":")[1]
        uinfo = db.get_user(uid)
        if not uinfo or bid not in uinfo.get("bots", {}):
            bot.answer_callback_query(call.id, "🥀 Session not found.", show_alert=True)
            return
        bmeta = uinfo["bots"][bid]
        log_path = os.path.join(bmeta["workspace"], "runtime.log")
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-35:]
            log_tail = "".join(lines).strip()[-3200:] or "No output logged yet."
        else:
            log_tail = "Log file not generated yet."

        bname = bmeta["bot_username"]
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            SakuraButton("🔄 Refresh Logs", callback_data=f"bot_logs:{bid}", style="success"),
            SakuraButton("🧹 Clear Logs", callback_data=f"bot_clearlog:{bid}", style="danger"),
            SakuraButton("🔙 Back to Bot", callback_data=f"bot_view:{bid}", style="primary"),
        )
        bot.edit_message_text(
            f"{sakura_header(f'📜 Live Logs: @{bname}')}\n\n"
            f"<pre>{telebot.formatting.escape_html(log_tail)}</pre>",
            chat_id,
            msg_id,
            reply_markup=kb,
        )
        bot.answer_callback_query(call.id)

    elif data.startswith("bot_clearlog:"):
        bid = data.split(":")[1]
        uinfo = db.get_user(uid)
        if uinfo and bid in uinfo.get("bots", {}):
            log_path = os.path.join(uinfo["bots"][bid]["workspace"], "runtime.log")
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"--- [🌸 Logs cleared at {datetime.now().strftime('%H:%M:%S')}] ---\n")
        bot.answer_callback_query(call.id, "🧹 Logs cleared!")
        call.data = f"bot_logs:{bid}"
        handle_callbacks(call)

    elif data.startswith("bot_setowner:"):
        bid = data.split(":")[1]
        USER_STATES[uid] = {"mode": "await_new_owner_id", "bot_id": bid}
        kb = InlineKeyboardMarkup()
        kb.add(SakuraButton("🔙 Cancel", callback_data=f"bot_view:{bid}", style="danger"))
        bot.edit_message_text(
            f"{sakura_header('Change Script Owner ID')}\n\n"
            f"Send the new numeric <b>Telegram Chat ID</b> to set as <code>OWNER_ID</code> for this bot:",
            chat_id,
            msg_id,
            reply_markup=kb,
        )
        bot.answer_callback_query(call.id)

    elif data.startswith("bot_logout:"):
        bid = data.split(":")[1]
        ok, msg = terminate_and_delete_bot_session(uid, bid)
        bot.answer_callback_query(call.id, msg, show_alert=True)
        call.data = "menu_my_bots"
        handle_callbacks(call)

    elif data.startswith("owner_") or data.startswith("own_"):
        if int(uid) != SUPER_OWNER_ID:
            bot.answer_callback_query(call.id, f"🥀 Master Owner ({MASTER_OWNER_TAG}) Only!", show_alert=True)
            return

        if data == "owner_home":
            USER_STATES.pop(uid, None)
            text, kb = render_owner_panel()
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
            bot.answer_callback_query(call.id)

        elif data == "own_toggle_hoster":
            cfg = db.get_system_config()
            new_state = not cfg.get("hosting_enabled", True)
            db.update_system_config(hosting_enabled=new_state)
            if not new_state:
                all_data = db.load()
                for u_id, u_info in all_data.get("users", {}).items():
                    for b_id in u_info.get("bots", {}).keys():
                        stop_user_bot_process(int(u_id), b_id)
            text, kb = render_owner_panel()
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
            bot.answer_callback_query(
                call.id,
                f"🌸 Hoster is now {'ONLINE' if new_state else 'OFFLINE (All bots paused)'}!",
                show_alert=True,
            )

        elif data == "own_toggle_watchdog":
            cfg = db.get_system_config()
            new_val = not cfg.get("auto_restart", True)
            db.update_system_config(auto_restart=new_val)
            text, kb = render_owner_panel()
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
            bot.answer_callback_query(call.id, f"🔁 Watchdog: {'ON' if new_val else 'OFF'}")

        elif data == "own_toggle_autopip":
            cfg = db.get_system_config()
            new_val = not cfg.get("auto_pip_install", True)
            db.update_system_config(auto_pip_install=new_val)
            text, kb = render_owner_panel()
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
            bot.answer_callback_query(call.id, f"📦 Auto-Pip on Script Upload: {'ON' if new_val else 'OFF'}")

        elif data == "own_cycle_ram_cap":
            presets = [64, 128, 150, 256, 512, 1024]
            current = int(db.get_system_config().get("max_ram_mb_per_bot", 150))
            next_cap = presets[(presets.index(current) + 1) % len(presets)] if current in presets else 150
            db.update_system_config(max_ram_mb_per_bot=next_cap)
            text, kb = render_owner_panel()
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
            bot.answer_callback_query(
                call.id,
                f"🛡️ Per-Bot RAM Limit updated to {next_cap} MB! (Or use /setram <MB>)",
                show_alert=True,
            )

        elif data == "own_upload_script":
            USER_STATES[uid] = {"mode": "awaiting_master_script"}
            kb = InlineKeyboardMarkup()
            kb.add(SakuraButton("🔙 Cancel", callback_data="owner_home", style="danger"))
            bot.edit_message_text(
                f"{sakura_header('📤 Upload Script, Requirements or JSON')}\n\n"
                f"Send any <b>Python file (<code>.py</code>)</b>, <b><code>requirements.txt</code></b>, or <b><code>packages_map.json</code></b> in chat now.\n\n"
                f"✨ <b>Real-Time Features on Upload:</b>\n"
                f"• <b>AST Package Scanner:</b> Automatically detects missing imports in your <code>.py</code> file and installs them via <code>pip</code>.\n"
                f"• <b>Dynamic Owner & Token Patching:</b> Injects each user's <code>BOT_TOKEN</code> and <code>OWNER_ID</code>.\n"
                f"• <b>Auto Bot Bio Branding:</b> Sets hosted bots' descriptions to <code>Hosted by {BOT_BRAND} | Owner: {MASTER_OWNER_TAG}</code>.",
                chat_id,
                msg_id,
                reply_markup=kb,
            )
            bot.answer_callback_query(call.id)

        elif data.startswith("own_pip_missing:"):
            pkgs_csv = data.split(":", 1)[1]
            pkgs = [p.strip() for p in pkgs_csv.split(",") if p.strip()]
            bot.answer_callback_query(call.id, f"📦 Installing: {', '.join(pkgs)}...")
            ok, out = install_packages_pip(pkgs)
            kb = InlineKeyboardMarkup()
            kb.add(SakuraButton("👑 Back to Owner Panel", callback_data="owner_home", style="primary"))
            bot.edit_message_text(
                f"{'🌸' if ok else '🥀'} <b>Manual Pip Installation Result:</b>\n"
                f"Packages: <code>{', '.join(pkgs)}</code>\n\n"
                f"<pre>{telebot.formatting.escape_html(out[-3000:])}</pre>",
                chat_id,
                msg_id,
                reply_markup=kb,
            )

        elif data == "own_terminal":
            USER_STATES[uid] = {"mode": "owner_terminal"}
            script_path = db.get_system_config().get("master_script_path", DEFAULT_MASTER_SCRIPT)
            missing = []
            if os.path.exists(script_path):
                with open(script_path, "r", encoding="utf-8", errors="ignore") as f:
                    missing = scan_missing_packages_from_code(f.read())

            kb = InlineKeyboardMarkup(row_width=2)
            if missing:
                kb.add(
                    SakuraButton(
                        f"📦 Auto-Fix Missing ({', '.join(missing)[:25]})",
                        callback_data=f"own_pip_missing:{','.join(missing)}",
                        style="success",
                    )
                )
            kb.add(
                SakuraButton("📦 pip list", callback_data="own_term_cmd:pip list", style="primary"),
                SakuraButton("🔍 Check Script Imports", callback_data="own_scan_script", style="success"),
            )
            kb.add(
                SakuraButton("⚡ Upgrade pip", callback_data="own_term_cmd:pip install --upgrade pip", style="primary"),
                SakuraButton("👑 Back to Owner Panel", callback_data="owner_home", style="danger"),
            )
            missing_str = f"<code>{', '.join(missing)}</code>" if missing else "✅ <b>None (All satisfied)</b>"
            bot.edit_message_text(
                f"{sakura_header('💻 Sakura Owner Mini-Terminal')}\n\n"
                f"🟢 <b>Interactive Terminal Mode Active!</b>\n"
                f"Type any command in chat to execute it directly on your RDP/Server:\n\n"
                f"• <code>pip install pyTelegramBotAPI psutil requests</code>\n"
                f"• <code>pip uninstall &lt;package&gt; -y</code>\n"
                f"• <code>python --version</code> or any shell command\n\n"
                f"🔍 <b>Missing Packages in Active Script:</b> {missing_str}",
                chat_id,
                msg_id,
                reply_markup=kb,
            )
            bot.answer_callback_query(call.id)

        elif data == "own_scan_script":
            script_path = db.get_system_config().get("master_script_path", DEFAULT_MASTER_SCRIPT)
            if os.path.exists(script_path):
                with open(script_path, "r", encoding="utf-8", errors="ignore") as f:
                    missing = scan_missing_packages_from_code(f.read())
            else:
                missing = []
            if not missing:
                bot.answer_callback_query(
                    call.id,
                    "🌸 All imports in master_script.py are already installed!",
                    show_alert=True,
                )
            else:
                ok, _ = install_packages_pip(missing)
                bot.answer_callback_query(
                    call.id,
                    f"{'✅ Installed' if ok else '🥀 Failed'}: {', '.join(missing)}",
                    show_alert=True,
                )
                call.data = "own_terminal"
                handle_callbacks(call)

        elif data.startswith("own_term_cmd:"):
            cmd = data.split(":", 1)[1]
            bot.answer_callback_query(call.id, f"💻 Running: {cmd}")
            code, output = execute_terminal_command(cmd)
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(
                SakuraButton("🔙 Terminal Home", callback_data="own_terminal", style="primary"),
                SakuraButton("👑 Owner Panel", callback_data="owner_home", style="danger"),
            )
            bot.edit_message_text(
                f"{sakura_header('💻 Terminal Execution Output')}\n\n"
                f"<b>$</b> <code>{telebot.formatting.escape_html(cmd)}</code>\n\n"
                f"<pre>{telebot.formatting.escape_html(output)}</pre>",
                chat_id,
                msg_id,
                reply_markup=kb,
            )

        elif data == "own_manage_users":
            USER_STATES.pop(uid, None)
            text, kb = render_owner_user_list()
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
            bot.answer_callback_query(call.id)

        elif data.startswith("own_usr_view:"):
            target_uid = data.split(":")[1]
            text, kb = render_owner_single_user_session(target_uid)
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
            bot.answer_callback_query(call.id)

        elif data.startswith("own_ubot_toggle:"):
            _, target_uid, bid = data.split(":")
            uinfo = db.get_user(int(target_uid))
            if uinfo and bid in uinfo.get("bots", {}):
                pid = uinfo["bots"][bid].get("pid")
                if is_pid_running(pid):
                    stop_user_bot_process(int(target_uid), bid)
                    bot.answer_callback_query(call.id, "⏹️ Stopped user bot.")
                else:
                    start_user_bot_process(int(target_uid), bid)
                    bot.answer_callback_query(call.id, "▶️ Started user bot.")
            text, kb = render_owner_single_user_session(target_uid)
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)

        elif data.startswith("own_ubot_kill:"):
            _, target_uid, bid = data.split(":")
            ok, msg = terminate_and_delete_bot_session(int(target_uid), bid)
            bot.answer_callback_query(call.id, msg, show_alert=True)
            text, kb = render_owner_single_user_session(target_uid)
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)

        elif data.startswith("own_uall_start:"):
            target_uid = data.split(":")[1]
            uinfo = db.get_user(int(target_uid)) or {"bots": {}}
            for bid in list(uinfo.get("bots", {}).keys()):
                start_user_bot_process(int(target_uid), bid)
            bot.answer_callback_query(call.id, "▶️ Started all bots for this user!")
            text, kb = render_owner_single_user_session(target_uid)
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)

        elif data.startswith("own_uall_stop:"):
            target_uid = data.split(":")[1]
            uinfo = db.get_user(int(target_uid)) or {"bots": {}}
            for bid in list(uinfo.get("bots", {}).keys()):
                stop_user_bot_process(int(target_uid), bid)
            bot.answer_callback_query(call.id, "⏹️ Stopped all bots for this user!")
            text, kb = render_owner_single_user_session(target_uid)
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)

        elif data.startswith("own_ukill_all:"):
            target_uid = data.split(":")[1]
            _, msg = terminate_entire_user_session(int(target_uid))
            bot.answer_callback_query(call.id, msg, show_alert=True)
            text, kb = render_owner_user_list()
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)

        elif data == "own_perf_stats":
            vm = psutil.virtual_memory()
            swap = psutil.swap_memory()
            disk = psutil.disk_usage(BASE_DIR)
            net = psutil.net_io_counters()
            self_proc = psutil.Process(os.getpid())
            all_data = db.load()
            sys_cfg = all_data["system"]

            text = (
                f"{sakura_header('📈 Deep RDP / Server Telemetry')}\n\n"
                f"💻 <b>CPU Cores:</b> <code>{psutil.cpu_count(logical=False)} Physical / {psutil.cpu_count()} Logical</code>\n"
                f"⚡ <b>CPU Usage:</b> <code>{psutil.cpu_percent(interval=0.1)}%</code>\n"
                f"🧠 <b>RAM:</b> <code>{vm.used // (1024**2)} MB / {vm.total // (1024**2)} MB ({vm.percent}%)</code>\n"
                f"🛡️ <b>Per-Bot RAM Cap:</b> <code>{sys_cfg.get('max_ram_mb_per_bot', 150)} MB</code>\n"
                f"💀 <b>Total OOM Kills:</b> <code>{sys_cfg.get('oom_kills_count', 0)}</code>\n"
                f"🔄 <b>Swap:</b> <code>{swap.used // (1024**2)} MB / {swap.total // (1024**2)} MB ({swap.percent}%)</code>\n"
                f"💾 <b>Disk:</b> <code>{disk.used / (1024**3):.2f} GB / {disk.total / (1024**3):.2f} GB ({disk.percent}%)</code>\n"
                f"🌐 <b>Network I/O:</b> <code>⬆️ {net.bytes_sent / (1024**2):.1f} MB | ⬇️ {net.bytes_recv / (1024**2):.1f} MB</code>\n"
                f"🧵 <b>Hoster Engine Threads:</b> <code>{self_proc.num_threads()}</code>\n"
                f"🚀 <b>Total Historical Deployments:</b> <code>{sys_cfg.get('total_deployments', 0)}</code>\n"
                f"⏱️ <b>Engine Uptime:</b> <code>{get_hoster_uptime()}</code>"
            )
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(
                SakuraButton("🔄 Refresh Metrics", callback_data="own_perf_stats", style="success"),
                SakuraButton("👑 Owner Panel", callback_data="owner_home", style="primary"),
            )
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
            bot.answer_callback_query(call.id)

        elif data == "own_redeploy_all":
            all_data = db.load()
            redeployed = 0
            for u_id, u_info in all_data.get("users", {}).items():
                for b_id, b_meta in u_info.get("bots", {}).items():
                    stop_user_bot_process(int(u_id), b_id)
                    validate_and_prepare_bot_token(
                        b_meta["token"],
                        b_meta["owner_chat_id"],
                        apply_branding=True,
                    )
                    ok, _ = start_user_bot_process(int(u_id), b_id)
                    if ok:
                        redeployed += 1
            text, kb = render_owner_panel()
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
            bot.answer_callback_query(
                call.id,
                f"🔄 Redeployed & branded {redeployed} bot(s) across all users!",
                show_alert=True,
            )

        elif data == "own_export_json":
            bot.answer_callback_query(call.id, "🗄️ Exporting all JSON files...")
            for jpath, label in [
                (SESSIONS_FILE, "sessions.json (Live User & Bot Sessions)"),
                (CONFIG_FILE, "config.json (Master Hoster Config)"),
                (PACKAGES_MAP_FILE, "packages_map.json (AST Auto-Pip Map)"),
            ]:
                if os.path.exists(jpath):
                    with open(jpath, "rb") as f:
                        bot.send_document(
                            chat_id,
                            f,
                            caption=f"🌸 <b>{BOT_BRAND} ({MASTER_OWNER_TAG})</b> — <code>{label}</code>",
                        )

        elif data == "own_start_all":
            all_data = db.load()
            db.update_system_config(hosting_enabled=True)
            count = 0
            for u_id, u_info in all_data.get("users", {}).items():
                for b_id in u_info.get("bots", {}).keys():
                    ok, _ = start_user_bot_process(int(u_id), b_id)
                    if ok:
                        count += 1
            text, kb = render_owner_panel()
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
            bot.answer_callback_query(call.id, f"⚡ Started {count} hosted bots!", show_alert=True)

        elif data == "own_stop_all":
            all_data = db.load()
            count = 0
            for u_id, u_info in all_data.get("users", {}).items():
                for b_id in u_info.get("bots", {}).keys():
                    stop_user_bot_process(int(u_id), b_id)
                    count += 1
            text, kb = render_owner_panel()
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
            bot.answer_callback_query(call.id, f"🛑 Stopped {count} hosted bots!", show_alert=True)


# ============================================================================
# 🌸 BOOTSTRAP & SESSION RESTORATION
# ============================================================================
def restore_sessions_on_boot():
    data = db.load()
    if not data.get("system", {}).get("hosting_enabled", True):
        print(f"[🌸 {BOT_BRAND}] Hosting is OFF in sessions.json; skipping boot restore.")
        return

    restored = 0
    for uid, uinfo in data.get("users", {}).items():
        for bid, bmeta in uinfo.get("bots", {}).items():
            if bmeta.get("status") == "running":
                ok, _ = start_user_bot_process(int(uid), bid)
                if ok:
                    restored += 1
    print(f"[🌸 {BOT_BRAND}] Restored {restored} active bot session(s) | Master Owner: {MASTER_OWNER_TAG}")


if __name__ == "__main__":
    print("╭────────────────────────────────────────────────────────╮")
    print(f"│ 🌸 Starting {BOT_BRAND} | Owner: {MASTER_OWNER_TAG} 🌸         │")
    print("╰────────────────────────────────────────────────────────╯")
    restore_sessions_on_boot()
    wd_thread = threading.Thread(target=watchdog_loop, daemon=True)
    wd_thread.start()
    bot.infinity_polling(timeout=30, long_polling_timeout=15, skip_pending=True)
