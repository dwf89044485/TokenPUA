# Token PUA — 项目规范

## 项目定位

macOS 菜单栏工具，实时显示 Token 额度使用进度，帮助用户把额度花完不浪费。基于 SwiftBar 插件体系。

术语约定：**CC = WOA 渠道（¥ 消耗）**。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 运行环境 | macOS (Apple Silicon) |
| 语言 | Python 3（`install.sh` 自动检测本机路径） |
| 菜单栏框架 | SwiftBar |
| 认证存储 | 文件存储 `~/.config/tokens-woa/`（无 Keychain，避免弹窗） |
| API | `https://token.woa.com`（内网，Cookie 认证） |

---

## 文件结构

```
Token-PUA/
├── tokens.3m.py     # SwiftBar 插件主脚本（单文件，修改后需部署）
├── install.sh       # 一键安装脚本（支持本地和远程模式）
├── README.md        # GitHub 项目门面
├── GUIDE.md         # AI 安装指引（对话脚本 + 踩坑记录）
├── CLAUDE.md        # 本文，开发约束
└── .gitignore
```

**部署位置：** 以 `defaults read com.ameba.SwiftBar PluginDirectory` 为准（默认 `~/.swiftbar-plugins/tokens.3m.py`，`install.sh` 会自动识别并部署）

**用户凭证与缓存（不进 git）：**
- 模式标记: `~/.config/tokens-woa/mode`（`auto` 或 `manual`）
- CC Cookie: `~/.config/tokens-woa/cc_cookie` (chmod 600)
- CC 数据缓存: `~/.config/tokens-woa/cache.json`

---

## 架构概览

`tokens.3m.py` 内部分区（单文件，SwiftBar 要求）：

| 模块 | 职责 |
|------|------|
| `CredStore` | 凭证存储（纯文件，无 Keychain） |
| `BrowserCookie` | 从 Edge/Chrome Cookie DB 自动提取 CC cookie（仅 auto 模式） |
| `ApiClient` | CC API 客户端（HTTP GET + Cookie） |
| `AuthManager` | CC 认证流程编排（自动登录、刷新、按模式分流） |
| `Pacing` | 工作日 pacing 计算 |
| `UI` | SwiftBar 菜单渲染 |

**命令行入口：**
- `tokens.3m.py` 无参数：正常刷新（SwiftBar 调用）
- `tokens.3m.py --setup` / `--login`：初始化 CC 登录（install.sh 调用）
- `tokens.3m.py --set-cookie`：从 stdin 读取 Cookie 并保存（手动模式）
- `tokens.3m.py --prompt-cookie`：弹出 GUI 输入框让用户输入 Cookie（手动模式）

---

## API 接口

Base URL: `https://token.woa.com`

| 接口 | 用途 | 认证方式 | 当前使用 |
|------|------|----------|----------|
| `GET /api/query-quota?platform=...` | 月度额度查询 | Cookie | ✅ 核心 |
| `GET /api/usage-summary?...` | 各模型用量汇总（月/日） | Cookie | ✅ |
| `GET /api/usage-details?...` | 每日用量明细 | Cookie | ✅ 今日消耗 + 近期记录 |

认证方式: auto 模式从浏览器 Cookie DB 自动提取；manual 模式使用用户手动提供的 cookie 文件。

---

## 核心算法

**Pacing（工作日制）：**
- 按工作日（周一至周五）计算日均消耗和目标日均
- `ratio = 实际日均 / 理想日均` 决定状态（加速/完美/放缓）
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
- `install.sh` 会自动：识别 PluginDirectory、解除禁用状态、重启并刷新 SwiftBar
- **AppleScript 必须写临时 .scpt 文件执行**，不能用 `osascript -e "..."`（SwiftBar 子进程 shell 转义会破坏代码）

### 配置项

`tokens.3m.py` 顶部 Config 区域：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `BASE_URL` | API 基础地址 | `https://token.woa.com` |
| `PLATFORMS` | 统计的产品平台 | `all` |
| `DASHBOARD_URL` | 菜单「打开 Token 看板」跳转地址 | `https://token.woa.com/?product=codebuddy` |

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
