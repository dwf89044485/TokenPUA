#!/opt/homebrew/bin/python3
# <xbar.title>TokenPUA</xbar.title>
# <xbar.desc>Monthly token usage burndown predictor for tokens.woa.com</xbar.desc>
# <xbar.version>2.0.0</xbar.version>
# <xbar.author>josephdeng</xbar.author>
# <xbar.abouturl>https://tokens.woa.com/?product=codebuddy</xbar.abouturl>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>
# <xbar.hideAbout>true</xbar.hideAbout>
# <xbar.hideRunInTerminal>true</xbar.hideRunInTerminal>
# <xbar.hideLastUpdated>true</xbar.hideLastUpdated>
# <xbar.hideSwiftBar>true</xbar.hideSwiftBar>
# <xbar.hideDisablePlugin>true</xbar.hideDisablePlugin>

import json
import os
import re as _re
import ssl
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from calendar import monthrange
from pathlib import Path
from typing import Literal, Optional

# ─── SSL: 内网服务，跳过证书验证 ─────────────────────────
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# ─── Config ───────────────────────────────────────────────
BASE_URL = "https://tokens-nbyxw43y.app.with.woa.com"
PLATFORMS = "codebuddy,with,codebuddy-code,codebuddy-cli,codex-internal,xcode"
BUDGET = 1000.0  # CC 月总额度默认回退值
KEYCHAIN_SERVICE = "tokens-woa"
KEYCHAIN_ACCOUNT = "cookie"
DASHBOARD_URL = "https://tokens.woa.com/?product=codebuddy"

CB_BASE_URL = "https://tencent.sso.codebuddy.cn"
CB_ENTERPRISE_ID = "etahzsqej0n4"
CB_TOKEN_LIMIT = 150000  # 月度积分上限
CB_POINTS_PER_USD = 100.0

CONFIG_DIR = Path.home() / ".config" / "tokens-woa"
CC_COOKIE_FILE = CONFIG_DIR / "cc_cookie"
CB_COOKIE_FILE = CONFIG_DIR / "cb_cookie"
FORCE_INIT_FILE = CONFIG_DIR / "force_init"
CACHE_FILE = CONFIG_DIR / "cache.json"
CB_HELPER_CACHE_FILE = CONFIG_DIR / "cb_helper_cache.json"
CB_HELPER_CACHE_TTL_SECONDS = 15 * 60
CB_HELPER_LOG_DIR = CONFIG_DIR / "logs"
CB_HELPER_STDOUT_LOG = CB_HELPER_LOG_DIR / "cb_helper.stdout.log"
CB_HELPER_STDERR_LOG = CB_HELPER_LOG_DIR / "cb_helper.stderr.log"
CB_HELPER_LAUNCH_LABEL = "com.tokenpua.cbhelper"

LAST_CB_ERROR = None  # module-level error state for CB

