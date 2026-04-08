# Token PUA — 项目规范

## 项目定位

macOS 菜单栏工具，实时显示每月 Token 额度使用进度，帮助用户把额度花完不浪费。基于 SwiftBar 插件体系。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 运行环境 | macOS (Apple Silicon) |
| 语言 | Python 3 (Homebrew `/opt/homebrew/bin/python3`) |
| 菜单栏框架 | SwiftBar |
| 认证存储 | macOS Keychain (`security` CLI) + `~/.config/tokens-woa/cookie` 文件备用 |
| API | `https://tokens-nbyxw43y.app.with.woa.com` (内网，Cookie 认证) |

---

## 文件结构

```
Token-PUA/
├── tokens.3m.py     # SwiftBar 插件主脚本（源码，修改后需部署）
├── install.sh       # 一键安装脚本
├── README.md        # 用户使用说明
└── .gitignore
```

**部署位置：** `~/.swiftbar-plugins/tokens.3m.py`（install.sh 负责复制）

**用户凭证（不进 git）：**
- Keychain: service=`tokens-woa`, account=`cookie`
- 文件备用: `~/.config/tokens-woa/cookie` (chmod 600)

---

## API 接口

Base URL: `https://tokens-nbyxw43y.app.with.woa.com`

| 接口 | 用途 | 当前使用 |
|------|------|----------|
| `GET /api/usage-summary?start_date=X&end_date=Y&dimension=personal&platform=...` | 各模型用量汇总 | ✅ 核心 |
| `GET /api/query-quota?platform=codebuddy` | 用量百分比 | 未使用 |
| `GET /api/quota-allocation` | 预算分配详情（总额、各类别） | 未使用 |
| `GET /api/platforms` | 产品类别列表 | 未使用 |
| `GET /api/usage-details?...&page=N&page_size=N` | 逐条使用记录（分页） | 未使用 |
| `GET /api/user` | 当前用户信息 | 未使用 |
| `GET /api/team-tokens` | 团队 token | 未使用 |

Platform 参数: `codebuddy,with,codebuddy-code,codebuddy-cli,codex-internal,xcode`

认证方式: 请求 Header 携带 `Cookie: <完整cookie值>`，内网 SSO 登录后从浏览器 DevTools 获取。

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
cp tokens.3m.py ~/.swiftbar-plugins/tokens.3m.py
open "swiftbar://refreshplugin?name=tokens"
```

### 终端测试

```bash
/opt/homebrew/bin/python3 tokens.3m.py
```

输出第一行是菜单栏标题，`---` 之后是下拉菜单内容，符合 SwiftBar/xbar 插件协议。

### SSL

内网 HTTPS 使用自签证书，脚本中通过 `ssl.create_default_context()` + `verify_mode = ssl.CERT_NONE` 跳过验证。不可移除，否则 SwiftBar 环境下 SSL 报错。

### SwiftBar 环境注意事项

- SwiftBar 启动脚本时的 PATH、SSL 证书路径与终端不同
- Shebang 必须用绝对路径 `#!/opt/homebrew/bin/python3`，不可用 `#!/usr/bin/env python3`
- `__pycache__/` 可能导致旧代码缓存，部署后如有异常先删除

### 配置项

`tokens.3m.py` 顶部 Config 区域：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `BUDGET` | 月度总预算（美元） | `1000.0` |
| `PLATFORMS` | 统计的产品平台 | `codebuddy,with,...` |
| `BASE_URL` | API 基础地址 | `https://tokens-nbyxw43y.app.with.woa.com` |

---

## 禁止事项

- 不得将 Cookie 值硬编码到代码中
- 不得将 `~/.config/tokens-woa/` 或 Keychain 内容提交到 git
- 不得移除 SSL 证书跳过逻辑
- 分发包（zip）不进 git

---

## Git 工作流

solo 开发，master 分支直推。修改后：

```bash
git add <changed-files>
git commit -m "<message>"
```
