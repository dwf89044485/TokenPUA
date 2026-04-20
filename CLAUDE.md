# Token PUA — 项目规范

## 项目定位

macOS 菜单栏工具，实时显示每月 Token 额度使用进度，帮助用户把额度花完不浪费。基于 SwiftBar 插件体系。

术语约定：**CC = WOA 渠道（美元消耗）**，**CB = Codebuddy 渠道（token 消耗，100 积分 = $1 统一为美元显示）**。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 运行环境 | macOS (Apple Silicon) |
| 语言 | Python 3（`install.sh` 自动检测本机路径） |
| 菜单栏框架 | SwiftBar |
| CB helper | Node.js + `agent-browser` + launchd |
| 认证存储 | 文件存储 `~/.config/tokens-woa/`（无 Keychain，避免弹窗） |
| API | `https://tokens-nbyxw43y.app.with.woa.com` (内网，Cookie 认证) |

---

## 文件结构

```
Token-PUA/
├── tokens.3m.py     # SwiftBar 插件主脚本（源码，修改后需部署）
├── cb_helper.py     # CB 浏览器自动化 helper（后台刷新）
├── install.sh       # 一键安装脚本
├── README.md        # 用户使用说明
└── .gitignore
```

**部署位置：** 以 `defaults read com.ameba.SwiftBar PluginDirectory` 为准（默认 `~/.swiftbar-plugins/tokens.3m.py`，`install.sh` 会自动识别并部署）

**用户凭证与缓存（不进 git）：**
- CC Cookie: `~/.config/tokens-woa/cc_cookie` (chmod 600)
- CB Cookie: `~/.config/tokens-woa/cb_cookie` (chmod 600，仅作 fallback)
- CC 数据缓存: `~/.config/tokens-woa/cache.json`
- CB helper 缓存: `~/.config/tokens-woa/cb_helper_cache.json`
- CB helper 日志: `~/.config/tokens-woa/logs/`

---

## 架构概览

`tokens.3m.py` 内部分区（单文件，SwiftBar 要求）：

| 模块 | 职责 |
|------|------|
| `CredStore` | 凭证存储（纯文件，无 Keychain） |
| `BrowserCookie` | 从 Edge/Chrome Cookie DB 自动提取 CC cookie（CB 仅作 fallback） |
| `CCClient` | CC API 客户端（HTTP GET + Cookie） |
| `AuthManager` | CC 认证流程编排（自动登录、刷新、重试） |
| `Pacing` | 工作日 pacing 计算 |
| `UI` | SwiftBar 菜单渲染 |

`cb_helper.py` 负责：
- 复用 `agent-browser` 持久 profile `~/.config/tokens-woa/agent-browser-profile`
- 首次登录时拉起可见浏览器窗口
- 登录后后台抓取 CB 月/日用量
- 将结果写入 `cb_helper_cache.json`
- 由 launchd 周期执行刷新

**命令行入口：**
- `tokens.3m.py` 无参数：正常刷新（SwiftBar 调用）
- `tokens.3m.py --setup`：初始化 CC（install.sh 调用）
- `cb_helper.py`：后台刷新 CB 数据
- `cb_helper.py --interactive`：可见窗口登录/修复 CB 会话

---

## API 接口

Base URL: `https://tokens-nbyxw43y.app.with.woa.com`

| 接口 | 用途 | 认证方式 | 当前使用 |
|------|------|----------|----------|
| `GET /api/usage-summary?...` | 各模型用量汇总（月/日） | Cookie | ✅ CC 核心 |
| `POST /billing/meter/get-enterprise-user-usage` | CB 月度积分额度 | helper 内浏览器自动化请求 | ✅ CB 月度 |
| `POST /billing/meter/get-user-daily-usage` | CB 每日积分消耗 | helper 内浏览器自动化请求 | ✅ CB 日额度 |

Platform 参数: `codebuddy,with,codebuddy-code,codebuddy-cli,codex-internal,xcode`

认证方式: CC 渠道从浏览器 Cookie DB 自动提取 cookie，HTTP 请求携带；CB 渠道通过 `cb_helper.py` 在 `agent-browser` 会话中调用接口，结果写入本地 cache，SwiftBar 再读取 cache 展示。

---

## 首次使用引导（AI 接手时必读）

当新用户拿到项目时，AI 应直接执行 `bash install.sh`，它会自动完成所有配置：

1. **执行 `bash install.sh`**：自动安装 SwiftBar、Python、Node.js、`agent-browser`
2. **自动部署**：部署 `tokens.3m.py` 与 `cb_helper.py`
3. **自动初始化 CC**：install.sh 调用 `tokens.3m.py --setup` 完成 CC 登录
4. **自动初始化 CB**：install.sh 调用 `cb_helper.py --interactive` 拉起可见浏览器窗口，用户在该窗口完成首次登录
5. **后台刷新**：install.sh 安装 LaunchAgent，后续由 launchd 定期运行 `cb_helper.py`