# ─── Module: CredStore ────────────────────────────────────
class CredStore:
    """凭证存储：纯文件，无 Keychain（避免弹窗）。"""

    @classmethod
    def _read(cls, path: Path) -> Optional[str]:
        try:
            if path.exists():
                v = path.read_text().strip()
                return v if v else None
        except Exception:
            pass
        return None

    @classmethod
    def _write(cls, path: Path, value: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
            os.chmod(path, 0o600)
        except Exception:
            pass

    @classmethod
    def get_cc(cls) -> Optional[str]:
        return cls._read(CC_COOKIE_FILE)

    @classmethod
    def set_cc(cls, cookie: str) -> None:
        cls._write(CC_COOKIE_FILE, cookie)

    @classmethod
    def get_cb(cls) -> Optional[str]:
        return cls._read(CB_COOKIE_FILE)

    @classmethod
    def set_cb(cls, cookie: str) -> None:
        cls._write(CB_COOKIE_FILE, cookie)

    @classmethod
    def clear_all(cls) -> None:
        for f in (
            CC_COOKIE_FILE,
            CB_COOKIE_FILE,
            FORCE_INIT_FILE,
            CACHE_FILE,
            CB_HELPER_CACHE_FILE,
            CB_HELPER_STDOUT_LOG,
            CB_HELPER_STDERR_LOG,
        ):
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass


# ─── Module: BrowserCookie ────────────────────────────────
class BrowserCookie:
    """从 Edge/Chrome Cookie DB 提取 cookie，统一 CC/CB。"""

    BROWSERS = [
        ("Microsoft Edge Safe Storage",
         Path.home() / "Library/Application Support/Microsoft Edge"),
        ("Chrome Safe Storage",
         Path.home() / "Library/Application Support/Google/Chrome"),
    ]

    # 内存缓存：同一进程内只取一次 Safe Storage 密钥
    _key_cache: dict[str, bytes] = {}

    CC_HOST_PATTERNS = (
        "%tokens-nbyxw43y.app.with.woa.com%",
        "%tokens.woa.com%",
        "%with.woa.com%",
        "%.woa.com%",
    )
    CC_ORDER_CASE = """
        CASE
          WHEN host_key LIKE '%tokens-nbyxw43y.app.with.woa.com%' THEN 0
          WHEN host_key LIKE '%app.with.woa.com%' THEN 1
          WHEN host_key LIKE '%with.woa.com%' THEN 2
          WHEN host_key LIKE '%tokens.woa.com%' THEN 3
          WHEN host_key LIKE '%.woa.com%' THEN 4
          ELSE 9
        END"""

    CB_HOST_PATTERNS = ("%tencent.sso.codebuddy.cn%", "%codebuddy.cn%")
    CB_PREFERRED_NAMES = ('_gcl_au', 'qcloud_visitId', 'i18next', 'session', 'session_2')

    @classmethod
    def _get_safe_storage_key(cls, service: str) -> Optional[bytes]:
        import hashlib
        if service in cls._key_cache:
            return cls._key_cache[service]
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-w", "-s", service],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None
            pwd = result.stdout.strip().encode('utf-8')
            key = hashlib.pbkdf2_hmac('sha1', pwd, b'saltysalt', 1003, dklen=16)
            cls._key_cache[service] = key
            return key
        except Exception:
            return None

    @classmethod
    def _decrypt(cls, enc, key: bytes) -> Optional[str]:
        """AES-128-CBC 解密浏览器 cookie 值。"""
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        enc_bytes = enc.tobytes() if isinstance(enc, memoryview) else enc
        if not enc_bytes:
            return None
        if enc_bytes[:3] != b'v10':
            return enc_bytes.decode('utf-8', errors='replace').strip('\x00')

        payload = enc_bytes[3:]
        iv = b' ' * 16
        dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        raw = dec.update(payload) + dec.finalize()
        pad_len = raw[-1]
        unpadded = raw[:-pad_len] if 1 <= pad_len <= 16 else raw

        for candidate in (unpadded[32:], unpadded):
            if not candidate:
                continue
            try:
                decoded = candidate.decode('utf-8').rstrip('\x00').strip()
                if decoded:
                    return decoded
            except Exception:
                pass

        raw_str = unpadded.decode('latin-1', errors='replace')
        m = _re.search(r'([A-Za-z0-9_\-]+\|\d{10}\|[A-Za-z0-9_\-]+)', raw_str)
        if m:
            return m.group(1)

        for i, b in enumerate(unpadded):
            if 0x20 <= b <= 0x7e:
                try:
                    return unpadded[i:].decode('utf-8', errors='replace').rstrip('\x00')
                except Exception:
                    pass
        return None

    @classmethod
    def _iter_profile_dbs(cls, browser_base: Path):
        if not browser_base.exists():
            return
        dbs = []
        for p in browser_base.iterdir():
            if not p.is_dir():
                continue
            if p.name == "Default" or p.name.startswith("Profile "):
                db = p / "Cookies"
                if db.exists():
                    dbs.append(db)
        dbs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        yield from dbs

    @classmethod
    def _read_cookies_from_db(cls, db_path: Path, host_patterns: tuple, order_case: str, key: bytes) -> Optional[dict]:
        import shutil, sqlite3
        tmp_file = tempfile.NamedTemporaryFile(prefix="tokenpua_", suffix=".db", delete=False)
        tmp_file.close()
        tmp = Path(tmp_file.name)
        try:
            shutil.copy2(db_path, tmp)
            conn = sqlite3.connect(tmp)
            where_parts = " OR ".join("host_key LIKE ?" for _ in host_patterns)
            rows = conn.execute(
                f"""SELECT host_key, name, value, encrypted_value FROM cookies
                    WHERE {where_parts}
                    ORDER BY {order_case}, last_access_utc DESC""",
                host_patterns,
            ).fetchall()
            conn.close()
        except Exception:
            return None
        finally:
            try:
                tmp.unlink()
            except Exception:
                pass

        cookies = {}
        seen = set()
        for _, name, value, enc in rows:
            if name in seen:
                continue
            seen.add(name)
            val = ""
            if isinstance(value, str):
                val = value.strip()
            elif isinstance(value, bytes):
                val = value.decode('utf-8', errors='replace').strip()
            if not val and enc:
                val = cls._decrypt(enc, key)
            if val:
                cookies[name] = val
        return cookies if cookies else None

    @classmethod
    def extract_cc(cls, validate: bool = True) -> Optional[str]:
        """从浏览器 Cookie DB 提取 CC (tokens.woa.com) cookie。"""
        for safe_storage_service, browser_base in cls.BROWSERS:
            key = cls._get_safe_storage_key(safe_storage_service)
            if not key:
                continue
            for db_path in cls._iter_profile_dbs(browser_base):
                cookies = cls._read_cookies_from_db(
                    db_path, cls.CC_HOST_PATTERNS, cls.CC_ORDER_CASE, key,
                )
                if not cookies:
                    continue
                candidate = "; ".join(f"{k}={v}" for k, v in cookies.items())
                if validate:
                    if CCClient.is_cookie_valid(candidate):
                        return candidate
                else:
                    return candidate
        return None

    @classmethod
    def extract_cb(cls, validate: bool = True) -> Optional[str]:
        """从浏览器 Cookie DB 提取 CB (codebuddy.cn) cookie。"""
        for safe_storage_service, browser_base in cls.BROWSERS:
            key = cls._get_safe_storage_key(safe_storage_service)
            if not key:
                continue
            for db_path in cls._iter_profile_dbs(browser_base):
                cookies = cls._read_cookies_from_db(
                    db_path, cls.CB_HOST_PATTERNS,
                    """CASE
                        WHEN host_key LIKE '%tencent.sso.codebuddy.cn%' THEN 0
                        WHEN host_key LIKE '%codebuddy.cn%' THEN 1
                        ELSE 9
                      END""",
                    key,
                )
                if not cookies:
                    continue
                if 'session' not in cookies:
                    continue
                ordered = [n for n in cls.CB_PREFERRED_NAMES if n in cookies]
                ordered.extend(n for n in cookies.keys() if n not in cls.CB_PREFERRED_NAMES)
                candidate = "; ".join(f"{n}={cookies[n]}" for n in ordered)
                if validate:
                    if CBClient.is_cookie_valid(candidate):
                        return candidate
                else:
                    return candidate
        return None


# ─── Module: ApiResult ────────────────────────────────────
@dataclass
class ApiResult:
    """统一 API 响应。"""
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None  # AUTH_EXPIRED | NETWORK_ERROR | PARSE_ERROR | TAB_MISSING | TIMEOUT


# ─── Module: CCClient ────────────────────────────────────
class CCClient:
    """CC (tokens.woa.com) API 客户端 — HTTP GET + Cookie。"""

    @classmethod
    def _api_get(cls, path: str, cookie: str) -> ApiResult:
        url = f"{BASE_URL}{path}"
        req = urllib.request.Request(url)
        req.add_header("Cookie", cookie)
        req.add_header("User-Agent", "TokenPUA/2.0")
        try:
            with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
                if resp.status == 200:
                    body = resp.read().decode()
                    if body.strip().startswith("<!") or body.strip().startswith("<html"):
                        return ApiResult(False, error="AUTH_EXPIRED")
                    return ApiResult(True, data=json.loads(body))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return ApiResult(False, error="AUTH_EXPIRED")
        except json.JSONDecodeError:
            return ApiResult(False, error="PARSE_ERROR")
        except Exception:
            pass
        return ApiResult(False, error="NETWORK_ERROR")

    @classmethod
    def fetch_usage_summary(cls, cookie: str) -> ApiResult:
        today = date.today()
        start = today.replace(day=1).isoformat()
        end = today.isoformat()
        path = (f"/api/usage-summary?start_date={start}&end_date={end}"
                f"&dimension=personal&platform={PLATFORMS}")
        return cls._api_get(path, cookie)

    @classmethod
    def fetch_today_usage(cls, cookie: str) -> ApiResult:
        today = date.today().isoformat()
        path = (f"/api/usage-summary?start_date={today}&end_date={today}"
                f"&dimension=personal&platform={PLATFORMS}")
        return cls._api_get(path, cookie)

    @classmethod
    def fetch_quota_allocation(cls, cookie: str) -> ApiResult:
        return cls._api_get("/api/quota-allocation", cookie)

    @classmethod
    def is_cookie_valid(cls, cookie: str) -> bool:
        today = date.today().isoformat()
        path = (f"/api/usage-summary?start_date={today}&end_date={today}"
                f"&dimension=personal&platform={PLATFORMS}")
        result = cls._api_get(path, cookie)
        return result.success and isinstance(result.data, dict) and isinstance(result.data.get("data"), list)


# ─── Module: CBClient ────────────────────────────────────
class CBClient:
    """CB (codebuddy.cn) API 客户端 — 优先浏览器 AppleScript XHR。"""

    @classmethod
    def _set_last_error(cls, err: Optional[str]):
        global LAST_CB_ERROR
        LAST_CB_ERROR = err

    @classmethod
    def _browser_xhr_post(cls, path: str, body_js: str = "'{}'",
                          retries: int = 1, open_if_missing: bool = False) -> Optional[tuple]:
        """通过 AppleScript 在浏览器内执行同步 XHR POST（Edge → Chrome）。"""
        cls._set_last_error(None)

        js = (
            "var xhr=new XMLHttpRequest();"
            f"xhr.open('POST','{path}',false);"
            "xhr.setRequestHeader('Content-Type','application/json');"
            f"xhr.setRequestHeader('x-enterprise-id','{CB_ENTERPRISE_ID}');"
            f"xhr.send({body_js});"
            "xhr.status+'|'+xhr.responseText;"
        )

        missing_tab_script = (
            '    if targetTab is missing value then\n'
            '        if (count of windows) is 0 then\n'
            '            make new window\n'
            '        end if\n'
            f'        set targetTab to make new tab at end of tabs of window 1 with properties {{URL:"https://tencent.sso.codebuddy.cn/profile/usage"}}\n'
            '        delay 2\n'
            '    end if\n'
        ) if open_if_missing else (
            '    if targetTab is missing value then\n'
            '        return "TAB_MISSING|"\n'
            '    end if\n'
        )

        for app_name in ("Microsoft Edge", "Google Chrome"):
            applescript = (
                f'tell application "{app_name}"\n'
                '    set targetTab to missing value\n'
                '    repeat with w in windows\n'
                '        repeat with t in tabs of w\n'
                '            if URL of t contains "codebuddy.cn" then\n'
                '                set targetTab to t\n'
                '                exit repeat\n'
                '            end if\n'
                '        end repeat\n'
                '        if targetTab is not missing value then exit repeat\n'
                '    end repeat\n'
                + missing_tab_script +
                f'    return execute targetTab javascript {json.dumps(js)}\n'
                'end tell'
            )

            for attempt in range(retries + 1):
                tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.scpt', delete=False)
                tmp.write(applescript)
                tmp.close()
                try:
                    result = subprocess.run(
                        ["osascript", tmp.name],
                        capture_output=True, text=True, timeout=8,
                    )
                    if result.returncode != 0:
                        err_text = (result.stderr or "").strip()
                        if ("AppleScript 执行 JavaScript 的功能已关闭" in err_text
                                or "Allow JavaScript from Apple Events" in err_text):
                            cls._set_last_error("BROWSER_JS_DISABLED")
                        else:
                            cls._set_last_error("BROWSER_SCRIPT_FAILED")
                        break

                    output = result.stdout.strip()
                    if not output:
                        if attempt < retries:
                            time.sleep(1.0)
                            continue
                        cls._set_last_error("BROWSER_EMPTY_RESULT")
                        break

                    status, _, body = output.partition("|")
                    status = status.strip()
                    if status == "TAB_MISSING":
                        cls._set_last_error("BROWSER_TAB_MISSING")
                        break
                    if status in ("401", "403"):
                        if attempt < retries:
                            time.sleep(1.5)
                            continue
                        cls._set_last_error(None)
                        return ("AUTH_EXPIRED", None)

                    cls._set_last_error(None)
                    return (status, body)
                except subprocess.TimeoutExpired:
                    # 超时不阻断，继续尝试下一个浏览器
                    cls._set_last_error("BROWSER_TIMEOUT")
                    # 不 break，让外层 for 继续下一个浏览器
                    # 但要跳出内层 retry 循环
                    break
                except Exception:
                    cls._set_last_error("BROWSER_SCRIPT_FAILED")
                    break
                finally:
                    try:
                        os.unlink(tmp.name)
                    except Exception:
                        pass
        return None

    @classmethod
    def fetch_quota_via_xhr(cls, open_if_missing: bool = False) -> ApiResult:
        result = cls._browser_xhr_post(
            "/billing/meter/get-enterprise-user-usage", "'{}'",
            retries=1, open_if_missing=open_if_missing,
        )
        if result is None:
            return ApiResult(False, error="NETWORK_ERROR")
        status, body = result
        if status == "AUTH_EXPIRED":
            return ApiResult(False, error="AUTH_EXPIRED")
        try:
            data = json.loads(body)
            if data.get("code") == 0:
                return ApiResult(True, data=data.get("data", {}))
        except Exception:
            pass
        return ApiResult(False, error="PARSE_ERROR")

    @classmethod
    def fetch_daily_usage_via_xhr(cls, open_if_missing: bool = False) -> ApiResult:
        today = date.today()
        start = today.strftime("%Y-%m-%d 00:00:00")
        end = today.strftime("%Y-%m-%d 23:59:59")
        body_js = f"JSON.stringify({{startTime:'{start}',endTime:'{end}',pageNum:1,pageSize:10}})"
        result = cls._browser_xhr_post(
            "/billing/meter/get-user-daily-usage", body_js,
            retries=1, open_if_missing=open_if_missing,
        )
        if result is None:
            return ApiResult(False, error="NETWORK_ERROR")
        status, body = result
        if status == "AUTH_EXPIRED":
            return ApiResult(False, error="AUTH_EXPIRED")
        try:
            data = json.loads(body)
            if data.get("code") == 0:
                records = data.get("data", {}).get("data", [])
                total_credit = sum(float(r.get("credit", 0)) for r in records)
                return ApiResult(True, data={"daily_credit": int(total_credit)})
        except Exception:
            pass
        return ApiResult(False, error="PARSE_ERROR")

    @classmethod
    def is_cookie_valid(cls, cookie: str) -> bool:
        url = f"{CB_BASE_URL}/billing/meter/get-enterprise-user-usage"
        req = urllib.request.Request(url, data=b"{}", method="POST")
        req.add_header("Cookie", cookie)
        req.add_header("Content-Type", "application/json")
        req.add_header("x-enterprise-id", CB_ENTERPRISE_ID)
        req.add_header("Referer", f"{CB_BASE_URL}/profile/usage")
        req.add_header("Origin", CB_BASE_URL)
        req.add_header("User-Agent", "Mozilla/5.0")
        try:
            with urllib.request.urlopen(req, timeout=8, context=SSL_CTX) as resp:
                data = json.loads(resp.read().decode())
                return data.get("code") == 0 and isinstance(data.get("data"), dict)
        except Exception:
            return False


# ─── Module: AuthManager ─────────────────────────────────
class AuthManager:
    """认证流程编排：自动登录、刷新、重试。"""

    CC_LOGIN_URL = "https://tokens.woa.com/?product=codebuddy"
    CB_LOGIN_URL = "https://tencent.sso.codebuddy.cn/profile/usage"

    @classmethod
    def ensure_cc(cls) -> Optional[str]:
        """确保 CC 认证可用。返回有效 cookie 或 None。"""
        cookie = CredStore.get_cc()
        if cookie and CCClient.is_cookie_valid(cookie):
            return cookie
        # 自动从浏览器刷新
        new_cookie = BrowserCookie.extract_cc(validate=True)
        if new_cookie:
            CredStore.set_cc(new_cookie)
            return new_cookie
        return None

    @classmethod
    def refresh_cc_on_expired(cls, cookie: str) -> Optional[str]:
        """CC API 返回 AUTH_EXPIRED 时，自动刷新 cookie 并重试一次。"""
        new_cookie = BrowserCookie.extract_cc(validate=False)
        if new_cookie and new_cookie != cookie:
            CredStore.set_cc(new_cookie)
            return new_cookie
        return None

    @classmethod
    def open_login_and_wait(cls, channel: str, timeout: int = 60) -> bool:
        """打开登录页并轮询等待认证成功。"""
        if channel == "cc":
            login_url = cls.CC_LOGIN_URL
        else:
            login_url = cls.CB_LOGIN_URL

        # 打开浏览器
        opened = False
        for cmd in (
            ["open", "-a", "Microsoft Edge", login_url],
            ["open", "-a", "Google Chrome", login_url],
            ["open", login_url],
        ):
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=5)
                if result.returncode == 0:
                    opened = True
                    break
            except Exception:
                continue

        if opened:
            time.sleep(2)

        # 轮询等待
        deadline = time.time() + timeout
        js_disabled_reported = False
        while time.time() < deadline:
            if channel == "cc":
                cookie = BrowserCookie.extract_cc(validate=True)
                if cookie:
                    CredStore.set_cc(cookie)
                    return True
            else:
                # CB: 尝试浏览器 XHR
                result = CBClient.fetch_quota_via_xhr(open_if_missing=False)
                if result.success:
                    # 顺带缓存 CB cookie
                    cb_cookie = BrowserCookie.extract_cb(validate=True)
                    if cb_cookie:
                        CredStore.set_cb(cb_cookie)
                    return True
                # 权限未开启则立即提示并退出，不无意义地重试
                if LAST_CB_ERROR == "BROWSER_JS_DISABLED":
                    if not js_disabled_reported:
                        js_disabled_reported = True
                        try:
                            subprocess.run(
                                ["osascript", "-e",
                                 'display dialog "请开启浏览器 AppleScript 权限后重试：\\n\\n'
                                 'Chrome: 菜单栏 → 视图 → 开发者 → 允许 Apple 事件中的 JavaScript\\n'
                                 'Edge: 菜单栏 → 视图 → 开发人员 → 允许 Apple 活动中的 JavaScript\\n\\n'
                                 '修改后需重启浏览器。" with title "TokenPUA" buttons {"知道了"} '
                                 'default button "知道了" with icon caution'],
                                capture_output=True, timeout=10,
                            )
                        except Exception:
                            pass
                    return False
            time.sleep(2)
        return False

    @classmethod
    def enable_browser_applescript(cls) -> None:
        """开启浏览器 AppleScript 权限（写 Preferences 文件）。"""
        browser_roots = (
            Path.home() / "Library/Application Support/Microsoft Edge",
            Path.home() / "Library/Application Support/Google/Chrome",
        )
        for root in browser_roots:
            try:
                if not root.exists():
                    continue
                for profile_dir in root.iterdir():
                    if not profile_dir.is_dir():
                        continue
                    pref_file = profile_dir / "Preferences"
                    if not pref_file.exists():
                        continue
                    try:
                        data = json.loads(pref_file.read_text())
                    except Exception:
                        continue
                    browser = data.setdefault("browser", {})
                    if browser.get("allow_javascript_apple_events") is True:
                        continue
                    browser["allow_javascript_apple_events"] = True
                    pref_file.write_text(json.dumps(data))
            except Exception:
                continue


