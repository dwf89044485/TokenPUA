#!/opt/homebrew/bin/python3
# <xbar.title>Token Budget Pacing</xbar.title>
# <xbar.desc>Monthly token usage burndown predictor for tokens.woa.com</xbar.desc>
# <xbar.version>1.0</xbar.version>
# <xbar.author>josephdeng</xbar.author>

import json
import os
import ssl
import subprocess
import sys
import urllib.request
import urllib.error
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
CB_TOKEN_LIMIT = 150000  # 月度 token 上限

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
            capture_output=True, text=True, timeout=20
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
    # 优先用 Edge 内部执行
    result = _edge_xhr_get(url)
    if result is not None:
        return result
    # 降级：直接 HTTP（需要有效 cookie）
    if not cookie:
        return None
    req = urllib.request.Request(url)
    req.add_header("Cookie", cookie)
    req.add_header("User-Agent", "TokensPacer/1.0")
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

def fetch_cb_quota_via_edge():
    """通过 AppleScript 在 Edge 浏览器内执行 XHR，绕过 session 限制。
    需要 Edge 已登录 tencent.sso.codebuddy.cn，且开启了 Allow JavaScript from Apple Events。
    Returns dict with credit/limitNum, 'AUTH_EXPIRED', or None."""
    js = (
        "var xhr=new XMLHttpRequest();"
        f"xhr.open('POST','/billing/meter/get-enterprise-user-usage',false);"
        "xhr.setRequestHeader('Content-Type','application/json');"
        f"xhr.setRequestHeader('x-enterprise-id','{CB_ENTERPRISE_ID}');"
        "xhr.send('{}');"
        "xhr.status+'|'+xhr.responseText;"
    )
    applescript = f'''
tell application "Microsoft Edge"
    set targetTab to missing value
    repeat with w in windows
        repeat with t in tabs of w
            if URL of t contains "tencent.sso.codebuddy.cn" then
                set targetTab to t
                exit repeat
            end if
        end repeat
        if targetTab is not missing value then exit repeat
    end repeat
    if targetTab is missing value then
        return "NO_TAB"
    end if
    return execute targetTab javascript "{js}"
end tell
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return None
        output = result.stdout.strip()
        if output == "NO_TAB" or not output:
            return None
        status, _, body = output.partition("|")
        if status.strip() in ("401", "403"):
            return "AUTH_EXPIRED"
        data = json.loads(body)
        if data.get("code") == 0:
            return data.get("data", {})
        return None
    except Exception:
        return None

def fetch_cb_quota(cb_cookie):
    """Fetch monthly token quota: try Edge AppleScript first, fall back to HTTP."""
    # 优先用 Edge 内部执行（无 session 问题）
    result = fetch_cb_quota_via_edge()
    if result is not None:
        return result
    # 降级：直接 HTTP 请求（需要有效 cookie）
    if not cb_cookie:
        return None
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
    return None

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

# ─── Progress bar ─────────────────────────────────────────
def progress_bar(pct, width=20):
    filled = int(pct / 100 * width)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)

# ─── SwiftBar output ──────────────────────────────────────
def render_no_cookie():
    """Show when no cookie is configured."""
    print("⚠️ Tokens: 需要登录 | color=#FF6B6B")
    print("---")
    print("尚未配置 Cookie | color=#999999")
    print("---")
    print("🔑 设置 Cookie | bash=/bin/bash param1=-c "
          "param2=\"cookie=$(osascript -e 'display dialog \\\"粘贴 Cookie (F12→Network→复制Cookie header):\\\" "
          "default answer \\\"\\\" with title \\\"Tokens Cookie\\\"' -e 'text returned of result') "
          "&& security delete-generic-password -s tokens-woa -a cookie 2>/dev/null; "
          "security add-generic-password -s tokens-woa -a cookie -w \\\"$cookie\\\"\" "
          "terminal=false refresh=true")
    print(f"🌐 打开看板 | href={DASHBOARD_URL}")

def render_auth_expired():
    """Show when cookie has expired."""
    print("⚠️ Tokens: Cookie 已过期 | color=#FF6B6B")
    print("---")
    print("Cookie 已失效，请重新登录并更新 | color=#FF6B6B")
    print("---")
    print("🔑 更新 Cookie | bash=/bin/bash param1=-c "
          "param2=\"cookie=$(osascript -e 'display dialog \\\"粘贴新的 Cookie (F12→Network→复制Cookie header):\\\" "
          "default answer \\\"\\\" with title \\\"Tokens Cookie\\\"' -e 'text returned of result') "
          "&& security delete-generic-password -s tokens-woa -a cookie 2>/dev/null; "
          "security add-generic-password -s tokens-woa -a cookie -w \\\"$cookie\\\"\" "
          "terminal=false refresh=true")
    print(f"🌐 打开看板重新登录 | href={DASHBOARD_URL}")

def render_error(detail=""):
    """Show when API call fails."""
    print("❌ Tokens: 请求失败 | color=#FF6B6B")
    print("---")
    print("API 请求失败，请检查网络 | color=#999999")
    if detail:
        print(f"{detail} | color=#999999 size=10")
    print("---")
    print("🔄 刷新 | refresh=true")
    print(f"🌐 打开看板 | href={DASHBOARD_URL}")

def render_dashboard(pacing, models, today_models, cb_data=None):
    """Render full dashboard."""
    p = pacing
    now = datetime.now().strftime("%H:%M")

    # ── Header (menu bar) ──
    print(f"{p['status_icon']} ${p['spent']:.0f}/${p['budget']:.0f} · {p['status_text']} | size=13")

    # ── Dropdown ──
    print("---")

    # ══ Block 1: WOA 总额 ══
    bar = progress_bar(p['pct'])
    print(f"{bar}  {p['pct']:.1f}%")
    print(f"已用 ${p['spent']:.2f}  /  月度额度 ${p['budget']:.0f}")
    print("---")

    # ══ Block 2: WOA 日均可用额度 ══
    print(f"日均可用  ${p['target_daily']:.0f}  （剩余 {p['remaining_workdays']} 工作日）")
    print("---")

    # ══ Block 3: Codebuddy Token 额度 ══
    if cb_data and cb_data != "AUTH_EXPIRED":
        used = int(cb_data.get("credit", 0))
        limit = int(cb_data.get("limitNum", CB_TOKEN_LIMIT))
        remaining_tokens = limit - used
        pct_tokens = used / limit * 100 if limit else 0
        bar_tokens = progress_bar(pct_tokens)
        daily_tokens = remaining_tokens // max(p['remaining_workdays'], 1)
        print(f"{bar_tokens}  {pct_tokens:.1f}%")
        print(f"Token 已用 {used:,}  /  {limit:,}")
        print(f"日均可用  {daily_tokens:,} tokens  （剩余 {p['remaining_workdays']} 工作日）")
    elif cb_data == "AUTH_EXPIRED":
        print("Codebuddy Token: Cookie 已过期 | color=#FF6B6B")
        print("更新 CB Cookie | sfimage=key bash=/bin/bash param1=-c "
              "param2=\"cookie=$(osascript -e 'display dialog \\\"粘贴 tencent.sso.codebuddy.cn Cookie:\\\" "
              "default answer \\\"\\\" with title \\\"Codebuddy Cookie\\\"' -e 'text returned of result') "
              f"&& mkdir -p {CB_COOKIE_FILE.parent} && echo \\\"$cookie\\\" > {CB_COOKIE_FILE} && chmod 600 {CB_COOKIE_FILE}\" "
              "terminal=false refresh=true")
    else:
        print("Codebuddy Token: 未配置 | color=#999999")
        print("设置 CB Cookie | sfimage=key bash=/bin/bash param1=-c "
              "param2=\"cookie=$(osascript -e 'display dialog \\\"粘贴 tencent.sso.codebuddy.cn Cookie:\\\" "
              "default answer \\\"\\\" with title \\\"Codebuddy Cookie\\\"' -e 'text returned of result') "
              f"&& mkdir -p {CB_COOKIE_FILE.parent} && echo \\\"$cookie\\\" > {CB_COOKIE_FILE} && chmod 600 {CB_COOKIE_FILE}\" "
              "terminal=false refresh=true")
    print("---")

    # ── Actions ──
    print(f"刷新 | refresh=true sfimage=arrow.clockwise")
    print("更新 WOA Cookie | sfimage=key.fill bash=/bin/bash param1=-c "
          "param2=\"cookie=$(osascript -e 'display dialog \\\"粘贴新的 Cookie:\\\" "
          "default answer \\\"\\\" with title \\\"Tokens Cookie\\\"' -e 'text returned of result') "
          "&& security delete-generic-password -s tokens-woa -a cookie 2>/dev/null; "
          "security add-generic-password -s tokens-woa -a cookie -w \\\"$cookie\\\"\" "
          "terminal=false refresh=true")
    print(f"打开看板 | href={DASHBOARD_URL} sfimage=safari")
    print(f"  {now} 更新 | color=#666666 size=10 trim=false")

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
    cb_data = None
    if cb_cookie:
        cb_data = fetch_cb_quota(cb_cookie)

    # Calculate pacing
    pacing = calculate_pacing(models)

    # Render
    render_dashboard(pacing, models, today_models, cb_data)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Tokens Error | color=#FF6B6B")
        print("---")
        print(f"{type(e).__name__}: {e} | color=#FF6B6B size=10 trim=false")
        print("🔄 刷新 | refresh=true")
