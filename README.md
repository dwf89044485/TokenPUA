# TokenPUA

macOS 菜单栏工具，实时显示每月 Token 额度使用进度，帮你把额度花完不浪费。

**CC（WOA 渠道）**：按模型展示美元花费，支持工作日 pacing 计算。

---

## 效果

菜单栏显示：`🟡 $125/$135 · 稍加速`

下拉内容：

```
月额度（$1 = 100积分）
时间进度  ██████░░░░░░░░░░  30%  9/30天
CC进度    █████░░░░░░░░░░  28%  $283/$1000

日额度（20:35更新）
时间进度  ████████████████░░░  86%  20:35/24:00
CC进度    ███████████████████  120%  $58/$48
---
打开 Token 看板
刷新
20:35 更新 | color=#888888 size=11
```

- 菜单栏标题 = 本月已用 / 月度预算
- 进度按工作日（周一至周五）pacing 计算

---

## 快速安装

拿到项目后，在终端执行：

```bash
bash install.sh
```

安装脚本会自动完成：

- 安装 SwiftBar、Python、Python 依赖
- 部署 `tokens.3m.py` 到 SwiftBar 插件目录
- 初始化 CC 登录
- 重启并刷新 SwiftBar

执行完后，菜单栏会出现 TokenPUA 图标。

---

## 首次使用流程

1. 执行 `bash install.sh`
2. 按提示完成 **CC 登录**（浏览器完成）
3. 之后数据会由 SwiftBar 每次刷新时自动拉取

---

## 自定义配置

修改 `tokens.3m.py` 顶部 Config 区域：

| 变量          | 说明          | 默认值      |
| ----------- | ----------- | -------- |
| `BUDGET`    | CC 月度预算（美元） | `1000.0` |
| `PLATFORMS` | CC 统计的产品平台  | `all`    |

---

## 状态含义

| 图标  | 含义  | 触发条件（目标日均 vs 当前日均） |
| --- | --- | ------------------ |
| 🔴  | 加速! | 目标 > 当前 × 1.3      |
| 🟡  | 稍加速 | 目标 > 当前 × 1.1      |
| 🟢  | 完美  | 差距在 ±10% 内         |
| 🟡  | 可放缓 | 目标 < 当前 × 0.9      |
| 🔵  | 省着用 | 目标 < 当前 × 0.7      |

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

### 坑 1：WOA 内网服务用自签名 SSL 证书

直接 Python HTTP 请求会 SSL 证书验证失败。脚本里必须关闭验证：

```python
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE
```

**不可删除**。SwiftBar 环境下证书路径与终端不同，即使终端可以正常访问，SwiftBar 里也会失败。

### 坑 2：SwiftBar shebang 必须用绝对路径

```python
#!/opt/homebrew/bin/python3   # ✅
#!/usr/bin/env python3         # ❌ SwiftBar 的 PATH 不含 Homebrew，env 找不到
```

### 坑 3：Edge Cookie DB 的解密方式

macOS 上 Edge/Chrome cookie 加密方式是 AES-128-CBC（不是 AES-GCM），前缀 `v10`：

- 密钥：从 Keychain 取 "Safe Storage" 密码，PBKDF2-SHA1，1003 次迭代，16 字节
- IV：固定 16 个空格
- 去 PKCS7 padding：最后一个字节就是 padding 长度

### 坑 4：SwiftBar 菜单灰色文字无法通过 `color=` 覆盖

没有关联 action 的 item 会被系统自动置灰。解决方案是给每个纯展示行加上 `bash=/usr/bin/true terminal=false`（NOOP）。

### 坑 5：修改源码后必须同步到 SwiftBar 插件目录

SwiftBar 运行的是 `~/.swiftbar-plugins/tokens.3m.py`（部署副本），**不是项目源码目录的文件**。

每次改完代码后必须手动同步：

```bash
PLUGIN_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo $HOME/.swiftbar-plugins)"
cp tokens.3m.py "$PLUGIN_DIR/tokens.3m.py"
```

### 坑 6：进度条字符在等宽字体外的对齐问题

在需要精确对齐的行上加 `font=Menlo` 参数。

### 坑 7：避免 Keychain 弹窗 ⚠️

`security find-generic-password` 会触发系统弹窗。凭证已改为纯文件存储（`~/.config/tokens-woa/cc_cookie`），不再使用 Keychain 存储自己的凭证。

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
