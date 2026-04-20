#!/usr/bin/env python3

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


CONFIG_DIR = Path.home() / ".config" / "tokens-woa"
CB_BASE_URL = "https://tencent.sso.codebuddy.cn"
CB_ENTERPRISE_ID = "etahzsqej0n4"
CB_USAGE_URL = f"{CB_BASE_URL}/profile/usage"
CB_HELPER_CACHE_FILE = CONFIG_DIR / "cb_helper_cache.json"
AGENT_BROWSER_PROFILE_DIR = CONFIG_DIR / "agent-browser-profile"
COMMON_AGENT_BROWSER_PATHS = (
    "/opt/homebrew/bin/agent-browser",
    "/usr/local/bin/agent-browser",
)


def resolve_agent_browser_bin() -> str:
    env_bin = os.environ.get("TOKEN_PUA_AGENT_BROWSER")
    if env_bin and Path(env_bin).exists():
        return env_bin

    found = shutil.which("agent-browser")
    if found:
        return found

    for candidate in COMMON_AGENT_BROWSER_PATHS:
        if Path(candidate).exists():
            return candidate

    raise RuntimeError("未安装 agent-browser，请先执行: npm i -g agent-browser && agent-browser install")


def write_cache(status: str, *, monthly_credit: Optional[int] = None,
                monthly_limit: Optional[int] = None,
                daily_credit: Optional[int] = None,
                message: str = "", current_url: str = "") -> dict[str, Any]:
    payload = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "monthly_credit": monthly_credit,
        "monthly_limit": monthly_limit,
        "daily_credit": daily_credit,
        "source": "agent-browser",
        "message": message,
        "current_url": current_url,
    }
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CB_HELPER_CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    os.chmod(CB_HELPER_CACHE_FILE, 0o600)
    return payload


def run_agent_browser(*args: str, headed: bool = False, timeout: int = 40) -> str:
    command = [
        resolve_agent_browser_bin(),
        "--profile",
        str(AGENT_BROWSER_PROFILE_DIR),
    ]
    if headed:
        command.append("--headed")
    command.extend(args)

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"agent-browser 命令超时: {' '.join(command[1:])}") from e

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(err or f"agent-browser 失败: {' '.join(command[1:])}")
    return result.stdout.strip()


def eval_json(script: str, *, headed: bool = False, timeout: int = 40) -> Any:
    output = run_agent_browser("eval", script, headed=headed, timeout=timeout)
    try:
        return json.loads(output)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"agent-browser 返回的不是 JSON: {output[:300]}") from e


def read_context(*, headed: bool = False) -> dict[str, Any]:
    script = """
(() => ({
  href: location.href,
  origin: location.origin,
  title: document.title,
  readyState: document.readyState,
  text: (document.body && document.body.innerText ? document.body.innerText : '').slice(0, 500)
}))()
""".strip()
    return eval_json(script, headed=headed)


def click_by_text(text: str, *, headed: bool = False) -> bool:
    script = f"""
(() => {{
  const nodes = [...document.querySelectorAll('a,button,[role=button],div,span')];
  const target = nodes.find((el) => ((el.innerText || el.textContent || '').trim().includes({json.dumps(text)})));
  if (!target) return {{clicked:false}};
  target.click();
  return {{clicked:true}};
}})()
""".strip()
    result = eval_json(script, headed=headed)
    return bool(result.get("clicked"))


def is_usage_page(ctx: dict[str, Any]) -> bool:
    href = ctx.get("href", "")
    return href.startswith(CB_USAGE_URL) or href.startswith(f"{CB_BASE_URL}/profile")


def build_login_required_message(current_url: str, interactive: bool) -> str:
    if interactive:
        return f"请在弹出的 agent-browser 浏览器窗口完成登录，然后重新运行 helper。当前页面: {current_url}"
    return f"CB 需要登录。请运行: python3 cb_helper.py --interactive。当前页面: {current_url}"


def ensure_usage_page(*, timeout: int = 30, interactive: bool = False) -> dict[str, Any]:
    run_agent_browser("open", CB_USAGE_URL, headed=interactive, timeout=40)
    time.sleep(1.5)

    clicked_quick_login = False
    clicked_push = False
    deadline = time.time() + timeout

    while time.time() < deadline:
        ctx = read_context(headed=interactive)
        text = ctx.get("text", "")
        if is_usage_page(ctx):
            return ctx
        if not interactive:
            time.sleep(2)
            continue
        if ("快速登录" in text or "/login/" in ctx.get("href", "")) and not clicked_quick_login:
            clicked_quick_login = click_by_text("快速登录", headed=True)
            time.sleep(1.5)
            continue
        if ("发起验证" in text or "请在手机 iOA 确认登录" in text) and not clicked_push:
            clicked_push = click_by_text("发起验证", headed=True)
            time.sleep(1.5)
            continue
        time.sleep(2)

    return read_context(headed=interactive)