# ─── Module: Pacing ───────────────────────────────────────
def count_workdays(start_date, end_date):
    count = 0
    d = start_date
    while d <= end_date:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count

def parse_cost(cost_str):
    try:
        return float(cost_str.replace("$", "").replace(",", ""))
    except (ValueError, AttributeError):
        return 0.0

def calculate_cc_pacing(cc_models, cc_budget=BUDGET):
    cc_budget = cc_budget if cc_budget and cc_budget > 0 else BUDGET

    today = date.today()
    month_start = today.replace(day=1)
    _, last_day = monthrange(today.year, today.month)
    month_end = today.replace(day=last_day)

    total_workdays = count_workdays(month_start, month_end)
    elapsed_workdays = count_workdays(month_start, today)
    remaining_workdays = total_workdays - elapsed_workdays

    spent = sum(parse_cost(model.get("cost", "$0")) for model in cc_models)
    ideal_spent = cc_budget * (elapsed_workdays / max(total_workdays, 1))
    gap = ideal_spent - spent
    daily_avg = spent / max(elapsed_workdays, 1)
    target_daily = (cc_budget - spent) / max(remaining_workdays, 1)
    projected = spent + daily_avg * remaining_workdays

    if daily_avg < 0.01:
        ratio = 999
    else:
        ratio = target_daily / daily_avg

    if ratio > 1.3:
        status_icon, status_text = "🟥", "加速!"
    elif ratio > 1.1:
        status_icon, status_text = "🟡", "稍加速"
    elif ratio > 0.9:
        status_icon, status_text = "🟢", "完美"
    elif ratio > 0.7:
        status_icon, status_text = "🟡", "可放缓"
    else:
        status_icon, status_text = "🔵", "省着用"

    diff_daily = target_daily - daily_avg
    if diff_daily > 0:
        advice = f"每工作日多用 ${diff_daily:.0f} 才能花完"
    elif diff_daily < -5:
        advice = f"每工作日可少用 ${-diff_daily:.0f}"
    else:
        advice = "保持当前节奏即可"

    last_5_warning = None
    if remaining_workdays <= 5 and (cc_budget - spent) > 100:
        remaining = cc_budget - spent
        last_5_warning = f"还剩 ${remaining:.0f}，{remaining_workdays} 个工作日，建议切 Opus 重度使用"

    return {
        "spent": spent, "budget": cc_budget, "pct": spent / cc_budget * 100,
        "ideal_spent": ideal_spent, "gap": gap,
        "daily_avg": daily_avg, "target_daily": target_daily,
        "projected": projected,
        "status_icon": status_icon, "status_text": status_text, "advice": advice,
        "last_5_warning": last_5_warning,
        "elapsed_workdays": elapsed_workdays,
        "total_workdays": total_workdays,
        "remaining_workdays": remaining_workdays,
    }


