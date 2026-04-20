# TokenPUA

macOS 菜单栏工具，实时显示每月 Token 额度使用进度，帮你把额度花完不浪费。

同时接入两个渠道：
- **CC（WOA 渠道）**（`tokens.woa.com`）：按模型展示美元花费，支持工作日 pacing 计算
- **CB（Codebuddy 渠道）**（`tencent.sso.codebuddy.cn`）：月度 token 积分用量（100 积分 = $1，统一以美元显示）

缩写约定：**CC = WOA 渠道（美元消耗）**，**CB = Codebuddy 渠道（token 消耗 → 按 100 积分 = $1 统一为美元显示）**。

---

## 效果

菜单栏显示：`🟡 $125/$135 · 稍加速`

下拉内容：
```
月额度（$1 = 100积分）
时间进度  ██████░░░░░░░░░░░░░░  30%  9/30天
CC进度    █████░░░░░░░░░░░░░░░  28%  $283/$1000
CB进度    ██░░░░░░░░░░░░░░░░░░  13%  $202/$1500
---
日额度（20:35更新）
时间进度  ████████████████░░░░  86%  20:35/24:00
CC进度    ████████████████████  120%  $58/$48
CB进度    ████████████████░░░░  82%   $71/$87
---
打开 CC Token 看板
打开 CB Token 看板
```

- 菜单栏标题 = 今日 CC + CB 已用之和 / 日均之和
- CC = WOA 渠道（美元消耗），CB = Codebuddy 渠道（100 积分 = $1）
- 进度按工作日（周一至周五）pacing 计算

---

## 安装

一键安装：

```bash
bash install.sh
```

安装脚本现在会自动完成：
- 安装 SwiftBar、Python 依赖、Node.js
- 安装并初始化 `agent-browser`
- 部署 `tokens.3m.py` 和 `cb_helper.py`
- 安装 `cb_helper.py` 的后台 LaunchAgent（自动刷新 CB 数据）
- 初始化 CC 登录
- 拉起一次可见的 CB 登录窗口，帮助完成首次登录
- 重启并刷新 SwiftBar

### 首次使用流程

1. 执行 `bash install.sh`
2. 按提示完成 **CC 登录**
3. 如果弹出 `agent-browser` 浏览器窗口，在该窗口里完成 **CB 登录**
4. 之后 CB 数据会由后台 helper 自动刷新，SwiftBar 直接读取 cache 显示

### 后台刷新

CB 现在使用 `cb_helper.py` + `agent-browser` + `launchd`：
- helper 会把结果写入 `~/.config/tokens-woa/cb_helper_cache.json`
- 后台任务会定期刷新 cache
- SwiftBar 插件只负责显示 cache，不再把 CB 主体验建立在每次刷新直接跑 AppleScript 上

### 手动触发 CB helper（排查时用）

```bash
python3 cb_helper.py --interactive
```

用途：
- 首次登录 CB
- 会话过期后重新登录
- 手动验证 helper 是否正常抓到数据

### 手动部署（备选）

```bash
PLUGIN_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo "$HOME/.swiftbar-plugins")"
cp tokens.3m.py "$PLUGIN_DIR/tokens.3m.py"
cp cb_helper.py "$PLUGIN_DIR/cb_helper.py"
open "swiftbar://refreshplugin?name=tokens"
```

---

## 自定义配置

修改 `tokens.3m.py` 顶部 Config 区域：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `BUDGET` | CC 月度预算（美元） | `1000.0` |
| `PLATFORMS` | CC 统计的产品平台 | `codebuddy,with,...` |
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
- Microsoft Edge 或 Google Chrome（用于 CC 登录态获取）
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

**根本原因**：浏览器通过 Keycloak silent refresh（基于 localStorage 里的 refresh token）在后台静默获取新 session 再调 `/billing/`，整个流程在内存里完成，不经过 cookie DB。脚本从 cookie DB 拿到的永远是"旧"的 session。

**当前正式方案**：CB 不再依赖主插件每次刷新直接跑 AppleScript，而是改为 `cb_helper.py` + `agent-browser` + 后台 cache。登录完成后由 helper 定期刷新数据，SwiftBar 只读 cache。

### 坑 2：AppleScript 执行 JavaScript 只能用同步 XHR（旧 CB 方案，现已非主路径）

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

### 坑 4：WOA 的前端域名和 API 域名不同

- 前端地址：`https://tokens.woa.com`（用这个 tab 做 XHR 会跨域失败）
- 实际 API：`https://tokens-nbyxw43y.app.with.woa.com`（CC 走 HTTP + Cookie，不依赖浏览器 XHR）

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

### 坑 7：Edge Cookie DB 的解密方式

macOS 上 Edge/Chrome cookie 加密方式是 AES-128-CBC（不是 AES-GCM），前缀 `v10`：

- 密钥：从 Keychain 取 "Safe Storage" 密码，PBKDF2-SHA1，1003 次迭代，16 字节
- IV：固定 16 个空格
- 去 PKCS7 padding：最后一个字节就是 padding 长度

> 注意：解出来的 session 对 `/billing/` 路径是一次性的（见坑 1），实际上靠这个方式无法持续调用 CB。代码里保留只作 CC cookie 提取和 CB fallback。

### 坑 8：SwiftBar 菜单灰色文字无法通过 `color=` 覆盖

没有关联 action 的 item 会被系统自动置灰。解决方案是给每个纯展示行加上 `bash=/usr/bin/true terminal=false`（NOOP）。

### 坑 9：`osascript -e` 在 SwiftBar 环境下不可靠 ⚠️（旧 CB 方案背景）

**正确方案**：将 AppleScript 代码先写入临时 `.scpt` 文件，再用 `osascript <file.scpt>` 执行。

### 坑 10：AppleScript 字符串内嵌入 JSON 会破坏解析（旧 CB 方案背景）

任何传入 `execute javascript "..."` 的 JS 代码中，不能出现未转义的 `"` 和 `{` 组合。用 JS 单引号 key + `JSON.stringify()` 构建 POST body。

### 坑 11：不同 CB 接口的返回结构不一致

| 接口 | 返回路径 |
|------|----------|
| `get-enterprise-user-usage`（月度） | `data.credit`, `data.limitNum`（扁平） |
| `get-user-daily-usage`（每日） | `data.data[].credit`, `data.data[].date`（嵌套，注意不是 `data.records`） |

### 坑 12：修改源码后必须同步到 SwiftBar 插件目录

SwiftBar 运行的是 `~/.swiftbar-plugins/tokens.3m.py`（部署副本），**不是项目源码目录的文件**。

每次改完代码后必须手动同步：
```bash
PLUGIN_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo $HOME/.swiftbar-plugins)"
cp tokens.3m.py "$PLUGIN_DIR/tokens.3m.py"
```

### 坑 13：进度条字符在等宽字体外的对齐问题

在需要精确对齐的行上加 `font=Menlo` 参数。

### 坑 14：CJK 标签宽度计算在 SwiftBar 中无效

放弃动态计算，直接硬编码空格数（如 `CC进度  `、`CB进度  `）确保视觉效果一致。

### 坑 15：避免 Keychain 弹窗 ⚠️

`security find-generic-password` 会触发系统弹窗。v2 已将 CC/CB cookie 改为纯文件存储（`~/.config/tokens-woa/cc_cookie`、`cb_cookie`），不再使用 Keychain 存储自己的凭证。

浏览器 Safe Storage 密钥读取仍需调用 `security`（解密 cookie DB 必须），但已添加进程内缓存，同一刷新周期只取一次。

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
