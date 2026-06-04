#!/opt/homebrew/bin/python3
# <xbar.title>TokenPUA</xbar.title>
# <xbar.version>3.0.0</xbar.version>
# <xbar.author>josephdeng</xbar.author>
# <xbar.abouturl>https://token.woa.com/?product=codebuddy</xbar.abouturl>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>

import json
import logging
import os
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from calendar import monthrange
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─── SSL ─────────────────────────────────────
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# ─── Config ───────────────────────────────────
BASE_URL   = "https://token.woa.com"
PLATFORMS = "all"
DASHBOARD_URL = "https://token.woa.com/"

CONFIG_DIR   = Path.home() / ".config" / "tokens-woa"
COOKIE_FILE = CONFIG_DIR / "cc_cookie"
MODE_FILE   = CONFIG_DIR / "mode"    # "auto" or "manual"
CACHE_FILE  = CONFIG_DIR / "cache.json"
KEY_CACHE   = CONFIG_DIR / "safe_storage_key"

# ─── Constants ─────────────────────────────
PBKDF2_ITERATIONS = 1003
AES_IV_SIZE = 16
MAX_API_PAGES = 10
API_PAGE_SIZE = 50
REMAINING_WD_WARNING = 5
HIGH_SPEND_THRESHOLD = 100.0
DEFAULT_LOOKUP_DAYS = 7
DEFAULT_MIN_COST = 0.001
DEFAULT_RECORD_LIMIT = 50
NOOP = "bash=/usr/bin/true terminal=false"

# 模型名称缩写映射（渲染时替换，保持表格紧凑）
MODEL_ALIASES = {
    "DeepSeek": "DS",
}

# ─── CredStore ───────────────────────────────
def cred_read(path: Path) -> Optional[str]:
    try:
        if path.exists():
            v = path.read_text().strip()
            return v if v else None
    except (OSError, PermissionError) as e:
        logger.warning(f"Failed to read credential {path}: {e}")
    return None