# ─── Module: UI ───────────────────────────────────────────
STATUS_COLORS = {"🟥": "#FF6B6B", "🟡": "#FFD93D", "🟢": "#6BCB77", "🔵": "#4D96FF"}

def get_status_color(cc_pacing):
    return STATUS_COLORS.get(cc_pacing.get("status_icon", "🟢"), "#FFFFFF")

def progress_bar_ansi(pct, width=20):
    filled = max(0, min(width, int(pct / 100 * width)))
    if pct > 90:
        fg = "\033[31m"
    elif pct > 70:
        fg = "\033[33m"
    else:
        fg = "\033[32m"
    dim = "\033[90m"
    reset = "\033[0m"
    return f"{fg}{'█' * filled}{dim}{'░' * (width - filled)}{reset}"

def _display_width(text):
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)

def render_no_cookie():
    _dir = os.path.dirname(os.path.abspath(__file__))
    _py = sys.executable or "/usr/bin/python3"
    login_action = f"bash={_py} param1={_dir}/tokens.3m.py param2=--auto-login param3=cc terminal=false"
    print("⚠️ TokenPUA: 需要登录 | color=#FF6B6B")
    print("---")
    print(f"🔑 点击登录 CC (tokens.woa.com) | {login_action}")

def render_auth_expired():
    _dir = os.path.dirname(os.path.abspath(__file__))
    _py = sys.executable or "/usr/bin/python3"
    login_action = f"bash={_py} param1={_dir}/tokens.3m.py param2=--auto-login param3=cc terminal=false"
    print("⚠️ TokenPUA: CC Cookie 已过期 | color=#FF6B6B")
    print("---")
    print(f"🔑 点击登录 CC (tokens.woa.com) | {login_action}")