def fetch_usage_data(*, interactive: bool = False) -> dict[str, Any]:
    script = f"""
(async () => {{
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const day = `${{now.getFullYear()}}-${{pad(now.getMonth() + 1)}}-${{pad(now.getDate())}}`;
  const headers = {{
    'Content-Type': 'application/json',
    'x-enterprise-id': {json.dumps(CB_ENTERPRISE_ID)}
  }};
  const [quotaResp, dailyResp] = await Promise.all([
    fetch('/billing/meter/get-enterprise-user-usage', {{
      method: 'POST',
      credentials: 'include',
      headers,
      body: '{{}}'
    }}),
    fetch('/billing/meter/get-user-daily-usage', {{
      method: 'POST',
      credentials: 'include',
      headers,
      body: JSON.stringify({{
        startTime: `${{day}} 00:00:00`,
        endTime: `${{day}} 23:59:59`,
        pageNum: 1,
        pageSize: 10,
      }})
    }})
  ]);

  const quotaText = await quotaResp.text();
  const dailyText = await dailyResp.text();
  let quotaJson = null;
  let dailyJson = null;
  try {{ quotaJson = JSON.parse(quotaText); }} catch (e) {{}}
  try {{ dailyJson = JSON.parse(dailyText); }} catch (e) {{}}

  return {{
    href: location.href,
    quotaStatus: quotaResp.status,
    dailyStatus: dailyResp.status,
    quotaJson,
    dailyJson,
    quotaText: quotaText.slice(0, 500),
    dailyText: dailyText.slice(0, 500),
  }};
}})()
""".strip()
    return eval_json(script, headed=interactive, timeout=60)


def normalize_usage(payload: dict[str, Any]) -> dict[str, int]:
    quota_status = int(payload.get("quotaStatus", 0) or 0)
    daily_status = int(payload.get("dailyStatus", 0) or 0)

    if quota_status in (401, 403) or daily_status in (401, 403):
        raise PermissionError("CB 登录态失效，需要重新登录")

    quota_json = payload.get("quotaJson") or {}
    daily_json = payload.get("dailyJson") or {}
    quota_data = quota_json.get("data") or {}
    daily_records = ((daily_json.get("data") or {}).get("data") or [])

    if quota_json.get("code") != 0:
        raise RuntimeError(payload.get("quotaText") or "月度接口返回异常")
    if daily_json.get("code") != 0:
        raise RuntimeError(payload.get("dailyText") or "日度接口返回异常")

    monthly_credit = int(float(quota_data.get("credit", 0) or 0))
    monthly_limit = int(float(quota_data.get("limitNum", 0) or 0))
    daily_credit = int(sum(float(item.get("credit", 0) or 0) for item in daily_records))

    return {
        "monthly_credit": monthly_credit,
        "monthly_limit": monthly_limit,
        "daily_credit": daily_credit,
    }


def main() -> int:
    interactive = "--interactive" in sys.argv[1:]
    try:
        ctx = ensure_usage_page(interactive=interactive)
        if not is_usage_page(ctx):
            current_url = ctx.get("href", "")
            msg = build_login_required_message(current_url, interactive)
            write_cache("login_required", message=msg, current_url=current_url)
            print(msg)
            return 0

        payload = fetch_usage_data(interactive=interactive)
        try:
            usage = normalize_usage(payload)
        except PermissionError as e:
            current_url = payload.get("href", "")
            suffix = build_login_required_message(current_url, interactive)
            msg = f"{e}。{suffix}"
            write_cache("login_required", message=msg, current_url=current_url)
            print(msg)
            return 0

        cache = write_cache(
            "ok",
            monthly_credit=usage["monthly_credit"],
            monthly_limit=usage["monthly_limit"],
            daily_credit=usage["daily_credit"],
            message="CB helper 抓取成功",
            current_url=payload.get("href", ""),
        )
        print(json.dumps(cache, ensure_ascii=False))
        return 0
    except Exception as e:
        write_cache("error", message=str(e))
        print(f"CB helper 失败: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
