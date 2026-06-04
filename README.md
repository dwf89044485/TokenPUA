# TokenPUA

macOS 菜单栏工具，实时显示每月 Token 额度使用进度，帮你把额度花完不浪费。

**CC（WOA 渠道）**：按模型展示花费（¥），支持工作日 pacing 计算。

---

## 效果

菜单栏显示：`🟢 ¥283/¥1000 · 完美`

下拉内容：

```
月进度 | size=11 color=#888888
 额度  █████░░░░░░░░  28%  ¥283/¥1000 | ansi=true size=12 font=Menlo bash=/usr/bin/true terminal=false
 时间  ██████░░░░░░░░  30%  9/30天 | ansi=true size=12 font=Menlo bash=/usr/bin/true terminal=false
---
日进度 | size=11 color=#888888
 额度  ████████████████░░░  86%  ¥41.5/¥48 | ansi=true size=12 font=Menlo bash=/usr/bin/true terminal=false
 时间  ███████████████████░  92%  22:05/24:00 | ansi=true size=12 font=Menlo bash=/usr/bin/true terminal=false
---
近期消费记录 | size=11 color=#888888
06-04 22:01  ¥21.35    Opus        12,345  帮我写一段...
---
打开 Token 看板 | href=https://token.woa.com/?product=codebuddy | size=11
刷新 | refresh=true | length=80
3分钟前更新 | color=#888888 size=11
```

- 菜单栏标题 = 状态图标 + 本月已用/月度额度 + 状态文字
- 进度按工作日（周一至周五）pacing 计算
- 底部显示近期高消费记录（时间 / 金额 / 模型 / Token 数 / 用户消息）

---

## AI 辅助设置（AI 接手时必读）

当用户说「帮我启动项目」，**先问用户怎么获取 Cookie**，不要直接执行：

---

### 第一步：问用户

```
我：我有两种方式获取登录态，你选哪种？

方案 1：我自动从浏览器拿          【推荐 - 大多数人选这个】
  ✅ 你什么都不用做，我帮你从 Edge/Chrome 里提取
  ✅ Cookie 过期后自动刷新，后续不用再管
  ⚠️ 需要装一个 Python 包
  ⚠️ 会弹一次钥匙串授权框（点「始终允许」就行，只弹一次）

方案 2：你手动复制 Cookie 给我
  ✅ 不需要装额外东西，不会弹任何系统框
  ✅ 适合隐私敏感的人
  ⚠️ 你需要去浏览器 DevTools 复制 Cookie 粘贴给我
  ⚠️ Cookie 过期后（几周到一个月）要重新复制一次

你选哪个？
```

### 第二步：根据回答执行

| 用户选了 | 你执行 |
|---------|--------|
| 方案 1 | `bash install.sh --auto` |
| 方案 2 | `bash install.sh --manual` |

### 第三步：执行中告诉用户接下来会看到什么

#### 如果选了自动模式（方案 1），跟用户说：

> 好，我现在开始安装。等会儿你会看到一条钥匙串弹窗，内容是：
> **"osascript" wants to access the "Safe Storage" item in your keychain.**
> **请点「始终允许」（Always Allow）**，只点这一次以后就不会再弹了。

安装过程中用户会看到：

```
🔧 Cookie 模式：自动提取
...（安装 SwiftBar、Python、依赖）...
⚠️ 即将弹出钥匙串授权框，请点击「始终允许」
...（浏览器弹出来，如果还没登录就手动登录一下）...
✅ 安装完成
```

之后菜单栏就会出现额度图标，以后每次刷新都是全自动的。

#### 如果选了手动模式（方案 2），跟用户说：

> 好，我现在开始安装。等会儿会提示你粘贴 Cookie，你现在就可以准备：
> 1. 浏览器打开 `token.woa.com` 并登录
> 2. 按 `F12` → `Application` → `Cookies`，复制全部内容
> 3. 等脚本提示"粘贴 Cookie"时贴进去

安装过程中用户会看到：

```
🔧 Cookie 模式：手动输入
...（安装 SwiftBar、Python，跳过 cryptography）...
请手动输入 CC Cookie：
获取方式：在浏览器登录 token.woa.com 后，
打开开发者工具 → Application → Cookies → 复制全部 Cookie

粘贴 Cookie: [用户粘贴]
✅ Cookie 已保存
✅ 安装完成
```