def render_error(detail=""):
    print("❌ TokenPUA: 请求失败 | color=#FF6B6B")
    print("---")
    print("API 请求失败，请检查网络 | color=#999999 bash=/usr/bin/true terminal=false")
    if detail:
        print(f"{detail} | color=#999999 size=10 bash=/usr/bin/true terminal=false")

def render_dashboard(cc_pacing, today_cc_models, cb_monthly_data=None, cb_daily_points=None, cb_helper_cache=None):
    now = datetime.now().strftime("%H:%M")
    NOOP = "bash=/usr/bin/true terminal=false"

    today = date.today()
    _, total_days = monthrange(today.year, today.month)
    elapsed_days = today.day
    time_pct = elapsed_days / total_days * 100

    cc_pct = cc_pacing['pct']
    cc_spent = cc_pacing['spent']
    cc_budget = cc_pacing['budget']

    cb_used_points = 0
    cb_limit_points = CB_TOKEN_LIMIT
    cb_pct = 0
    cb_available = False
    if cb_monthly_data and cb_monthly_data != "AUTH_EXPIRED":
        cb_used_points = int(cb_monthly_data.get("credit", 0))
        cb_limit_points = int(cb_monthly_data.get("limitNum", CB_TOKEN_LIMIT))
        cb_pct = cb_used_points / cb_limit_points * 100 if cb_limit_points else 0
        cb_available = True

    cb_used_usd = cb_used_points / CB_POINTS_PER_USD
    cb_limit_usd = cb_limit_points / CB_POINTS_PER_USD

    remaining_workdays = cc_pacing['remaining_workdays']
    daily_cc_target = (cc_budget - cc_spent) / max(remaining_workdays, 1)
    daily_cb_target_usd = (cb_limit_usd - cb_used_usd) / max(remaining_workdays, 1)

    today_cc_spent = sum(parse_cost(m.get("cost", "$0")) for m in today_cc_models)
    today_cb_usd = 0
    if cb_daily_points is not None and cb_daily_points != "AUTH_EXPIRED":
        today_cb_usd = cb_daily_points / CB_POINTS_PER_USD
    today_total_usd = today_cc_spent + today_cb_usd
    daily_total_usd = daily_cc_target + daily_cb_target_usd

    current_hour = datetime.now().hour
    current_minute = datetime.now().minute
    day_time_pct = (current_hour + current_minute / 60) / 24 * 100
    daily_cc_pct = today_cc_spent / max(daily_cc_target, 0.01) * 100 if daily_cc_target > 0 else 0

    # Menu bar title
    print(f"{cc_pacing['status_icon']} ${today_total_usd:.0f}/${daily_total_usd:.0f} · {cc_pacing['status_text']} | size=13")
    print("---")

    _dir = os.path.dirname(os.path.abspath(__file__))
    _py = sys.executable or "/usr/bin/python3"
    helper_script = Path(_dir) / "cb_helper.py"
    helper_ready = helper_script.exists()
    helper_log_path = CB_HELPER_STDERR_LOG if CB_HELPER_STDERR_LOG.exists() else CB_HELPER_STDOUT_LOG
    helper_log_ready = helper_log_path.exists()
    CB_HELPER_ACTION = (
        f"bash={_py} "
        f"param1={helper_script} "
        "param2=--interactive terminal=false refresh=true"
    )
    CB_HELPER_LOG_ACTION = (
        f"bash=/usr/bin/open param1={helper_log_path} terminal=false"
        if helper_log_ready else NOOP
    )
    helper_status, helper_stale, helper_age_text, helper_message = get_cb_helper_cache_meta(cb_helper_cache)

    # ══ 模块一：总额度 ══
    print(f"月额度（$1 = 100积分） | size=11 color=#888888 {NOOP}")
    label_time = "时间进度"
    label_cc = "CC进度 "
    label_cb = "CB进度 "

    bar_time = progress_bar_ansi(time_pct)
    print(f"{label_time}  {bar_time}  {time_pct:.0f}%  {elapsed_days}/{total_days}天 | ansi=true size=13 font=Menlo {NOOP}")
    bar_cc = progress_bar_ansi(cc_pct)
    print(f"{label_cc}  {bar_cc}  {cc_pct:.0f}%  ${cc_spent:.0f}/${cc_budget:.0f} | ansi=true size=13 font=Menlo {NOOP}")
    if cb_available:
        bar_cb = progress_bar_ansi(cb_pct)
        print(f"{label_cb}  {bar_cb}  {cb_pct:.0f}%  ${cb_used_usd:.0f}/${cb_limit_usd:.0f} | ansi=true size=13 font=Menlo {NOOP}")
        if helper_status == "ok":
            age_label = helper_age_text or "刚刚"
            if helper_stale and helper_ready:
                print(f"CB提示  helper缓存 {age_label} 前更新，后台刷新可能落后；点此手动刷新 | color=#FF9F1C {CB_HELPER_ACTION}")
            else:
                print(f"CB提示  helper缓存 {age_label} 前更新，后台刷新已启用 | color=#999999 {NOOP}")
        elif helper_status == "error" and helper_message:
            print(f"CB提示  helper 最近一次刷新失败：{helper_message} | color=#FF9F1C {NOOP}")
    else:
        if not helper_ready:
            print(f"{label_cb}  未部署 CB helper | color=#999999 {NOOP}")
        elif helper_status == "login_required":
            print(f"{label_cb}  首次登录 / 重新登录 | {CB_HELPER_ACTION}")
            if helper_message:
                print(f"CB提示  {helper_message} | color=#FF9F1C {NOOP}")
        elif helper_status == "error":
            print(f"{label_cb}  helper 抓取失败，点击修复 | {CB_HELPER_ACTION}")
            if helper_message:
                print(f"CB提示  {helper_message} | color=#FF6B6B {NOOP}")
        else:
            print(f"{label_cb}  首次登录 CB | {CB_HELPER_ACTION}")
            print(f"CB提示  安装完成后请先完成一次 CB 登录；随后会后台自动刷新 | color=#999999 {NOOP}")
    print("---")

    # ══ 模块二：日额度 ══
    print(f"日额度（{now}更新） | size=11 color=#888888 {NOOP}")
    bar_day_time = progress_bar_ansi(day_time_pct)
    print(f"{label_time}  {bar_day_time}  {day_time_pct:.0f}%  {current_hour:02d}:{current_minute:02d}/24:00 | ansi=true size=13 font=Menlo {NOOP}")
    bar_daily_cc = progress_bar_ansi(min(daily_cc_pct, 100))
    print(f"{label_cc}  {bar_daily_cc}  {daily_cc_pct:.0f}%  ${today_cc_spent:.0f}/${daily_cc_target:.0f} | ansi=true size=13 font=Menlo {NOOP}")
    if cb_available:
        if cb_daily_points is not None and cb_daily_points != "AUTH_EXPIRED":
            today_cb_usd = cb_daily_points / CB_POINTS_PER_USD
            daily_cb_pct = today_cb_usd / max(daily_cb_target_usd, 0.01) * 100 if daily_cb_target_usd > 0 else 0
            bar_daily_cb = progress_bar_ansi(min(daily_cb_pct, 100))
            print(f"{label_cb}  {bar_daily_cb}  {daily_cb_pct:.0f}%  ${today_cb_usd:.0f}/${daily_cb_target_usd:.0f} | ansi=true size=13 font=Menlo {NOOP}")
        else:
            print(f"{label_cb}  —  /${daily_cb_target_usd:.0f} | color=#999999 {NOOP}")
    else:
        if not helper_ready:
            print(f"{label_cb}  未部署 CB helper | color=#999999 {NOOP}")
        elif helper_status == "login_required":
            print(f"{label_cb}  等待浏览器登录完成 | {CB_HELPER_ACTION}")
        elif helper_status == "error":
            print(f"{label_cb}  helper 失败，点击修复 | {CB_HELPER_ACTION}")
        else:
            print(f"{label_cb}  首次登录后自动刷新 | {CB_HELPER_ACTION}")
    print("---")
    print(f"立即刷新 CB 数据 | {CB_HELPER_ACTION}")
    if helper_log_ready:
        print(f"打开 CB helper 日志 | {CB_HELPER_LOG_ACTION}")
    else:
        print(f"CB helper 日志暂不可用 | color=#999999 {NOOP}")
    print("打开 CC Token 看板 | href=https://tokens.woa.com/?product=codebuddy")
    print("打开 CB Token 看板 | href=https://tencent.sso.codebuddy.cn/profile/usage")


