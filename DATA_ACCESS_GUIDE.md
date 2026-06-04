# Token-PUA 数据获取指南（手动 Cookie 方式）

适用场景：不想运行安装脚本，只想手动拿到 Cookie 后调用 API 获取数据。

---

## 一、获取 Cookie

### 步骤

1. 用浏览器（Chrome 或 Edge）打开 https://tokens.woa.com，确保已登录
2. 按 `F12` 打开开发者工具，切到 **Network（网络）** 标签
3. 刷新页面（`Cmd + R`）
4. 点击任意一个请求，在右侧找到 **Request Headers（请求头）**
5. 找到 `Cookie:` 这一行，复制整个值

你需要的是 `RIO_TOKEN=xxxx` 这一段（xxxx 是你的 token 值）。

> 如果只想复制 `RIO_TOKEN` 的值：在 **Application（应用）** 标签 → **Cookies** → `https://tokens.woa.com` → 找到 `RIO_TOKEN` → 复制它的值（不含键名）。

---

## 二、调用 API 获取数据

### 方式 A：用 curl（最简单）

把 `<YOUR_TOKEN>` 替换成你复制的 `RIO_TOKEN` 值：

```bash
# 获取本月额度使用情况
curl -s 'https://tokens.woa.com/api/query-quota?platform=codebuddy' \
  -H 'Cookie: RIO_TOKEN=<YOUR_TOKEN>' \
  -H 'User-Agent: Mozilla/5.0' \
  | python3 -m json.tool
```

返回示例：

```json
{
  "code": 0,
  "data": {
    "total_used": 123.45,
    "total_quota": 1000.0
  }
}
```

### 方式 B：用 Python

```python
import urllib.request
import json
import ssl

TOKEN = "<YOUR_TOKEN>"
BASE_URL = "https://tokens.woa.com"

def get_quota():
    url = f"{BASE_URL}/api/query-quota?platform=codebuddy"
    req = urllib.request.Request(url)
    req.add_header("Cookie", f"RIO_TOKEN={TOKEN}")
    req.add_header("User-Agent", "Mozilla/5.0")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    with urllib.request.urlopen(req, context=ctx) as resp:
        return json.loads(resp.read())

result = get_quota()
print(result)
```

> 内网 HTTPS 证书是自签的，Python 需要跳过 SSL 验证（见上方 `ssl.create_default_context()` 配置）。

---

## 三、可用接口一览

| 接口 | 用途 | 参数 |
|------|------|-------|
| `GET /api/query-quota?platform=codebuddy` | 本月已用额度 / 总预算 | `platform=codebuddy` |
| `GET /api/usage-summary?start_date=...&end_date=...&platform=codebuddy` | 按模型汇总用量 | `start_date`、`end_date`（格式 `YYYY-MM-DD`）、`platform` |
| `GET /api/usage-details?start_date=...&end_date=...&platform=codebuddy` | 指定日期使用明细 | `start_date`、`end_date`、`platform` |

`platform` 可选值：`codebuddy`、`with`、`codebuddy-code`、`codebuddy-cli`、`codex-internal`、`xcode`（多个用逗号分隔）。

---

## 四、常见问题

**Q：Cookie 多久过期？**
A：通常 1-2 天。过期后重新从浏览器复制即可。

**Q：返回 `{"code": 401}` 或空数据？**
A：Cookie 已过期，重新登录 `https://tokens.woa.com` 后再复制。

**Q：内网访问不到 `tokens.woa.com`？**
A：需要在公司内网，或开启 VPN。