### 后续 Cookie 过期了怎么办

| 自动模式 | 手动模式 |
|---------|---------|
| 什么都不用做，菜单栏自动恢复 | 点击菜单栏「重新输入 Cookie」，粘贴新的 → 自动恢复 |

---

## 快速安装

## 快速安装

拿到项目后，在终端执行：

```bash
bash install.sh
```

脚本会先询问 **Cookie 获取方式**（也可直接带参数跳过询问）：

| 方式           | 适合人群        | 说明                                              |
| ------------ | ----------- | ----------------------------------------------- |
| **自动提取（推荐）** | 大多数用户       | 从 Edge/Chrome 自动读取 Cookie，无需手动操作；Cookie 过期后自动刷新 |
| **手动输入**     | 隐私敏感 / 无浏览器 | 不读取浏览器，无 Keychain 弹窗；Cookie 过期后需重新填入            |

```bash
bash install.sh --auto      # 直接以自动模式安装
bash install.sh --manual    # 直接以手动模式安装
```

安装脚本会自动完成：

- 安装 SwiftBar、Python、Python 依赖（自动模式需要 `cryptography`，手动模式不需要）
- 部署 `tokens.3m.py` 到 SwiftBar 插件目录（自动修正 shebang）
- **自动模式**：拉起浏览器完成 CC 登录，自动保存 Cookie
- **手动模式**：提示用户粘贴从浏览器复制的 Cookie
- 启动 SwiftBar

执行完后，菜单栏会出现 TokenPUA 图标。

### 手动获取 Cookie 的方式

1. 浏览器打开 `https://token.woa.com` 并登录
2. 按 `F12` 打开开发者工具 → `Application` → `Cookies`
3. 复制所有 Cookie（格式：`name=value; name2=value2; ...`）
4. 在脚本提示时粘贴进去

---

## 首次使用流程

1. 执行 `bash install.sh`（选择自动或手动模式）
2. **自动模式**：脚本自动从浏览器提取 Cookie，无需操作
   **手动模式**：按提示粘贴 Cookie
3. 成功后菜单栏即时显示额度进度
4. 之后数据由 SwiftBar 每次刷新时自动拉取

Cookie 过期后：

- **自动模式**：脚本自动从浏览器重新提取，无需操作
- **手动模式**：点击菜单栏「重新输入 Cookie」，重新粘贴

---

## 状态含义

| 图标  | 含义  | 触发条件（实际日均 / 理想日均） |
| --- | --- | ----------------- |
| 🟥  | 加速! | ratio > 1.3       |
| 🟡  | 稍加速 | ratio > 1.1       |
| 🟢  | 完美  | 0.9 < ratio ≤ 1.1 |
| 🟡  | 可放缓 | 0.7 < ratio ≤ 0.9 |
| 🔵  | 省着用 | ratio ≤ 0.7       |

ratio = 本月至今实际日均花费 / 本月理想日均花费（按工作日计算）

当剩余工作日 ≤ 5 且剩余额度 > ¥100 时，会显示提示建议多用 Opus。

---

## 前置要求

- macOS（Apple Silicon，已测试 M 系列）
- [Homebrew](https://brew.sh)
- Microsoft Edge 或 Google Chrome（**自动模式**需要，手动模式不需要）
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

`install.sh` 会自动将本机 Python 路径写入 shebang，不需要手动修改。

### 坑 3：Edge/Chrome Cookie DB 的解密方式

macOS 上 Edge/Chrome cookie 加密方式是 AES-128-CBC（不是 AES-GCM），前缀 `v10`：

- 密钥：从 Keychain 取 "Safe Storage" 密码，PBKDF2-SHA1，1003 次迭代，16 字节
- IV：固定 16 个空格
- 去 PKCS7 padding：最后一个字节就是 padding 长度

### 坑 4：SwiftBar 菜单灰色文字无法通过 `color=` 覆盖

没有关联 action 的 item 会被系统自动置灰。解决方案是给每个纯展示行加上 `bash=/usr/bin/true terminal=false`（代码中定义为常量 `NOOP`）。

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

浏览器 Safe Storage 密钥读取仍需调用 `security`（解密 cookie DB 必须，仅自动模式），但已添加进程内缓存，同一刷新周期只取一次。

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