# ─── Data cache ───────────────────────────────────────────
def save_cache(data: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(data))
    except Exception:
        pass

def load_cache() -> Optional[dict]:
    try:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text())
    except Exception:
        pass
    return None


def load_cb_helper_cache() -> Optional[dict]:
    try:
        if CB_HELPER_CACHE_FILE.exists():
            return json.loads(CB_HELPER_CACHE_FILE.read_text())
    except Exception:
        pass
    return None


def get_cb_helper_cache_meta(cache: Optional[dict]) -> tuple[str, bool, str, str]:
    if not cache:
        return "missing", True, "", ""

    status = cache.get("status") or "unknown"
    message = cache.get("message") or ""
    fetched_at = cache.get("fetched_at") or ""
    if not fetched_at:
        return status, True, "", message

    try:
        fetched_dt = datetime.fromisoformat(fetched_at)
        age_seconds = max(0, int((datetime.now() - fetched_dt).total_seconds()))
        stale = age_seconds > CB_HELPER_CACHE_TTL_SECONDS
        if age_seconds >= 3600:
            age_text = f"{age_seconds // 3600}h"
        elif age_seconds >= 60:
            age_text = f"{age_seconds // 60}m"
        else:
            age_text = f"{age_seconds}s"
        return status, stale, age_text, message
    except Exception:
        return status, True, "", message


