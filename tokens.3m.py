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
import os
import ssl
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from calendar import monthrange
from pathlib import Path

# ─── SSL ─────────────────────────────────────
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# ─── Config ───────────────────────────────────
BASE_URL   = "https://token.woa.com"
PLATFORMS = "all"
DASHBOARD_URL = "https://token.woa.com/?product=codebuddy"

CONFIG_DIR   = Path.home() / ".config" / "tokens-woa"
COOKIE_FILE = CONFIG_DIR / "cc_cookie"
CACHE_FILE  = CONFIG_DIR / "cache.json"

# ─── CredStore ───────────────────────────────
def cred_read(path):
    try:
        if path.exists():
            v = path.read_text().strip()
            return v if v else None
    except Exception:
        pass
    return None

def cred_write(path, value):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        os.chmod(path, 0o600)
    except Exception:
        pass

def get_cookie():
    return cred_read(COOKIE_FILE)

def set_cookie(cookie):
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
        try:
            r = subprocess.run(
                ["security", "find-generic-password", "-w", "-s", service],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode != 0 or not r.stdout.strip():
                return None
            pwd = r.stdout.strip().encode("utf-8")
            key = hashlib.pbkdf2_hmac("sha1", pwd, b"saltysalt", 1003, dklen=16)
            cls._key_cache[service] = key
            return key
        except Exception:
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
        iv = b" " * 16
        dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        raw = dec.update(payload) + dec.finalize()
        pad_len = raw[-1]
        unpadded = raw[:-pad_len] if 1 <= pad_len <= 16 else raw
        for candidate in (unpadded[32:], unpadded):
            if not candidate:
                continue
            try:
                decoded = candidate.decode("utf-8").rstrip("\x00").strip()
                if decoded:
                    return decoded
            except Exception:
                pass
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
        except Exception:
            return None
        finally:
            try:
                Path(tmp).unlink()
            except Exception:
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
    def extract(cls, validate=True):
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
        except Exception:
            return False

# ─── ApiClient ────────────────────────────────
import urllib.request
import urllib.error

class ApiClient:
    @classmethod
    def _get(cls, path, cookie):
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
        except Exception:
            pass
        return False, None, "NETWORK_ERROR"

    @classmethod
    def fetch_quota(cls, cookie, platform="codebuddy"):
        return cls._get(f"/api/query-quota?platform={platform}", cookie)

    @classmethod
    def fetch_usage_summary(cls, cookie, start, end):
        path = (f"/api/usage-summary?start_date={start}&end_date={end}"
                f"&dimension=personal&platform={PLATFORMS}")
        return cls._get(path, cookie)

    @classmethod
    def fetch_usage_details(cls, cookie, start, end, page=1):
        path = (f"/api/usage-details?start_date={start}&end_date={end}"
                f"&dimension=all&page={page}&page_size=50&platform=all")
        return cls._get(path, cookie)

    @classmethod
    def fetch_recent_high_cost(cls, cookie, days=7, min_cost=0.001, limit=50):
        """获取最近 N 天消费大于指定金额的记录"""
        records = []
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        for page in range(1, 10):  # 最多抓 9 页
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
    def ensure(cls):
        cookie = get_cookie()
        if cookie and cls._is_valid(cookie):
            return cookie
        new_cookie = BrowserCookie.extract(validate=True)
        if new_cookie:
            set_cookie(new_cookie)
            return new_cookie
        return None

    @classmethod
    def refresh(cls, old_cookie):
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
    def open_login_and_wait(cls, timeout=60):
        for cmd in (
            ["open", "-a", "Microsoft Edge", cls.LOGIN_URL],
            ["open", "-a", "Google Chrome", cls.LOGIN_URL],
            ["open", cls.LOGIN_URL],
        ):
            try:
                if subprocess.run(cmd, capture_output=True, timeout=5).returncode == 0:
                    break
            except Exception:
                continue
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
def count_workdays(start, end):
    d = start
    n = 0
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n

def calc_pacing(spent, budget, remaining_wd):
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
    if remaining_wd <= 5 and (budget - spent) > 100:
        warning = (f"还剩 ¥{budget - spent:.0f}，仅剩 {remaining_wd} 个工作日，建议多用 Opus")

    return dict(
        spent=spent, budget=budget,
        pct=spent / budget * 100 if budget else 0,
        daily_quota=daily_quota,
        status_icon=icon, status_text=text,
        warning=warning,
        remaining_wd=remaining_wd,
    )

# ─── UI ─────────────────────────────────────
BAR_WIDTH = 18

def ansi_bar(pct, width=BAR_WIDTH):
    filled = max(0, min(width, int(pct / 100 * width)))
    if pct > 90:
        fg = "\033[31m"
    elif pct > 70:
        fg = "\033[33m"
    else:
        fg = "\033[32m"
    return f"{fg}{'█' * filled}\033[90m{'░' * (width - filled)}\033[0m"

def render_no_cookie():
    _dir = os.path.dirname(os.path.abspath(__file__))
    _py = sys.executable or "/usr/bin/python3"
    action = f"bash={_py} param1={_dir}/tokens.3m.py param2=--login terminal=false"
    print("\u26a0\ufe0f TokenPUA: 需要登录 | color=#FF6B6B")
    print("---")
    print(f"\U0001f512 点击登录 | {action}")

def render_auth_expired():
    _dir = os.path.dirname(os.path.abspath(__file__))
    _py = sys.executable or "/usr/bin/python3"
    action = f"bash={_py} param1={_dir}/tokens.3m.py param2=--login terminal=false"
    print("\u26a0\ufe0f TokenPUA: 登录已过期 | color=#FF6B6B")
    print("---")
    print(f"\U0001f512 点击重新登录 | {action}")

def render_error(msg):
    print("\u274c TokenPUA: 请求失败 | color=#FF6B6B")
    print("---")
    print(f"{msg} | color=#999999 size=11 bash=/usr/bin/true terminal=false")

def render(pacing, today_used):
    NOOP = "bash=/usr/bin/true terminal=false"
    spent  = pacing["spent"]
    budget = pacing["budget"]
    pct    = pacing["pct"]
    daily_q = pacing["daily_quota"]
    rem_wd = pacing["remaining_wd"]

    # menu bar title
    print(f"{pacing['status_icon']} ¥{spent:.0f}/¥{budget:.0f} · {pacing['status_text']} | size=13")
    print("---")

    # ── month progress ──────────────────
    print("月进度 | size=11 color=#888888")
    today = date.today()
    _, total_days = monthrange(today.year, today.month)
    month_time_pct = today.day / total_days * 100
    bq = ansi_bar(pct)
    print(f" 额度  {bq}  {pct:.0f}%  ¥{spent:.0f}/¥{budget:.0f} | ansi=true size=12 font=Menlo {NOOP}")
    bt = ansi_bar(month_time_pct)
    print(f" 时间  {bt}  {month_time_pct:.0f}%  {today.day}/{total_days}天 | ansi=true size=12 font=Menlo {NOOP}")
    print("---")

    # ── day progress ─────────────────────
    print("日进度 | size=11 color=#888888")
    now = datetime.now()
    day_time_pct = (now.hour * 60 + now.minute) / 1440 * 100
    day_pct = (today_used / daily_q * 100) if daily_q > 0 else 0
    bdq = ansi_bar(min(day_pct, 100))
    print(f" 额度  {bdq}  {day_pct:.0f}%  ¥{today_used:.1f}/¥{daily_q:.0f} | ansi=true size=12 font=Menlo {NOOP}")
    bdt = ansi_bar(day_time_pct)
    print(f" 时间  {bdt}  {day_time_pct:.0f}%  {now.hour:02d}:{now.minute:02d}/24:00 | ansi=true size=12 font=Menlo {NOOP}")

def render_with_records(pacing, today_used, records):
    NOOP = "bash=/usr/bin/true terminal=false"
    render(pacing, today_used)
    if not records:
        return
    print("---")
    print("近期消费记录 | size=11 color=#888888")
    for rec in records:
        # 格式：时间 金额 模型 用户输入 token（列间隔2空格）
        time_str = rec["time"][5:16] if len(rec["time"]) >= 16 else rec["time"]  # MM-DD HH:MM
        model = rec["model"][:15] if len(rec["model"]) > 15 else rec["model"]
        cost = rec["cost"]
        tokens = rec["total_tokens"]
        user_input = (rec["user_input"] or "")[:30].replace("\n", " ").replace("\r", "")
        cost_str = f"¥{cost:.2f}"
        line = f"{time_str:<8}  {cost_str:<6}  {model:<15}  {tokens:>12,}  {user_input:<30}"
        color_param = " color=#666666" if cost == 0 else ""
        print(f"{line} | size=10 font=Menlo {NOOP}{color_param}")

    # ── bottom hints ──────────────────
    if pacing.get("warning"):
        print("---")
        print(f"\u26a0\ufe0f {pacing['warning']} | size=11 color=#FF6B6B {NOOP}")

    # refresh button (left) + update time (right) same line
    print("---")
    print(f"打开 Token 看板 | href={DASHBOARD_URL} | size=11")
    # 时间对比：只比较 hour:minute，忽略日期（避免 strptime 默认 1900 年问题）
    cache = load_cache()
    last_time = cache.get("time", "") if cache else ""
    if last_time and " " in last_time:
        try:
            # 提取 time 部分 "HH:MM" 进行比较
            time_part = last_time.split(" ")[1] if " " in last_time else last_time
            last_h, last_m = map(int, time_part.split(":"))
            now_h = datetime.now().hour
            now_m = datetime.now().minute
            diff_min = (now_h * 60 + now_m) - (last_h * 60 + last_m)
            # 处理跨午夜的情况（虽然不太可能在这个场景）
            if diff_min < 0:
                diff_min += 1440
            if diff_min == 0:
                time_label = "刚刚更新"
            elif diff_min < 60:
                time_label = f"{diff_min}分钟前更新"
            else:
                time_label = f"{diff_min // 60}小时前更新"
        except Exception:
            time_label = f"{last_time} 更新"
    else:
        time_label = "刚刚更新"
    print(f"刷新 | refresh=true | length=80")
    print(f"{time_label} | color=#888888 size=11")

# ─── Cache ──────────────────────────────────
def save_cache(data):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False))
    except Exception:
        pass