**关键提醒**：
- 给用户的 URL 永远是 `https://tokens.woa.com`，不要给 `tokens-nbyxw43y.app.with.woa.com`（那是内部 API 域名，用户无法直接访问）
- CC 仍通过浏览器登录态获取；CB 现在通过 helper 会话获取，不需要用户手动复制 Cookie
- 新用户的核心体验应该是：运行一次 `bash install.sh`，按提示完成登录，其余交给后台刷新

---

## 核心算法

**Pacing（工作日制）：**
- 按工作日（周一至周五）计算日均消耗和目标日均
- `ratio = 目标日均 / 当前日均` 决定状态（加速/完美/放缓）
- 月底预测 = 已用 + 当前日均 × 剩余工作日

**状态阈值：**
- ratio > 1.3 → 🟥 加速
- ratio > 1.1 → 🟡 稍加速
- ratio > 0.9 → 🟢 完美
- ratio > 0.7 → 🟡 可放缓
- ratio ≤ 0.7 → 🔵 省着用

---

## 开发规范

### 修改后部署

```bash
PLUGIN_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo "$HOME/.swiftbar-plugins")"
cp tokens.3m.py "$PLUGIN_DIR/tokens.3m.py"
chmod +x "$PLUGIN_DIR/tokens.3m.py"
open "swiftbar://refreshplugin?name=tokens"
```

### 终端测试

```bash
./tokens.3m.py
# 或测试已部署版本：
"$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo "$HOME/.swiftbar-plugins")/tokens.3m.py"
```

输出第一行是菜单栏标题，`---` 之后是下拉菜单内容，符合 SwiftBar/xbar 插件协议。

### SSL

内网 HTTPS 使用自签证书，脚本中通过 `ssl.create_default_context()` + `verify_mode = ssl.CERT_NONE` 跳过验证。不可移除，否则 SwiftBar 环境下 SSL 报错。

### SwiftBar 环境注意事项

- SwiftBar 启动脚本时的 PATH、SSL 证书路径与终端不同
- Shebang 必须是绝对路径（`install.sh` 会自动按本机 Python 重写首行）
- `__pycache__/` 可能导致旧代码缓存，部署后如有异常先删除
- 菜单空白优先检查：`DisabledPlugins` 是否包含 `tokens.3m.py`、`StealthMode` 是否为 `1`
- **修改源码后必须同步到 SwiftBar 插件目录**：SwiftBar 运行的是部署副本（`~/.swiftbar-plugins/tokens.3m.py`），不是源码目录文件。每次改完需 `cp tokens.3m.py "$PLUGIN_DIR/tokens.3m.py"`
- `install.sh` 会自动：识别 PluginDirectory、解除 `tokens.3m.py` 禁用状态、重启并刷新 SwiftBar
- **AppleScript 必须写临时 .scpt 文件执行**，不能用 `osascript -e "..."`（SwiftBar 子进程 shell 转义会破坏代码）
- **AppleScript 的 execute javascript 字符串内不能有未转义的 `{` 和 `"`**，否则 AppleScript 解析器报错。用 JS 单引号 key 构建对象 + `JSON.stringify()` 或反斜杠转义
- **不同 CB 接口返回结构字段名不一致**：`get-enterprise-user-usage` 是扁平 `data.credit`，`get-user-daily-usage` 是嵌套 `data.data[].credit`（注意不是 records）。接入新接口必须先确认实际返回结构

### 配置项

`tokens.3m.py` 顶部 Config 区域：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `BUDGET` | 月度总预算（美元） | `1000.0` |
| `PLATFORMS` | 统计的产品平台 | `codebuddy,with,...` |
| `BASE_URL` | API 基础地址 | `https://tokens-nbyxw43y.app.with.woa.com` |
| `CB_ENTERPRISE_ID` | Codebuddy 企业 ID | `etahzsqej0n4` |
| `CB_TOKEN_LIMIT` | Codebuddy 月度积分上限 | `150000` |
| `CB_POINTS_PER_USD` | 积分→美元换算比 | `100.0` |

---

## 禁止事项

- 不得将 Cookie 值硬编码到代码中
- 不得将 `~/.config/tokens-woa/` 内容提交到 git
- 不得移除 SSL 证书跳过逻辑
- 不得引入 Keychain 依赖（已迁移为纯文件存储以消除弹窗）
- 分发包（zip）不进 git

---

## Git 工作流

solo 开发，master 分支直推。修改后：

```bash
git add <changed-files>
git commit -m "<message>"
```