def run_cb_helper(interactive: bool = False) -> bool:
    helper_script = Path(__file__).with_name("cb_helper.py")
    if not helper_script.exists():
        return False

    cmd = [sys.executable or "/usr/bin/python3", str(helper_script)]
    if interactive:
        cmd.append("--interactive")

    try:
        subprocess.run(cmd, capture_output=True, timeout=180)
        return True
    except Exception:
        return False


# ─── Main ─────────────────────────────────────────────────
def main():
    # ── CC 认证 ──
    cookie = AuthManager.ensure_cc()
    if not cookie:
        # 尝试从旧 cookie 文件（Keychain 时代兼容）迁移
        old_file = CONFIG_DIR / "cookie"
        if old_file.exists():
            try:
                old_cookie = old_file.read_text().strip()
                if old_cookie and CCClient.is_cookie_valid(old_cookie):
                    CredStore.set_cc(old_cookie)
                    cookie = old_cookie
                    # 清理旧文件
                    try:
                        old_file.unlink()
                    except Exception:
                        pass
            except Exception:
                pass
        if not cookie:
            render_no_cookie()
            return

    # ── CC 数据 ──
    cc_summary_result = CCClient.fetch_usage_summary(cookie)
    if cc_summary_result.error == "AUTH_EXPIRED":
        new_cookie = AuthManager.refresh_cc_on_expired(cookie)
        if new_cookie:
            cookie = new_cookie
            cc_summary_result = CCClient.fetch_usage_summary(cookie)
        if cc_summary_result.error == "AUTH_EXPIRED":
            render_auth_expired()
            return
    if not cc_summary_result.success:
        # 尝试显示缓存
        cache = load_cache()
        if cache:
            render_error(f"网络异常，显示 {cache.get('time', '?')} 缓存")
        else:
            render_error("usage-summary 返回错误")
        return

    cc_models = cc_summary_result.data.get("data", [])
    if not cc_models:
        render_error(f"data 为空, keys={list(cc_summary_result.data.keys())}")
        return

    # ── CC 今日 ──
    today_cc_result = CCClient.fetch_today_usage(cookie)
    today_cc_models = today_cc_result.data.get("data", []) if today_cc_result.success else []

    # ── CC 总额度 ──
    cc_total_budget = BUDGET
    cc_quota_result = CCClient.fetch_quota_allocation(cookie)
    if cc_quota_result.success and isinstance(cc_quota_result.data, dict):
        cc_quota_data = cc_quota_result.data.get("data") or {}
        try:
            total_quota_cost = float(cc_quota_data.get("total_quota_cost", 0) or 0)
        except (TypeError, ValueError):
            total_quota_cost = 0
        if total_quota_cost > 0:
            cc_total_budget = total_quota_cost

    # ── CB helper cache ──
    cb_helper_cache = load_cb_helper_cache()
    cb_monthly_data = None
    cb_daily_points = None
    if cb_helper_cache and cb_helper_cache.get("status") == "ok":
        cb_monthly_data = {
            "credit": cb_helper_cache.get("monthly_credit") or 0,
            "limitNum": cb_helper_cache.get("monthly_limit") or CB_TOKEN_LIMIT,
        }
        if cb_helper_cache.get("daily_credit") is not None:
            cb_daily_points = cb_helper_cache.get("daily_credit")

    # ── 计算 & 渲染 ──
    cc_pacing = calculate_cc_pacing(cc_models, cc_budget=cc_total_budget)
    render_dashboard(cc_pacing, today_cc_models, cb_monthly_data, cb_daily_points, cb_helper_cache=cb_helper_cache)

    # 保存缓存
    save_cache({
        "time": datetime.now().strftime("%H:%M"),
        "pacing": cc_pacing,
    })