def cred_write(path: Path, value: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        os.chmod(path, 0o600)
    except (OSError, PermissionError) as e:
        logger.warning(f"Failed to write credential {path}: {e}")

def get_cookie() -> Optional[str]:
    return cred_read(COOKIE_FILE)

def set_cookie(cookie: str) -> None:
    cred_write(COOKIE_FILE, cookie)

# ─── BrowserCookie ────────────────────────────
class BrowserCookie:
    BROWSERS = [
        ("Microsoft Edge Safe Storage",
         Path.home() / "Library/Application Support/Microsoft Edge"),
        ("Chrome Safe Storage",
         Path.home() / "Library/Application Support/Google/Chrome"),
    ]
    _key_cache = {}

    HOST_PATTERNS = (
        "%token.woa.com%",
        "%tokens.woa.com%",
        "%with.woa.com%",
        "%.woa.com%",
    )
    ORDER_CASE = (
        "CASE "
        "WHEN host_key LIKE '%token.woa.com%' THEN 0 "
        "WHEN host_key LIKE '%tokens.woa.com%' THEN 1 "
        "WHEN host_key LIKE '%with.woa.com%' THEN 2 "
        "ELSE 9 END"
    )

    @classmethod
    def _get_key(cls, service):
        import hashlib
        if service in cls._key_cache:
            return cls._key_cache[service]
        # 文件缓存：避免每次刷新都调 security（钥匙串弹窗干扰）
        if KEY_CACHE.exists():
            try:
                cached = KEY_CACHE.read_bytes()
                if len(cached) == AES_IV_SIZE:
                    cls._key_cache[service] = cached
                    return cached
            except OSError:
                pass
        try:
            r = subprocess.run(
                ["security", "find-generic-password", "-w", "-s", service],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode != 0 or not r.stdout.strip():
                return None
            pwd = r.stdout.strip().encode("utf-8")
            key = hashlib.pbkdf2_hmac("sha1", pwd, b"saltysalt", PBKDF2_ITERATIONS, dklen=AES_IV_SIZE)
            cls._key_cache[service] = key
            # 持久化到文件，后续不再弹窗
            try:
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                KEY_CACHE.write_bytes(key)
                KEY_CACHE.chmod(0o600)
            except OSError:
                pass
            return key
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, KeyError) as e:
            logger.debug(f"Failed to get key for {service}: {e}")
            return None

    @classmethod
    def _decrypt(cls, enc, key):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        enc_bytes = enc.tobytes() if isinstance(enc, memoryview) else enc
        if not enc_bytes:
            return None
        if enc_bytes[:3] != b"v10":
            return enc_bytes.decode("utf-8", errors="replace").strip("\x00")
        payload = enc_bytes[3:]
        iv = b" " * AES_IV_SIZE
        dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        raw = dec.update(payload) + dec.finalize()
        pad_len = raw[-1]
        if 1 <= pad_len <= min(AES_IV_SIZE, len(raw)):
            unpadded = raw[:-pad_len]
        else:
            unpadded = raw
        for candidate in (unpadded[32:], unpadded):
            if not candidate:
                continue
            try:
                decoded = candidate.decode("utf-8").rstrip("\x00").strip()
                if decoded:
                    return decoded
            except UnicodeDecodeError:
                continue
        return None

    @classmethod
    def _iter_dbs(cls, browser_base):
        if not browser_base.exists():
            return
        for p in browser_base.iterdir():
            if not p.is_dir():
                continue
            if p.name == "Default" or p.name.startswith("Profile "):
                db = p / "Cookies"
                if db.exists():
                    yield db

    @classmethod
    def _read_db(cls, db_path, key):
        import shutil, sqlite3
        tmp = Path(tempfile.NamedTemporaryFile(prefix="tpua_", suffix=".db", delete=False).name)
        try:
            shutil.copy2(db_path, tmp)
            conn = sqlite3.connect(tmp)
            where = " OR ".join("host_key LIKE ?" for _ in cls.HOST_PATTERNS)
            rows = conn.execute(
                f"SELECT name, value, encrypted_value FROM cookies "
                f"WHERE {where} ORDER BY {cls.ORDER_CASE}, last_access_utc DESC",
                cls.HOST_PATTERNS,
            ).fetchall()
            conn.close()
        except (sqlite3.Error, OSError) as e:
            logger.warning(f"Failed to read cookie DB {db_path}: {e}")
            return None
        finally:
            try:
                Path(tmp).unlink()
            except OSError:
                pass
        cookies = {}
        seen = set()
        for name, value, enc in rows:
            if name in seen:
                continue
            seen.add(name)
            val = ""
            if isinstance(value, str):
                val = value.strip()
            elif isinstance(value, bytes):
                val = value.decode("utf-8", errors="replace").strip()
            if not val and enc:
                val = cls._decrypt(enc, key)
            if val:
                cookies[name] = val
        return "; ".join(f"{k}={v}" for k, v in cookies.items()) if cookies else None

    @classmethod
    def extract(cls, validate: bool = True) -> Optional[str]:
        for _service, browser_base in cls.BROWSERS:
            key = cls._get_key(_service)
            if not key:
                continue
            for db_path in cls._iter_dbs(browser_base):
                cookie_str = cls._read_db(db_path, key)
                if not cookie_str:
                    continue
                if validate:
                    if cls._check_cookie(cookie_str):
                        return cookie_str
                else:
                    return cookie_str
        return None

    @classmethod
    def _check_cookie(cls, cookie):
        try:
            today = date.today().isoformat()
            url = (f"{BASE_URL}/api/usage-summary?start_date={today}&end_date={today}"
                    f"&dimension=personal&platform=all")
            req = urllib.request.Request(url)
            req.add_header("Cookie", cookie)
            req.add_header("User-Agent", "TokenPUA/3.0")
            with urllib.request.urlopen(req, timeout=8, context=SSL_CTX) as resp:
                body = resp.read().decode()
                return body.strip() and not body.strip().startswith("<!")
        except (urllib.error.URLError, OSError) as e:
            logger.debug(f"Cookie validation failed: {e}")
            return False
    
# ─── ApiClient ────────────────────────────────
import urllib.request
import urllib.error

class ApiClient:
    @classmethod
    def _get(cls, path: str, cookie: str) -> tuple[bool, Optional[dict], Optional[str]]:
        url = f"{BASE_URL}{path}"
        req = urllib.request.Request(url)
        req.add_header("Cookie", cookie)
        req.add_header("User-Agent", "TokenPUA/3.0")
        try:
            with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
                if resp.status == 200:
                    body = resp.read().decode()
                    if body.strip().startswith("<!") or body.strip().startswith("<html>"):
                        return False, None, "AUTH_EXPIRED"
                    data = json.loads(body)
                    return True, data, None
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return False, None, "AUTH_EXPIRED"
        except json.JSONDecodeError:
            return False, None, "PARSE_ERROR"
        except (urllib.error.URLError, OSError) as e:
            logger.debug(f"Network error in API request: {e}")
        return False, None, "NETWORK_ERROR"

    @classmethod
    def fetch_quota(cls, cookie: str, platform: str = "codebuddy") -> tuple[bool, Optional[dict], Optional[str]]:
        return cls._get(f"/api/query-quota?platform={platform}", cookie)

    @classmethod
    def fetch_usage_summary(cls, cookie: str, start: str, end: str) -> tuple[bool, Optional[dict], Optional[str]]:
        path = (f"/api/usage-summary?start_date={start}&end_date={end}"
                f"&dimension=personal&platform={PLATFORMS}")
        return cls._get(path, cookie)

    @classmethod
    def fetch_usage_details(cls, cookie: str, start: str, end: str, page: int = 1) -> tuple[bool, Optional[dict], Optional[str]]:
        path = (f"/api/usage-details?start_date={start}&end_date={end}"
                f"&dimension=all&page={page}&page_size={API_PAGE_SIZE}&platform=all")
        return cls._get(path, cookie)

    @classmethod
    def fetch_recent_high_cost(cls, cookie: str, days: int = DEFAULT_LOOKUP_DAYS, min_cost: float = DEFAULT_MIN_COST, limit: int = DEFAULT_RECORD_LIMIT) -> list[dict]:
        """获取最近 N 天消费大于指定金额的记录"""
        records = []
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        for page in range(1, MAX_API_PAGES + 1):
            ok, data, _ = cls.fetch_usage_details(
                cookie, start_date.isoformat(), end_date.isoformat(), page
            )
            if not ok or not data:
                break
            for rec in data.get("data", []):
                try:
                    cost_str = str(rec.get("cost", "¥0")).replace("¥", "").replace(",", "")
                    cost = float(cost_str)
                    if cost >= min_cost:
                        # 解析 total_tokens
                        total_str = str(rec.get("total_tokens", "0")).replace(",", "")
                        records.append({
                            "time": rec.get("request_time", "")[:16],  # YYYY-MM-DD HH:MM
                            "model": rec.get("model_name", "-"),
                            "cost": cost,
                            "total_tokens": int(total_str) if total_str.isdigit() else 0,
                            "user_input": rec.get("user_input", "")[:100],  # 截断到100字符
                        })
                except (ValueError, TypeError):
                    pass
            if len(records) >= limit:
                break
        # API 本身已按最新时间排序，只需取前 limit 条
        return records[:limit]

# ─── AuthManager ────────────────────────────
class AuthManager:
    LOGIN_URL = "https://token.woa.com/?product=codebuddy"

    @classmethod
    def _mode(cls) -> str:
        try:
            return MODE_FILE.read_text().strip()
        except (OSError, IOError):
            return "auto"

    @classmethod
    def ensure(cls):
        cookie = get_cookie()
        if cookie and cls._is_valid(cookie):
            return cookie
        if cls._mode() == "manual":
            return None  # 手动模式：不尝试自动提取
        new_cookie = BrowserCookie.extract(validate=True)
        if new_cookie:
            set_cookie(new_cookie)
            return new_cookie
        return None

    @classmethod
    def refresh(cls, old_cookie):
        if cls._mode() == "manual":
            return None
        new_cookie = BrowserCookie.extract(validate=False)
        if new_cookie and new_cookie != old_cookie:
            set_cookie(new_cookie)
            return new_cookie
        return None

    @classmethod
    def _is_valid(cls, cookie):
        ok, _, _ = ApiClient.fetch_quota(cookie, platform="codebuddy")
        return ok

    @classmethod
    def open_login_and_wait(cls, timeout=120):
        if cls._mode() == "manual":
            return False  # 手动模式：不读浏览器，用户从菜单「手动输入Cookie」填入
        cookie = BrowserCookie.extract(validate=True)
        if cookie:
            set_cookie(cookie)
            return True
        # 不行再打开浏览器让用户登录
        app_opened = False
        for cmd in (
            ["open", "-a", "Microsoft Edge", cls.LOGIN_URL],
            ["open", "-a", "Google Chrome", cls.LOGIN_URL],
            ["open", cls.LOGIN_URL],
        ):
            try:
                if subprocess.run(cmd, capture_output=True, timeout=5).returncode == 0:
                    app_opened = True
                    break
            except (subprocess.TimeoutExpired, OSError):
                continue
        if not app_opened:
            return False
        time.sleep(2)
        deadline = time.time() + timeout
        while time.time() < deadline:
            cookie = BrowserCookie.extract(validate=True)
            if cookie:
                set_cookie(cookie)
                return True
            time.sleep(2)
        return False

# ─── Pacing ─────────────────────────────────
def count_workdays(start: date, end: date) -> int:
    d = start
    n = 0
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n

def calc_pacing(spent: float, budget: float, remaining_wd: int) -> dict:
    today = date.today()
    _, total_days = monthrange(today.year, today.month)
    month_elapsed_pct = today.day / total_days * 100

    # daily_quota = remaining amount / remaining workdays
    daily_quota = (budget - spent) / max(remaining_wd, 1)

    # pacing: actual daily avg vs theoretical daily avg
    total_wd = count_workdays(today.replace(day=1), today.replace(day=total_days))
    elapsed_wd = count_workdays(today.replace(day=1), today)
    ideal_daily = budget / max(total_wd, 1)
    actual_daily = spent / max(elapsed_wd, 1)
    ratio = actual_daily / ideal_daily if ideal_daily >= 0.01 else 999

    if ratio > 1.3:
        icon, text = "\U0001f7e5", "加速"
    elif ratio > 1.1:
        icon, text = "\U0001f7e1", "稍加速"
    elif ratio > 0.9:
        icon, text = "\U0001f7e2", "完美"
    elif ratio > 0.7:
        icon, text = "\U0001f7e1", "可放缓"
    else:
        icon, text = "\U0001f535", "省着用"

    warning = None
    if remaining_wd <= REMAINING_WD_WARNING and (budget - spent) > HIGH_SPEND_THRESHOLD:
        warning = (f"还剩 ¥{budget - spent:.0f}，仅剩 {remaining_wd} 个工作日，建议多用 Opus")

    return dict(
        spent=spent, budget=budget,
        pct=spent / budget * 100 if budget else 0,
        daily_quota=daily_quota,
        status_icon=icon, status_text=text,
        warning=warning,
        remaining_wd=remaining_wd,
        total_days=total_days,
        month_elapsed_pct=month_elapsed_pct,
    )

# ─── UI ─────────────────────────────────────
BAR_WIDTH = 18

def ansi_bar(pct: float, width: int = BAR_WIDTH) -> str:
    filled = max(0, min(width, int(pct / 100 * width)))
    if pct > 90:
        fg = "\033[31m"
    elif pct > 70:
        fg = "\033[33m"
    else:
        fg = "\033[32m"
    return f"{fg}{'█' * filled}\033[90m{'░' * (width - filled)}\033[0m"

def _is_manual_mode() -> bool:
    return AuthManager._mode() == "manual"

def render_no_cookie() -> None:
    _dir = os.path.dirname(os.path.abspath(__file__))
    _py = sys.executable or "/usr/bin/python3"
    print("\u26a0\ufe0f TokenPUA: 需要登录 | color=#FF6B6B")
    print("---")
    if _is_manual_mode():
        print(f"\U0001f512 手动输入 Cookie | bash={_py} param1={_dir}/tokens.3m.py param2=--prompt-cookie terminal=true")
        print("如何获取 Cookie： | color=#888888 size=11 {NOOP}")
        print("  1. 浏览器打开 token.woa.com 并登录 | color=#888888 size=11 {NOOP}")
        print("  2. F12 → Application → Cookies | color=#888888 size=11 {NOOP}")
        print("  3. 复制所有 Cookie（格式：name=value; ...）| color=#888888 size=11 {NOOP}")
    else:
        action = f"bash={_py} param1={_dir}/tokens.3m.py param2=--login terminal=false"
        print(f"\U0001f512 点击登录 | {action}")

def render_auth_expired():
    _dir = os.path.dirname(os.path.abspath(__file__))
    _py = sys.executable or "/usr/bin/python3"
    print("\u26a0\ufe0f TokenPUA: 登录已过期 | color=#FF6B6B")
    print("---")
    if _is_manual_mode():
        print(f"\U0001f512 重新输入 Cookie | bash={_py} param1={_dir}/tokens.3m.py param2=--prompt-cookie terminal=true")
    else:
        action = f"bash={_py} param1={_dir}/tokens.3m.py param2=--login terminal=false"
        print(f"\U0001f512 点击重新登录 | {action}")

def render_error(msg):
    print("\u274c TokenPUA: 请求失败 | color=#FF6B6B")
    print("---")
    print(f"{msg} | color=#999999 size=11 bash=/usr/bin/true terminal=false")

def render(pacing: dict, today_used: float) -> None:
    spent  = pacing["spent"]
    budget = pacing["budget"]
    pct    = pacing["pct"]
    daily_q = pacing["daily_quota"]
    rem_wd = pacing["remaining_wd"]
    total_days = pacing["total_days"]
    month_elapsed_pct = pacing["month_elapsed_pct"]

    # menu bar title
    print(f"{pacing['status_icon']} ¥{spent:.0f}/¥{budget:.0f} · {pacing['status_text']} | size=13")
    print("---")

    # ── month progress ──────────────────
    print("月进度 | size=11 color=#888888")
    month_time_bar = ansi_bar(month_elapsed_pct)
    month_quota_bar = ansi_bar(pct)
    print(f" 额度  {month_quota_bar}  {pct:.0f}%  ¥{spent:.0f}/¥{budget:.0f} | ansi=true size=12 font=Menlo {NOOP}")
    print(f" 时间  {month_time_bar}  {month_elapsed_pct:.0f}%  {date.today().day}/{total_days}天 | ansi=true size=12 font=Menlo {NOOP}")
    print("---")

    # ── day progress ─────────────────────
    print("日进度 | size=11 color=#888888")
    now = datetime.now()
    day_time_pct = (now.hour * 60 + now.minute) / 1440 * 100
    day_pct = (today_used / daily_q * 100) if daily_q > 0 else 0
    day_quota_bar = ansi_bar(min(day_pct, 100))
    print(f" 额度  {day_quota_bar}  {day_pct:.0f}%  ¥{today_used:.1f}/¥{daily_q:.0f} | ansi=true size=12 font=Menlo {NOOP}")
    day_time_bar = ansi_bar(day_time_pct)
    print(f" 时间  {day_time_bar}  {day_time_pct:.0f}%  {now.hour:02d}:{now.minute:02d}/24:00 | ansi=true size=12 font=Menlo {NOOP}")

def render_records_table(records: list[dict]) -> None:
    """渲染近期消费记录表格"""
    print("---")
    print("明细 | size=11 color=#888888")
    for rec in records:
        # 格式：时间  金额  模型  token  用户消息(最后一列，可较长)
        time_str = rec["time"][11:16] if len(rec["time"]) >= 16 else rec["time"]  # HH:MM
        model = rec["model"]
        # 模型名称缩写
        for prefix, alias in MODEL_ALIASES.items():
            if model.startswith(prefix):
                model = alias + model[len(prefix):]
                break
        # Claude 模型去掉前缀 "Claude-"，节省显示宽度
        if model.startswith("Claude-"):
            model = model[7:]
        model = model[:18] if len(model) > 18 else model
        cost = rec["cost"]
        tokens = rec["total_tokens"]
        user_input = (rec["user_input"] or "").replace("\n", " ").replace("\r", "").replace("|", "｜")
        # 用户消息截到60显示宽度（中文=2宽，英文=1宽）
        ui_trunc = ""
        w = 0
        for c in user_input:
            cw = 2 if ord(c) > 127 else 1
            if w + cw > 60:
                break
            ui_trunc += c
            w += cw

        # 避免消息里的 | 被 SwiftBar 当成参数分隔符解析
        ui_trunc = ui_trunc.replace("|", "｜")

        cost_str = f"¥{cost:.3f}"
        token_str = f"{tokens:,}"

        # 用户消息放最后一列；模型列定宽10字符，token 列右对齐10字符
        model_fixed = model[:10] if len(model) > 10 else model
        line = f"{time_str:<5}  {cost_str:>8}    {model_fixed:<10} {token_str:>10}    {ui_trunc}"
        if cost > 100:
            color_param = " color=#990000"
        elif cost > 50:
            color_param = " color=#BB2222"
        elif cost > 20:
            color_param = " color=#CC9900"
        elif cost < 0.0005:
            color_param = " color=#999999"
        else:
            color_param = ""
        print(f"{line} | size=11 font=Menlo {NOOP}{color_param}")

def render_with_records(pacing: dict, today_used: float, records: list[dict]) -> None:
    render(pacing, today_used)
    if not records:
        return
    render_records_table(records)
    time_label = render_time_label()
    render_bottom_section(pacing, time_label)

def render_time_label() -> str:
    """计算缓存时间的可读标签"""
    cache = load_cache()
    last_time = cache.get("time", "") if cache else ""
    if last_time and " " in last_time:
        try:
            # 提取 time 部分 "HH:MM" 进行比较
            time_part = last_time.split(" ")[1] if " " in last_time else last_time
            last_h, last_m = map(int, time_part.split(":"))
            now = datetime.now()
            now_h = now.hour
            now_m = now.minute
            diff_min = (now_h * 60 + now_m) - (last_h * 60 + last_m)
            # 处理跨午夜的情况（虽然不太可能在这个场景）
            if diff_min < 0:
                diff_min += 1440
            if diff_min == 0:
                return "刚刚更新"
            elif diff_min < 60:
                return f"{diff_min}分钟前更新"
            else:
                return f"{diff_min // 60}小时前更新"
        except (ValueError, IndexError) as e:
            logger.debug(f"Failed to parse time {last_time}: {e}")
            return f"{last_time} 更新"
    return "刚刚更新"

def render_bottom_section(pacing: dict, time_label: str) -> None:
    """渲染底部警告、链接和刷新按钮"""
    if pacing.get("warning"):
        print("---")
        print(f"⚠️ {pacing['warning']} | size=11 color=#FF6B6B {NOOP}")

    # 底部：打开看板 / 刷新（含时间标签） / 退出
    print("---")
    print(f"打开 Token 看板 | href={DASHBOARD_URL} | size=11")
    print(f"刷新（{time_label}） | refresh=true")
    print(f"退出 TokenPUA | bash=/usr/bin/defaults param1=write param2=com.ameba.SwiftBar param3=DisabledPlugins param4=-array-add param5=tokens.3m.py terminal=false refresh=true")

# ─── Cache ──────────────────────────────────
def save_cache(data: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False))
    except (OSError, TypeError) as e:
        logger.warning(f"Failed to save cache: {e}")