def load_cache():
    try:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text())
    except Exception:
        pass
    return None

# ─── Main ─────────────────────────────────────
def main():
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
    today = date.today().isoformat()
    _, details, _ = ApiClient.fetch_usage_details(cookie, today, today)
    today_used = 0.0
    if details and isinstance(details.get("data"), list):
        for rec in details["data"]:
            try:
                c = str(rec.get("cost", "0")).replace("¥", "").replace(",", "")
                today_used += float(c)
            except (ValueError, TypeError):
                pass

    # remaining workdays
    _, total_days = monthrange(date.today().year, date.today().month)
    month_end = date.today().replace(day=total_days)
    remaining_wd = count_workdays(date.today(), month_end)

    # 近期高消费记录
    records = ApiClient.fetch_recent_high_cost(cookie, days=7, min_cost=0, limit=50)

    pacing = calc_pacing(total_used, total_quota, remaining_wd)
    render_with_records(pacing, today_used, records)
    save_cache({"time": datetime.now().strftime("%m-%d %H:%M"), "spent": total_used})

def handle_login():
    print("TokenPUA 登录中...")
    if AuthManager.open_login_and_wait(timeout=60):
        print("成功")
    else:
        print("超时，请从菜单重试")
    try:
        subprocess.run(["open", "swiftbar://refreshplugin?name=tokens"],
                       capture_output=True, timeout=5)
    except Exception:
        pass

if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--login":
            handle_login()
            sys.exit(0)
        main()
    except Exception as e:
        print(f"\u274c TokenPUA 错误 | color=#FF6B6B")
        print("---")
        print(f"{type(e).__name__}: {e} | color=#FF6B6B size=10")
        print("\U0001f504 刷新 | refresh=true")