def handle_setup():
    """初始化引导（install.sh 调用）。"""
    print("TokenPUA 初始化...")
    AuthManager.enable_browser_applescript()

    # CC
    print("正在打开 CC 登录页 (tokens.woa.com)...")
    cc_ok = AuthManager.open_login_and_wait("cc", timeout=60)
    if cc_ok:
        print("✅ CC 认证成功")
    else:
        print("⚠️ CC 登录超时，可在菜单栏中手动登录")

    print("ℹ️ CB 已切换为 helper + 后台刷新模式，安装脚本会继续初始化 CB helper")

    # 刷新 SwiftBar
    try:
        subprocess.run(
            ["open", "swiftbar://refreshplugin?name=tokens"],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass
    print("初始化完成")


def handle_auto_login(channel: str = "all"):
    """单渠道登录刷新（菜单点击调用）。"""
    AuthManager.enable_browser_applescript()

    if channel in ("cc", "all"):
        AuthManager.open_login_and_wait("cc", timeout=60)
    if channel in ("cb", "all"):
        run_cb_helper(interactive=True)

    try:
        subprocess.run(
            ["open", "swiftbar://refreshplugin?name=tokens"],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            arg = sys.argv[1]
            if arg == "--setup":
                handle_setup()
                sys.exit(0)
            elif arg == "--auto-login":
                ch = sys.argv[2] if len(sys.argv) > 2 else "all"
                handle_auto_login(ch)
                sys.exit(0)
            elif arg == "--cb-login-refresh":
                # 兼容旧菜单项
                handle_auto_login("cb")
                sys.exit(0)
        main()
    except Exception as e:
        print(f"❌ TokenPUA Error | color=#FF6B6B")
        print("---")
        print(f"{type(e).__name__}: {e} | color=#FF6B6B size=10 trim=false")
        print("🔄 刷新 | refresh=true")
