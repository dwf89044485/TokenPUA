#!/opt/homebrew/bin/python3
# <xbar.title>TokenPUA</xbar.title>
# <xbar.desc>Monthly token usage burndown predictor for tokens.woa.com</xbar.desc>
# <xbar.version>1.0</xbar.version>
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
import ssl
import subprocess
import sys
import urllib.request
import urllib.error
import unicodedata
from datetime import date, datetime, timedelta
from calendar import monthrange
from pathlib import Path

# ─── SSL: 内网服务，跳过证书验证 ─────────────────────────
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# ─── Config ───────────────────────────────────────────────
BASE_URL = "https://tokens-nbyxw43y.app.with.woa.com"
PLATFORMS = "codebuddy,with,codebuddy-code,codebuddy-cli,codex-internal,xcode"
BUDGET = 1000.0
KEYCHAIN_SERVICE = "tokens-woa"
KEYCHAIN_ACCOUNT = "cookie"
DASHBOARD_URL = "https://tokens.woa.com/?product=codebuddy"
COOKIE_FILE = Path.home() / ".config" / "tokens-woa" / "cookie"

# ─── Codebuddy (tencent.sso) Config ───────────────────────
CB_BASE_URL = "https://tencent.sso.codebuddy.cn"
CB_ENTERPRISE_ID = "etahzsqej0n4"
CB_COOKIE_FILE = Path.home() / ".config" / "tokens-woa" / "cb_cookie"
CB_TOKEN_LIMIT = 150000  # 月度积分上限
CB_POINTS_PER_USD = 100.0

# ─── Cookie helpers (Keychain primary, file fallback) ─────
def get_cookie():
    """Read cookie: try Keychain first, fall back to file."""
    # Try Keychain
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
             "-a", KEYCHAIN_ACCOUNT, "-w"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    # Fallback: config file
    try:
        if COOKIE_FILE.exists():
            cookie = COOKIE_FILE.read_text().strip()
            if cookie:
                return cookie
    except Exception:
        pass
    return None

def set_cookie(cookie_value):
    """Store cookie in both Keychain and file."""
    # Keychain
    try:
        subprocess.run(
            ["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE,
             "-a", KEYCHAIN_ACCOUNT],
            capture_output=True, timeout=5
        )
        subprocess.run(
            ["security", "add-generic-password", "-s", KEYCHAIN_SERVICE,
             "-a", KEYCHAIN_ACCOUNT, "-w", cookie_value],
            capture_output=True, timeout=5
        )
    except Exception:
        pass
    # File fallback (chmod 600)
    try:
        COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        COOKIE_FILE.write_text(cookie_value)
        os.chmod(COOKIE_FILE, 0o600)
    except Exception:
        pass

