# TokenPUA

macOS 菜单栏工具，实时显示每月 Token 额度使用进度，帮你把额度花完不浪费。

同时接入两个渠道：
- **CC（WOA 渠道）**（`tokens.woa.com`）：按模型展示美元花费，支持工作日 pacing 计算
- **CB（Codebuddy 渠道）**（`tencent.sso.codebuddy.cn`）：月度 token 积分用量（100 秒分 = $1，统一以美元显示）

缩写约定：**CC = WOA 渠道（美元消耗）**，**CB = Codebuddy 渠道（token 消耗 → 按 100 积分 = $1 统一为美元显示）**。

---

## 效果

菜单栏显示：`🟥 $231/$1000 · 加速!`

下拉内容：
```
████░░░░░░░░░░░░░░░░  23.1%
已用 $231.03  /  月度额度 $1000
---
日均可用  $51  （剩余 15 工作日）
---
█░░░░░░░░░░░░░░░░░░░  9.8%
Token 已用 14,748  /  150,000
日均可用  9,016 tokens  （剩余 15 工作日）
```

---

## 安装

### 1. 安装 SwiftBar

```bash
brew install --cask swiftbar
```

或从 [swiftbar.app](https://swiftbar.app) 下载。

### 2. 安装依赖

```bash
python3 -m pip install cryptography --break-system-packages
```

> `install.sh` 会自动检测并尝试安装该依赖；手动执行仅用于补装或排错。

### 3. 部署插件

```bash
bash install.sh
```

安装脚本会自动完成：
- 识别 SwiftBar 当前插件目录并部署 `tokens.3m.py`
- 按本机 Python 路径修正 shebang
- 若插件被 SwiftBar 禁用，自动解除 `tokens.3m.py` 的禁用状态
- 重启并刷新 SwiftBar

或手动：

```bash
PLUGIN_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo "$HOME/.swiftbar-plugins")"
cp tokens.3m.py "$PLUGIN_DIR/tokens.3m.py"
```

### 4. 开启 Edge AppleScript 权限（推荐）

**不开也能用，但会更依赖手动更新 Cookie；开启后自动获取成功率更高。**

Mac 屏幕**最顶部系统菜单栏**（不是 Edge 窗口内）→ **视图（View）** → **开发人员（Developer）** → **允许 Apple 活动中的 JavaScript（Allow JavaScript from Apple Events）** → 勾选。

> 找不到"开发人员"子菜单？在 Edge 地址栏输入 `edge://flags/#edge-developer-mode-devtools` 开启开发者模式后重试。

### 5. 登录状态要求（重要）

- **WOA 渠道**：首次安装需要提供 WOA Cookie（`install.sh` 会提示输入），后续过期时在菜单中点 `更新 WOA Cookie`。
- **Codebuddy 渠道**：建议保持 `https://tencent.sso.codebuddy.cn/profile/usage` 已登录；插件会优先尝试自动获取，失败时可在菜单中手动更新 CB Cookie。

---

## 自定义配置

修改 `tokens.3m.py` 顶部 Config 区域：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `BUDGET` | WOA 月度预算（美元） | `1000.0` |
| `PLATFORMS` | WOA 统计的产品平台 | `codebuddy,with,...` |
| `CB_ENTERPRISE_ID` | Codebuddy 企业 ID（见下方说明） | `etahzsqej0n4` |
| `CB_TOKEN_LIMIT` | Codebuddy 月度 token 上限（显示用，实际从 API 取） | `150000` |

**如何找到你的 `CB_ENTERPRISE_ID`**：打开 `tencent.sso.codebuddy.cn/profile/usage`，F12 → Network → 找 `get-enterprise-user-usage` 请求 → Request Headers → 找 `x-enterprise-id` 的值。

---

## 状态含义

| 图标 | 含义 | 触发条件（目标日均 vs 当前日均） |
|------|------|------|
| 🟥 | 加速! | 目标 > 当前 × 1.3 |
| 🟡 | 稍加速 | 目标 > 当前 × 1.1 |
| 🟢 | 完美 | 差距在 ±10% 内 |
| 🟡 | 可放缓 | 目标 < 当前 × 0.9 |
| 🔵 | 省着用 | 目标 < 当前 × 0.7 |

---

## 前置要求

- macOS（Apple Silicon，已测试 M 系列）
- [Homebrew](https://brew.sh)
- Microsoft Edge（用于 AppleScript 自动认证）
- 公司内网访问权限（WOA 渠道）

---

## 快速自检（菜单栏空白 / 没内容时）

1. **先看插件是否能在终端输出**：
   ```bash
   "$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo "$HOME/.swiftbar-plugins")/tokens.3m.py"
   ```
2. **确认 SwiftBar 正在使用的插件目录**：
   ```bash
   defaults read com.ameba.SwiftBar PluginDirectory
   ```
   并确认该目录下存在 `tokens.3m.py`。
3. **确认没有被禁用**：
   ```bash
   defaults read com.ameba.SwiftBar DisabledPlugins
   ```
   如果出现 `tokens.3m.py`，重新执行 `bash install.sh` 自动解除禁用。
4. **确认不是隐身模式**：
   ```bash
   defaults read com.ameba.SwiftBar StealthMode
   ```
   若结果是 `1`，执行：
   ```bash
   defaults write com.ameba.SwiftBar StealthMode -bool false
   pkill -x SwiftBar; open -a SwiftBar
   ```

---

## 踩坑记录（AI 接手此项目时必读）

### 坑 1：Codebuddy `/billing/` 接口的 session 是一次性 token ⚠️

这是最核心的坑，花了大量时间排查。

`tencent.sso.codebuddy.cn` 的 `/billing/` 路径有特殊安全机制：**每个 session 只允许成功调用一次**。调用后服务端响应的 `Set-Cookie` 会把 session 清空（`session=; Path=/billing; Max-Age=0`），该 session 对 `/billing/` 路径永久失效。

**表现**：手动 curl 一次成功（200），下一次用完全相同的 cookie 就 401。

**走过的错误方向**（不要重蹈）：
- 以为是 Python urllib 发请求方式有问题 → 不是，curl 也一样
- 以为需要先 GET HTML 页面让服务端续签 session → 不行，HTML 页面不触发 session 轮换
- 以为从 Edge Cookie DB 解密出来的 session 可以多次用 → 解密逻辑没问题，但浏览器自身访问页面时已消耗一次
- 以为服务端会 rotate session（每次响应下发新 session）→ 只对 `/billing/` 路径做清空，不下发新的
- 以为换用 `KEYCLOAK_IDENTITY` JWT 或 `KEYCLOAK_SESSION` 直接换 billing session → 这两个 token 也已过期（登录后浏览器不再更新 cookie DB）

**根本原因**：浏览器通过 Keycloak silent refresh（基于 localStorage 里的 refresh token）在后台静默获取新 session 再调 `/billing/`，整个流程在内存里完成，不经过 cookie DB。脚本从 cookie DB 拿到的永远是"旧"的 session。

**正确方案**：AppleScript 在 Edge 浏览器内部执行同步 XHR，借用浏览器完整的认证上下文。浏览器自动处理 Keycloak 刷新，脚本完全透明。

### 坑 2：AppleScript 执行 JavaScript 只能用同步 XHR

```javascript
// ❌ 这样不行，AppleScript 拿到的是 Promise 对象字符串
async function() { return await fetch(...) }

// ✅ 必须用同步 XHR（第三个参数 false = 同步）
var xhr = new XMLHttpRequest();
xhr.open('POST', '/billing/meter/get-enterprise-user-usage', false);
xhr.setRequestHeader('Content-Type', 'application/json');
xhr.setRequestHeader('x-enterprise-id', 'etahzsqej0n4');
xhr.send('{}');
xhr.status + '|' + xhr.responseText;
```

### 坑 3：Codebuddy API 必须带 `x-enterprise-id` header

只有 cookie 不够，缺 `x-enterprise-id` 会 401，不会有任何提示说缺这个 header。

该值是你的企业 ID，从浏览器 Network 里找 `get-enterprise-user-usage` 请求的 Request Headers 里复制。不同企业账号值不同。

### 坑 4：WOA 的前端域名和 API 域名不同，XHR 必须在正确 tab 执行

- 前端地址：`https://tokens.woa.com`（用这个 tab 做 XHR 会跨域失败）
- 实际 API：`https://tokens-nbyxw43y.app.with.woa.com`（必须在这个 tab 里执行 XHR）

脚本会匹配 URL 包含 `tokens-nbyxw43y` 的 tab，找不到则自动打开并等待 4 秒。

### 坑 5：WOA 内网服务用自签名 SSL 证书

直接 Python HTTP 请求会 SSL 证书验证失败。脚本里必须关闭验证：

```python
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE
```

**不可删除**。SwiftBar 环境下证书路径与终端不同，即使终端可以正常访问，SwiftBar 里也会失败。

### 坑 6：SwiftBar shebang 必须用绝对路径

```python
#!/opt/homebrew/bin/python3   # ✅
#!/usr/bin/env python3         # ❌ SwiftBar 的 PATH 不含 Homebrew，env 找不到
```

### 坑 7：Edge Cookie DB 的解密方式（如需直接读 cookie）

macOS 上 Edge/Chrome cookie 加密方式是 AES-128-CBC（不是 AES-GCM），前缀 `v10`：

```python
import hashlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# 密钥：从 Keychain 取密码，PBKDF2-SHA1，1003 次迭代，16 字节
result = subprocess.run(["security", "find-generic-password", "-w", "-s", "Microsoft Edge Safe Storage"], ...)
pwd = result.stdout.strip().encode('utf-8')
key = hashlib.pbkdf2_hmac('sha1', pwd, b'saltysalt', 1003, dklen=16)

# IV：固定 16 个空格
iv = b' ' * 16

# 解密
payload = encrypted_value[3:]  # 去掉 v10 前缀
raw = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor().update(payload) + ...

# 去 PKCS7 padding：最后一个字节就是 padding 长度
pad_len = raw[-1]
unpadded = raw[:-pad_len]

# Session 值格式：base64url|timestamp|base64url，用正则提取
import re
m = re.search(r'([A-Za-z0-9_\-]+\|\d{10}\|[A-Za-z0-9_\-]+)', unpadded.decode('latin-1'))
session_value = m.group(1)
```

> 注意：解密方式本身没问题，但解出来的 session 对 `/billing/` 路径是一次性的（见坑 1），实际上靠这个方式无法持续调用。代码里保留只作降级 fallback。

### 坑 8：SwiftBar 菜单灰色文字无法通过 `color=` 覆盖

SwiftBar 遵循 macOS 原生菜单规范，没有关联 action 的 item 会被系统自动置灰，`color=` 参数无效。这是 OS 级行为，不是 bug，无法绕过。解决方案是给每个纯展示行加上 `bash=/usr/bin/true terminal=false`（NOOP）。

### 坑 9：`osascript -e` 在 SwiftBar 环境下不可靠 ⚠️

通过 `-e` 参数直接传递 AppleScript 代码给 `osascript`，在终端正常执行，但在 SwiftBar 的子进程环境中会因 shell 转义问题静默失败（returncode=0 但 stdout 为空，或报 script error）。

**正确方案**：将 AppleScript 代码先写入临时 `.scpt` 文件，再用 `osascript <file.scpt>` 执行：

```python
import tempfile
tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.scpt', delete=False)
tmp.write(applescript)
tmp.close()
result = subprocess.run(["osascript", tmp.name], capture_output=True, text=True, timeout=20)
```

### 坑 10：AppleScript 字符串内嵌入 JSON 会破坏解析

在 AppleScript 的 `execute targetTab javascript "..."` 中，如果 JS 代码包含 JSON 对象字面量（带双引号和花括号），AppleScript 解析器会将 `{` / `"` 当作自己的语法符号，导致 "预期是行的结尾等等，却找到 '{'" 错误。

错误示例（会崩溃）：
```javascript
// AppleScript 看到 { 和 " 后解析失败
xhr.send({"startTime": "2026-04-09", ...})
```

正确做法 — 用 JS 单引号 key 构建对象，或用转义后的字符串变量：
```javascript
// 方案 A：单引号 key（属性值不含引号时可用）
var _b = {startTime: '2026-04-09', endTime: '2026-04-09', pageNum: 1, pageSize: 10};
xhr.send(JSON.stringify(_b));

// 方案 B：字符串变量 + 反斜杠转义双引号
var _b = "{\"startTime\": \"2026-04-09\"}";
```

> **原则**：任何传入 `execute javascript "..."` 的 JS 代码中，不能出现未转义的 `"` 和 `{` 组合。

### 坑 11：不同 CB 接口的返回结构不一致

Codebuddy 同一套 `/billing/meter/` 下面的接口，返回数据结构的字段名不同：

| 接口 | 返回路径 |
|------|----------|
| `get-enterprise-user-usage`（月度） | `data.credit`, `data.limitNum`（扁平） |
| `get-user-daily-usage`（每日） | `data.data[].credit`, `data.data[].date`（嵌套，注意不是 `data.records`） |

接入新接口时必须先用 curl 或 Edge Console 确认实际返回结构，不能假设。

### 坑 12：修改源码后必须同步到 SwiftBar 插件目录

SwiftBar 运行的是 `~/.swiftbar-plugins/tokens.3m.py`（部署副本），**不是项目源码目录的文件**。

终端测试用源码目录跑没问题，但菜单栏里永远是旧版本。

每次改完代码后必须手动同步：
```bash
PLUGIN_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo $HOME/.swiftbar-plugins)"
cp tokens.3m.py "$PLUGIN_DIR/tokens.3m.py"
# 然后 SwiftBar 自动刷新，或点菜单中的「刷新」
```

### 坑 13：进度条字符在等宽字体外的对齐问题

SwiftBar 默认使用系统等宽字体渲染，但 `█`（填充）和 `░`（空白）在某些字体下视觉宽度不同，导致进度百分比不同时整条进度条长短不一。

**解决方案**：在需要精确对齐的行上加 `font=Menlo` 参数强制使用 Menlo 等宽字体：
```
print(f"{label}  {bar}  ... | ansi=true size=13 font=Menlo")
```

### 坑 14：CJK 标签宽度计算在 SwiftBar 中无效

Python 端用 `unicodedata.east_asian_width()` 计算中文字符占 2 格、英文占 1 格来动态补空格，逻辑完全正确，但 SwiftBar 使用的是 macOS 系统等宽字体，其 CJK 字符宽度比例与 Python 计算的不一致。

**解决方案**：放弃动态计算，直接硬编码空格数（如 `CC进度  `、`CB进度  `）确保视觉效果一致。

---

## 手动更新 Cookie（降级方案）

Edge 未开启或未登录时，插件降级为直接 HTTP 请求，需要手动提供 cookie。

**WOA cookie**（存 Keychain）：
```bash
security delete-generic-password -s tokens-woa -a cookie 2>/dev/null
security add-generic-password -s tokens-woa -a cookie -w "<粘贴cookie值>"
```

**Codebuddy cookie**（存文件）：
```bash
echo "<粘贴cookie值>" > ~/.config/tokens-woa/cb_cookie
chmod 600 ~/.config/tokens-woa/cb_cookie
```

获取方式：浏览器登录 → F12 → Network → 找对应域名任意请求 → Request Headers → 复制 `Cookie:` 后面的完整值。

> **注意**：Codebuddy 的 cookie 用一次就失效（见坑 1），手动方式每次只能用一次，不建议依赖。

---

## 修改后部署

```bash
PLUGIN_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo "$HOME/.swiftbar-plugins")"
cp tokens.3m.py "$PLUGIN_DIR/tokens.3m.py"
open "swiftbar://refreshplugin?name=tokens"
```

终端测试：

```bash
./tokens.3m.py
```

输出第一行是菜单栏标题，`---` 后是下拉内容，符合 SwiftBar/xbar 插件协议。