def load_cache() -> Optional[dict]:
    try:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text())
    except (OSError, json.JSONDecodeError) as e:
        logger.debug(f"Failed to load cache: {e}")
    return None

# ─── Main ─────────────────────────────────────
def main() -> None:
    cookie = AuthManager.ensure()
    if not cookie:
        render_no_cookie()
        return

    ok, data, err = ApiClient.fetch_quota(cookie, platform="codebuddy")
    if err == "AUTH_EXPIRED":
        new_cookie = AuthManager.refresh(cookie)
        if new_cookie:
            cookie = new_cookie
            ok, data, err = ApiClient.fetch_quota(cookie, platform="codebuddy")
        if not ok:
            render_auth_expired()
            return

    if not ok:
        cache = load_cache()
        if cache:
            render_error(f"network error, showing {cache.get('time', '')} cache")
        else:
            render_error(str(err or "request failed"))
        return

    total_used  = float((data or {}).get("total_used", 0) or 0)
    total_quota = float((data or {}).get("total_quota", 0) or 1000)

    # today cost: accumulate cost field from usage-details
    today_str = date.today().isoformat()
    _, details, _ = ApiClient.fetch_usage_details(cookie, today_str, today_str)
    today_used = 0.0
    if details and isinstance(details.get("data"), list):
        for rec in details["data"]:
            try:
                c = str(rec.get("cost", "0")).replace("¥", "").replace(",", "")
                today_used += float(c)
            except (ValueError, TypeError):
                pass

    # remaining workdays
    today = date.today()
    _, total_days = monthrange(today.year, today.month)
    month_end = today.replace(day=total_days)
    remaining_wd = count_workdays(today, month_end)

    # 近期高消费记录
    records = ApiClient.fetch_recent_high_cost(cookie, days=DEFAULT_LOOKUP_DAYS, min_cost=0, limit=45)

    pacing = calc_pacing(total_used, total_quota, remaining_wd)
    render_with_records(pacing, today_used, records)
    save_cache({"time": datetime.now().strftime("%m-%d %H:%M"), "spent": total_used})