# ─── API helpers ──────────────────────────────────────────
def _edge_xhr_get(url):
    """在 Edge 浏览器内执行同步 XHR GET，绕过 CORS/cookie 问题。
    需要对应域名的 tab 已打开，否则自动打开后等待加载。
    返回 JSON dict 或 'AUTH_EXPIRED' 或 None。"""
    # 从 URL 提取 origin 用于匹配 tab
    import re as _re
    m = _re.match(r'(https?://[^/]+)', url)
    origin = m.group(1) if m else url
    path = url[len(origin):]

    js = (
        f"var xhr=new XMLHttpRequest();"
        f"xhr.open('GET',{json.dumps(path)},false);"
        f"xhr.send(null);"
        f"xhr.status+'|'+xhr.responseText;"
    )
    applescript = f'''
tell application "Microsoft Edge"
    set targetTab to missing value
    repeat with w in windows
        repeat with t in tabs of w
            if URL of t starts with {json.dumps(origin)} then
                set targetTab to t
                exit repeat
            end if
        end repeat
        if targetTab is not missing value then exit repeat
    end repeat
    if targetTab is missing value then
        set targetTab to make new tab at end of tabs of window 1 with properties {{URL:{json.dumps(origin + "/")}}}
        delay 4
    end if
    return execute targetTab javascript {json.dumps(js)}
end tell
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return None
        output = result.stdout.strip()
        if not output:
            return None
        status, _, body = output.partition("|")
        if status.strip() in ("401", "403"):
            return "AUTH_EXPIRED"
        if body.strip().startswith("<!") or body.strip().startswith("<html"):
            return "AUTH_EXPIRED"
        return json.loads(body)
    except Exception:
        return None

def api_get(path, cookie):
    """GET request to tokens API. Try Edge browser first, fall back to HTTP."""
    url = f"{BASE_URL}{path}"
    # 跳过 Edge（超时卡死），直接 HTTP
    # 降级：直接 HTTP（需要有效 cookie）
    if not cookie:
        return None
    req = urllib.request.Request(url)
    req.add_header("Cookie", cookie)
    req.add_header("User-Agent", "TokenPUA/1.0")
    try:
        with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
            if resp.status == 200:
                body = resp.read().decode()
                if body.strip().startswith("<!") or body.strip().startswith("<html"):
                    return "AUTH_EXPIRED"
                return json.loads(body)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "AUTH_EXPIRED"
    except json.JSONDecodeError:
        return "AUTH_EXPIRED"
    except Exception:
        pass
    return None

def fetch_usage_summary(cookie):
    """Fetch per-model usage summary for current month."""
    today = date.today()
    start = today.replace(day=1).isoformat()
    end = today.isoformat()
    path = (f"/api/usage-summary?start_date={start}&end_date={end}"
            f"&dimension=personal&platform={PLATFORMS}")
    return api_get(path, cookie)

def fetch_today_usage(cookie):
    """Fetch per-model usage summary for today only."""
    today = date.today().isoformat()
    path = (f"/api/usage-summary?start_date={today}&end_date={today}"
            f"&dimension=personal&platform={PLATFORMS}")
    return api_get(path, cookie)

# ─── Codebuddy (tencent.sso) API ──────────────────────────
def _decrypt_edge_cookie(enc, key):
    """Decrypt a Chrome/Edge v10 AES-CBC encrypted cookie value."""
    import re as _re
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    if enc[:3] != b'v10':
        return enc.decode('utf-8', errors='replace')
    payload = enc[3:]
    iv = b' ' * 16
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    raw = dec.update(payload) + dec.finalize()
    pad_len = raw[-1]
    unpadded = raw[:-pad_len] if 1 <= pad_len <= 16 else raw
    raw_str = unpadded.decode('latin-1')
    # Session 格式: base64url|timestamp|base64url
    m = _re.search(r'([A-Za-z0-9_\-]+\|\d{10}\|[A-Za-z0-9_\-]+)', raw_str)
    if m:
        return m.group(1)
    # 其他 cookie：找第一个可打印字符
    for i, b in enumerate(unpadded):
        if 0x20 <= b <= 0x7e:
            try:
                return unpadded[i:].decode('utf-8').rstrip('\x00')
            except Exception:
                pass
    return None

def get_cb_cookie_from_browser():
    """从 Edge 浏览器 cookie 数据库自动读取 codebuddy session。"""
    import hashlib, shutil, sqlite3
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", "Microsoft Edge Safe Storage"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return None
        pwd = result.stdout.strip().encode('utf-8')
        key = hashlib.pbkdf2_hmac('sha1', pwd, b'saltysalt', 1003, dklen=16)

        db_path = Path.home() / "Library/Application Support/Microsoft Edge/Default/Cookies"
        if not db_path.exists():
            return None
        tmp = Path("/tmp/edge_cb_cookies.db")
        shutil.copy2(db_path, tmp)

        conn = sqlite3.connect(tmp)
        rows = conn.execute(
            """SELECT name, encrypted_value FROM cookies
               WHERE host_key LIKE '%tencent.sso.codebuddy%'
               ORDER BY last_access_utc DESC"""
        ).fetchall()
        conn.close()

        cookies = {}
        seen = set()
        for name, enc in rows:
            if name in seen:
                continue
            seen.add(name)
            val = _decrypt_edge_cookie(enc, key)
            if val:
                cookies[name] = val

        if 'session' not in cookies:
            return None
        # 拼成 cookie 字符串
        parts = []
        for name in ('_gcl_au', 'qcloud_visitId', 'i18next', 'session', 'session_2'):
            if name in cookies:
                parts.append(f"{name}={cookies[name]}")
        return "; ".join(parts)
    except Exception:
        return None

def get_cb_cookie():
    """Read codebuddy cookie: try Edge browser first, fall back to file."""
    # 先试从 Edge 自动读取
    browser_cookie = get_cb_cookie_from_browser()
    if browser_cookie:
        return browser_cookie
    # 文件备用
    try:
        if CB_COOKIE_FILE.exists():
            cookie = CB_COOKIE_FILE.read_text().strip()
            if cookie:
                return cookie
    except Exception:
        pass
    return None

def set_cb_cookie(cookie_value):
    """Store codebuddy cookie to file."""
    try:
        CB_COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CB_COOKIE_FILE.write_text(cookie_value)
        os.chmod(CB_COOKIE_FILE, 0o600)
    except Exception:
        pass

def _edge_xhr_post(path, body_js="{}", retries=1):
    """通过 AppleScript 在 Edge 浏览器内执行同步 XHR POST。
    path: 请求路径，body_js: JS 表达式（字符串或对象字面量），retries: 401 时重试次数。
    Returns (status_code, response_body) 或 None。"""
    import tempfile, time

    js = (
        "var xhr=new XMLHttpRequest();"
        f"xhr.open('POST','{path}',false);"
        "xhr.setRequestHeader('Content-Type','application/json');"
        f"xhr.setRequestHeader('x-enterprise-id','{CB_ENTERPRISE_ID}');"
        f"xhr.send({body_js});"
        "xhr.status+'|'+xhr.responseText;"
    )
    applescript = (
        'tell application "Microsoft Edge"\n'
        '    set targetTab to missing value\n'
        '    repeat with w in windows\n'
        '        repeat with t in tabs of w\n'
        '            if URL of t contains "tencent.sso.codebuddy.cn" then\n'
        '                set targetTab to t\n'
        '                exit repeat\n'
        '            end if\n'
        '        end repeat\n'
        '        if targetTab is not missing value then exit repeat\n'
        '    end repeat\n'
        '    if targetTab is missing value then\n'
        '        return "NO_TAB"\n'
        '    end if\n'
        f'    return execute targetTab javascript "{js}"\n'
        'end tell'
    )

    for attempt in range(retries + 1):
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.scpt', delete=False)
        tmp.write(applescript)
        tmp.close()

        try:
            result = subprocess.run(
                ["osascript", tmp.name],
                capture_output=True, text=True, timeout=20
            )
            if result.returncode != 0:
                return None
            output = result.stdout.strip()
            if not output or output == "NO_TAB":
                return None
            status, _, body = output.partition("|")
            status = status.strip()
            if status in ("401", "403"):
                if attempt < retries:
                    time.sleep(1.5)
                    continue
                return ("AUTH_EXPIRED", None)
            return (status, body)
        except Exception:
            return None
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
    return None

def fetch_cb_quota_via_edge():
    """通过 Edge AppleScript 获取 CB 月度额度。
    Returns dict with credit/limitNum, 'AUTH_EXPIRED', or None."""
    result = _edge_xhr_post("/billing/meter/get-enterprise-user-usage", "'{}'", retries=1)
    if result is None:
        return None
    status, body = result
    if status == "AUTH_EXPIRED":
        return "AUTH_EXPIRED"
    try:
        data = json.loads(body)
        if data.get("code") == 0:
            return data.get("data", {})
    except Exception:
        pass
    return None

def fetch_cb_daily_usage_via_edge():
    """通过 Edge AppleScript 获取 CB 今日消耗数据。
    返回今日积分消耗（int），'AUTH_EXPIRED', 或 None。"""
    today = date.today()
    start = today.strftime("%Y-%m-%d 00:00:00")
    end = today.strftime("%Y-%m-%d 23:59:59")

    body_js = f"JSON.stringify({{startTime:'{start}',endTime:'{end}',pageNum:1,pageSize:10}})"
    result = _edge_xhr_post("/billing/meter/get-user-daily-usage", body_js, retries=1)
    if result is None:
        return None
    status, body = result
    if status == "AUTH_EXPIRED":
        return "AUTH_EXPIRED"
    try:
        data = json.loads(body)
        if data.get("code") == 0:
            records = data.get("data", {}).get("data", [])
            total_credit = sum(float(r.get("credit", 0)) for r in records)
            return int(total_credit)
    except Exception:
        pass
    return None

def fetch_cb_quota(cb_cookie):
    """Fetch monthly token quota: try Edge AppleScript first, fall back to HTTP."""
    edge_data = fetch_cb_quota_via_edge()
    if edge_data and edge_data != "AUTH_EXPIRED":
        return edge_data

    if not cb_cookie:
        return edge_data if edge_data == "AUTH_EXPIRED" else None

    url = f"{CB_BASE_URL}/billing/meter/get-enterprise-user-usage"
    req = urllib.request.Request(url, data=b"{}", method="POST")
    req.add_header("Cookie", cb_cookie)
    req.add_header("Content-Type", "application/json")
    req.add_header("x-enterprise-id", CB_ENTERPRISE_ID)
    req.add_header("Referer", f"{CB_BASE_URL}/profile/usage")
    req.add_header("Origin", CB_BASE_URL)
    req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0")
    try:
        with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
            body = resp.read().decode()
            data = json.loads(body)
            if data.get("code") == 0:
                return data.get("data", {})
            return None
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "AUTH_EXPIRED"
    except Exception:
        pass

    return edge_data if edge_data == "AUTH_EXPIRED" else None

# ─── Pacing logic ─────────────────────────────────────────
def count_workdays(start_date, end_date):
    """Count weekdays (Mon-Fri) between start and end inclusive."""
    count = 0
    d = start_date
    while d <= end_date:
        if d.weekday() < 5:  # Mon=0 ... Fri=4
            count += 1
        d += timedelta(days=1)
    return count

def parse_cost(cost_str):
    """Parse '$103.86' to float 103.86."""
    try:
        return float(cost_str.replace("$", "").replace(",", ""))
    except (ValueError, AttributeError):
        return 0.0

def calculate_pacing(models):
    """Calculate all pacing metrics."""
    today = date.today()
    month_start = today.replace(day=1)
    _, last_day = monthrange(today.year, today.month)
    month_end = today.replace(day=last_day)

    total_workdays = count_workdays(month_start, month_end)
    elapsed_workdays = count_workdays(month_start, today)
    remaining_workdays = total_workdays - elapsed_workdays

    # Total spend
    spent = sum(parse_cost(m.get("cost", "$0")) for m in models)

    # Ideal spend by today
    ideal_spent = BUDGET * (elapsed_workdays / max(total_workdays, 1))
    gap = ideal_spent - spent

    # Daily averages
    daily_avg = spent / max(elapsed_workdays, 1)
    target_daily = (BUDGET - spent) / max(remaining_workdays, 1)

    # Projection
    projected = spent + daily_avg * remaining_workdays

    # Status
    if daily_avg < 0.01:
        ratio = 999  # no usage yet
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

    # Advice
    diff_daily = target_daily - daily_avg
    if diff_daily > 0:
        advice = f"每工作日多用 ${diff_daily:.0f} 才能花完"
    elif diff_daily < -5:
        advice = f"每工作日可少用 ${-diff_daily:.0f}"
    else:
        advice = "保持当前节奏即可"

    # Last 5 workdays warning
    last_5_warning = None
    if remaining_workdays <= 5 and (BUDGET - spent) > 100:
        remaining = BUDGET - spent
        last_5_warning = f"还剩 ${remaining:.0f}，{remaining_workdays} 个工作日，建议切 Opus 重度使用"

    return {
        "spent": spent,
        "budget": BUDGET,
        "pct": spent / BUDGET * 100,
        "ideal_spent": ideal_spent,
        "gap": gap,
        "daily_avg": daily_avg,
        "target_daily": target_daily,
        "projected": projected,
        "status_icon": status_icon,
        "status_text": status_text,
        "advice": advice,
        "last_5_warning": last_5_warning,
        "elapsed_workdays": elapsed_workdays,
        "total_workdays": total_workdays,
        "remaining_workdays": remaining_workdays,
    }

# ─── UI Helpers ───────────────────────────────────────────
# Status-aware color scheme
STATUS_COLORS = {
    "🟥": "#FF6B6B",   # 加速 — 红
    "🟡": "#FFD93D",   # 稍加速/可放缓 — 黄
    "🟢": "#6BCB77",   # 完美 — 绿
    "🔵": "#4D96FF",   # 省着用 — 蓝
}

def get_status_color(pacing):
    """Get hex color matching current pacing status."""
    return STATUS_COLORS.get(pacing.get("status_icon", "🟢"), "#FFFFFF")

def progress_bar(pct, width=20):
    """Plain text progress bar (no ANSI)."""
    filled = int(pct / 100 * width)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)

def progress_bar_ansi(pct, width=20):
    """ANSI-colored progress bar. Use with | ansi=true."""
    filled = int(pct / 100 * width)
    filled = max(0, min(width, filled))
    # Color based on percentage
    if pct > 90:
        fg = "\033[31m"  # red
    elif pct > 70:
        fg = "\033[33m"  # yellow
    else:
        fg = "\033[32m"  # green
    dim = "\033[90m"     # dark gray
    reset = "\033[0m"
    return f"{fg}{'█' * filled}{dim}{'░' * (width - filled)}{reset}"

# ─── SwiftBar output ──────────────────────────────────────
def render_no_cookie():
    """Show when no cookie is configured."""
    print("⚠️ TokenPUA: 需要登录 | color=#FF6B6B")
    print("---")
    print("尚未配置 Cookie | color=#999999 bash=/usr/bin/true terminal=false")
    print("---")
    print("🔑 设置 Cookie | bash=/bin/bash param1=-c "
          "param2=\"cookie=$(osascript -e 'display dialog \\\"粘贴 Cookie (F12→Network→复制Cookie header):\\\" "
          "default answer \\\"\\\" with title \\\"TokenPUA\\\"' -e 'text returned of result') "
          "&& security delete-generic-password -s tokens-woa -a cookie 2>/dev/null; "
          "security add-generic-password -s tokens-woa -a cookie -w \\\"$cookie\\\"\" "
          "terminal=false refresh=true")
    print(f"🌐 打开看板 | href={DASHBOARD_URL}")

def render_auth_expired():
    """Show when cookie has expired."""
    print("⚠️ TokenPUA: Cookie 已过期 | color=#FF6B6B")
    print("---")
    print("Cookie 已失效，请重新登录并更新 | color=#FF6B6B bash=/usr/bin/true terminal=false")
    print("---")
    print("🔑 更新 Cookie | bash=/bin/bash param1=-c "
          "param2=\"cookie=$(osascript -e 'display dialog \\\"粘贴新的 Cookie (F12→Network→复制Cookie header):\\\" "
          "default answer \\\"\\\" with title \\\"TokenPUA\\\"' -e 'text returned of result') "
          "&& security delete-generic-password -s tokens-woa -a cookie 2>/dev/null; "
          "security add-generic-password -s tokens-woa -a cookie -w \\\"$cookie\\\"\" "
          "terminal=false refresh=true")
    print(f"🌐 打开看板重新登录 | href={DASHBOARD_URL}")

def render_error(detail=""):
    """Show when API call fails."""
    print("❌ TokenPUA: 请求失败 | color=#FF6B6B")
    print("---")
    print("API 请求失败，请检查网络 | color=#999999 bash=/usr/bin/true terminal=false")
    if detail:
        print(f"{detail} | color=#999999 size=10 bash=/usr/bin/true terminal=false")
    print("---")
    print("🔄 刷新 | refresh=true")
    print(f"🌐 打开看板 | href={DASHBOARD_URL}")

def render_dashboard(pacing, models, today_models, cb_data=None, cb_daily_credit=None):
    """Render full dashboard with rich formatting."""
    p = pacing
    now = datetime.now().strftime("%H:%M")
    sc = get_status_color(p)  # status-aware accent color

    def _display_width(text):
        return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)

    def _pad_label(text, width=8):
        pad = max(0, width - _display_width(text))
        return text + (" " * pad)

    # ── Precompute common values ──
    today = date.today()
    _, total_days = monthrange(today.year, today.month)
    elapsed_days = today.day  # 自然日：今天是一月中的第几天
    time_pct = elapsed_days / total_days * 100  # 时间进度百分比

    # CC (USD) 数据
    cb_pct = p['pct']  # spent/budget*100
    cb_spent = p['spent']
    cb_budget = p['budget']

    # CB (Codebuddy 积分) 数据
    cc_used = 0
    cc_limit = CB_TOKEN_LIMIT
    cc_pct = 0
    cc_available = False
    cc_expired = False
    if cb_data and cb_data != "AUTH_EXPIRED":
        cc_used = int(cb_data.get("credit", 0))
        cc_limit = int(cb_data.get("limitNum", CB_TOKEN_LIMIT))
        cc_pct = cc_used / cc_limit * 100 if cc_limit else 0
        cc_available = True
    elif cb_data == "AUTH_EXPIRED":
        cc_expired = True

    cc_used_usd = cc_used / CB_POINTS_PER_USD
    cc_limit_usd = cc_limit / CB_POINTS_PER_USD

    # 日均额度（按工作日）
    remaining_workdays = p['remaining_workdays']
    daily_cb = (cb_budget - cb_spent) / max(remaining_workdays, 1)
    daily_cc_usd = (cc_limit_usd - cc_used_usd) / max(remaining_workdays, 1)

    # 今日消耗
    today_cb_spent = sum(parse_cost(m.get("cost", "$0")) for m in today_models)
    today_cc_usd = 0
    if cb_daily_credit is not None and cb_daily_credit != "AUTH_EXPIRED":
        today_cc_usd = cb_daily_credit / CB_POINTS_PER_USD
    today_total_usd = today_cb_spent + today_cc_usd
    daily_total_usd = daily_cb + daily_cc_usd

    # 今日时间进度
    current_hour = datetime.now().hour
    current_minute = datetime.now().minute
    day_time_pct = (current_hour + current_minute / 60) / 24 * 100

    # 日进度百分比
    daily_cb_pct = today_cb_spent / max(daily_cb, 0.01) * 100 if daily_cb > 0 else 0

    # ── Header (menu bar) ──
    print(f"{p['status_icon']} ${today_total_usd:.0f}/${daily_total_usd:.0f} · {p['status_text']} | size=13")

    # ── Dropdown ──
    print("---")

    # bash=/usr/bin/true gives items an action so macOS doesn't grey them out
    NOOP = "bash=/usr/bin/true terminal=false"

    # ══ 模块一：总额度 ══
    print(f"月额度（$1 = 100积分） | size=11 color=#888888 {NOOP}")
    label_time = "时间进度"
    label_cc = "CC进度 "
    label_cb = "CB进度 "

    bar_time = progress_bar_ansi(time_pct)
    print(f"{label_time}  {bar_time}  {time_pct:.0f}%  {elapsed_days}/{total_days}天 | ansi=true size=13 font=Menlo {NOOP}")
    bar_cb = progress_bar_ansi(cb_pct)
    print(f"{label_cc}  {bar_cb}  {cb_pct:.0f}%  ${cb_spent:.0f}/${cb_budget:.0f} | ansi=true size=13 font=Menlo {NOOP}")
    if cc_available:
        bar_cc = progress_bar_ansi(cc_pct)
        print(f"{label_cb}  {bar_cc}  {cc_pct:.0f}%  ${cc_used_usd:.0f}/${cc_limit_usd:.0f} | ansi=true size=13 font=Menlo {NOOP}")
    elif cc_expired:
        print(f"{label_cb}  Cookie 已过期 | color=#FF6B6B {NOOP}")
        print("更新 CB Cookie | bash=/bin/bash param1=-c "
              "param2=\"cookie=$(osascript -e 'display dialog \\\"粘贴 tencent.sso.codebuddy.cn Cookie:\\\" "
              "default answer \\\"\\\" with title \\\"Codebuddy Cookie\\\"' -e 'text returned of result') "
              f"&& mkdir -p {CB_COOKIE_FILE.parent} && echo \\\"$cookie\\\" > {CB_COOKIE_FILE} && chmod 600 {CB_COOKIE_FILE}\" "
              "terminal=false refresh=true")
    else:
        print(f"{label_cb}  未配置 | color=#999999 {NOOP}")
        print("设置 CB Cookie | bash=/bin/bash param1=-c "
              "param2=\"cookie=$(osascript -e 'display dialog \\\"粘贴 tencent.sso.codebuddy.cn Cookie:\\\" "
              "default answer \\\"\\\" with title \\\"Codebuddy Cookie\\\"' -e 'text returned of result') "
              f"&& mkdir -p {CB_COOKIE_FILE.parent} && echo \\\"$cookie\\\" > {CB_COOKIE_FILE} && chmod 600 {CB_COOKIE_FILE}\" "
              "terminal=false refresh=true")
    print("---")

    # ══ 模块二：日额度 ══
    print(f"日额度（{now}更新） | size=11 color=#888888 {NOOP}")
    bar_day_time = progress_bar_ansi(day_time_pct)
    print(f"{label_time}  {bar_day_time}  {day_time_pct:.0f}%  {current_hour:02d}:{current_minute:02d}/24:00 | ansi=true size=13 font=Menlo {NOOP}")
    bar_daily_cb = progress_bar_ansi(min(daily_cb_pct, 100))
    print(f"{label_cc}  {bar_daily_cb}  {daily_cb_pct:.0f}%  ${today_cb_spent:.0f}/${daily_cb:.0f} | ansi=true size=13 font=Menlo {NOOP}")
    if cc_available:
        if cb_daily_credit is not None and cb_daily_credit != "AUTH_EXPIRED":
            today_cb_credit_usd = cb_daily_credit / CB_POINTS_PER_USD
            daily_cb_pct_cb = today_cb_credit_usd / max(daily_cc_usd, 0.01) * 100 if daily_cc_usd > 0 else 0
            bar_daily_cc = progress_bar_ansi(min(daily_cb_pct_cb, 100))
            print(f"{label_cb}  {bar_daily_cc}  {daily_cb_pct_cb:.0f}%  ${today_cb_credit_usd:.0f}/${daily_cc_usd:.0f} | ansi=true size=13 font=Menlo {NOOP}")
        else:
            print(f"{label_cb}  —  /${daily_cc_usd:.0f} | color=#999999 {NOOP}")
    elif cc_expired:
        print(f"{label_cb}  Cookie 已过期 | color=#FF6B6B {NOOP}")
    else:
        print(f"{label_cb}  未配置 | color=#999999 {NOOP}")
    print("---")
    print("打开 CC Token 看板 | href=https://tokens.woa.com/?product=codebuddy")
    print("打开 CB Token 看板 | href=https://tencent.sso.codebuddy.cn/profile/usage")

# ─── Main ─────────────────────────────────────────────────
def main():
    cookie = get_cookie()
    if not cookie:
        render_no_cookie()
        return

    # Fetch data
    summary = fetch_usage_summary(cookie)
    if summary == "AUTH_EXPIRED":
        render_auth_expired()
        return
    if summary is None:
        render_error("usage-summary 返回 None")
        return

    models = summary.get("data", [])
    if not models:
        render_error(f"data 为空, keys={list(summary.keys())}")
        return

    # Fetch today's usage
    today_summary = fetch_today_usage(cookie)
    today_models = []
    if today_summary and today_summary != "AUTH_EXPIRED":
        today_models = today_summary.get("data", [])

    # Fetch codebuddy token quota
    cb_cookie = get_cb_cookie()
    cb_data = fetch_cb_quota(cb_cookie)

    # Fetch CB daily usage (today)
    cb_daily_credit = fetch_cb_daily_usage_via_edge()

    # Calculate pacing
    pacing = calculate_pacing(models)

    # Render
    render_dashboard(pacing, models, today_models, cb_data, cb_daily_credit)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ TokenPUA Error | color=#FF6B6B")
        print("---")
        print(f"{type(e).__name__}: {e} | color=#FF6B6B size=10 trim=false")
        print("🔄 刷新 | refresh=true")
