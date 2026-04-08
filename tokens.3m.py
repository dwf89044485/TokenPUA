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
def api_get(path, cookie):
    """GET request to tokens API. Returns parsed JSON or None."""
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url)
    req.add_header("Cookie", cookie)
    req.add_header("User-Agent", "TokensPacer/1.0")
    try:
        with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
            if resp.status == 200:
                body = resp.read().decode()
                # If response is HTML (login redirect), cookie is expired
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

def fetch_quota(cookie):
    """Fetch usage percentage."""
    return api_get("/api/query-quota?platform=codebuddy", cookie)

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

def render_dashboard(pacing, models):
    """Render full dashboard."""
    p = pacing
    now = datetime.now().strftime("%H:%M:%S")

    # ── Header (menu bar) ──
    print(f"{p['status_icon']} ${p['spent']:.0f}/${p['budget']:.0f} · {p['status_text']} | size=13")

    # ── Dropdown ──
    print("---")

    # Budget section
    print(f"本月额度 | size=13 color=#AAAAAA")
    print(f"已用 ${p['spent']:.2f} / ${p['budget']:.0f} ({p['pct']:.1f}%) | font=Menlo size=12")
    print(f"{progress_bar(p['pct'])} | font=Menlo size=11")
    print("---")

    # Pacing section
    print(f"Pacing | size=13 color=#AAAAAA")
    gap_sign = "落后" if p['gap'] > 0 else "超前"
    print(f"理论应用  ${p['ideal_spent']:.0f} ({gap_sign} ${abs(p['gap']):.0f}) | font=Menlo size=12")
    print(f"当前日均  ${p['daily_avg']:.2f} (工作日) | font=Menlo size=12")
    print(f"目标日均  ${p['target_daily']:.2f} (工作日) | font=Menlo size=12")
    print(f"月底预测  ${p['projected']:.0f} | font=Menlo size=12")
    print(f"工作日    {p['elapsed_workdays']}/{p['total_workdays']} (剩余 {p['remaining_workdays']}) | font=Menlo size=12")
    print("---")

    # Advice section
    print(f"建议 | size=13 color=#AAAAAA")
    print(f"{p['status_icon']} {p['advice']} | size=12")
    if p['last_5_warning']:
        print(f"⚡ {p['last_5_warning']} | size=12 color=#FFD700")
    print("---")

    # Model breakdown
    print(f"模型分布 | size=13 color=#AAAAAA")
    for m in models:
        cost = parse_cost(m.get("cost", "$0"))
        if cost <= 0:
            continue
        pct = cost / max(p['spent'], 0.01) * 100
        name = m.get("model_name", "Unknown")
        req = m.get("request_count", "0")
        print(f"{name:20s} ${cost:>7.2f} ({pct:4.1f}%) {req} 次 | font=Menlo size=11")
    print("---")

    # Actions
    print("🔄 刷新 | refresh=true")
    print("🔑 更新 Cookie | bash=/bin/bash param1=-c "
          "param2=\"cookie=$(osascript -e 'display dialog \\\"粘贴新的 Cookie:\\\" "
          "default answer \\\"\\\" with title \\\"Tokens Cookie\\\"' -e 'text returned of result') "
          "&& security delete-generic-password -s tokens-woa -a cookie 2>/dev/null; "
          "security add-generic-password -s tokens-woa -a cookie -w \\\"$cookie\\\"\" "
          "terminal=false refresh=true")
    print(f"🌐 打开看板 | href={DASHBOARD_URL}")
    print(f"上次刷新: {now} | color=#666666 size=10")

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

    # Calculate pacing
    pacing = calculate_pacing(models)

    # Render
    render_dashboard(pacing, models)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Tokens Error | color=#FF6B6B")
        print("---")
        print(f"{type(e).__name__}: {e} | color=#FF6B6B size=10 trim=false")
        print("🔄 刷新 | refresh=true")