def handle_login() -> None:
    print("TokenPUA 登录中...")
    if AuthManager.open_login_and_wait(timeout=120):
        print("✅ 成功")
    else:
        print("⚠️ 超时或未检测到登录态，请从菜单栏点击「点击登录」重试")
    try:
        subprocess.run(["open", "swiftbar://refreshplugin?name=tokens"],
                       capture_output=True, timeout=5)
    except subprocess.TimeoutExpired:
        pass

def handle_set_cookie() -> None:
    """从 stdin 读取用户手动提供的 Cookie 并保存"""
    import sys
    cookie = sys.stdin.read().strip()
    if not cookie:
        print("❌ 未收到 Cookie")
        sys.exit(1)
    set_cookie(cookie)
    print("✅ Cookie 已保存")
    try:
        subprocess.run(["open", "swiftbar://refreshplugin?name=tokens"],
                       capture_output=True, timeout=5)
    except subprocess.TimeoutExpired:
        pass

def handle_prompt_cookie() -> None:
    """弹出 AppleScript 输入框让用户输入 Cookie"""
    _dir = os.path.dirname(os.path.abspath(__file__))
    _py = sys.executable or "/usr/bin/python3"
    # 写入临时 AppleScript 文件（避免 Shell 转义问题）
    script = f'''tell application "System Events"
        display dialog "请粘贴 CC Cookie:\\n\\n获取方式：\\n1. 浏览器打开 token.woa.com 并登录\\n2. F12 → Application → Cookies\\n3. 复制全部 Cookie（格式：name=value; ...）" default answer "" with title "TokenPUA — 输入 Cookie" buttons {{"取消", "确定"}} default button 2
        set cookie to text returned of result
        do shell script "\\\\"{_py}\\" \\\\\"{_dir}/tokens.3m.py\\\\" --set-cookie <<< " & quoted form of cookie
    end tell'''
    import tempfile
    scpt = tempfile.NamedTemporaryFile(suffix=".scpt", delete=False, mode="w")
    scpt.write(script)
    scpt.close()
    subprocess.run(["osascript", scpt.name], capture_output=True, timeout=120)
    try:
        os.unlink(scpt.name)
    except OSError:
        pass

if __name__ == "__main__":
    try:
        arg = sys.argv[1] if len(sys.argv) > 1 else ""
        if arg in ("--login", "--setup"):
            handle_login()
            sys.exit(0)
        if arg == "--set-cookie":
            handle_set_cookie()
            sys.exit(0)
        if arg == "--prompt-cookie":
            handle_prompt_cookie()
            sys.exit(0)
        main()
    except Exception as e:
        print(f"\u274c TokenPUA 错误 | color=#FF6B6B")
        print("---")
        print(f"{type(e).__name__}: {e} | color=#FF6B6B size=10")
        print("\U0001f504 刷新 | refresh=true")
