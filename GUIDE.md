# TokenPUA — AI 安装指引

## 项目文件

| 文件 | 用途 |
|------|------|
| `tokens.3m.py` | SwiftBar 插件主脚本 |
| `install.sh` | 一键安装脚本 |
| `README.md` | GitHub 项目介绍 |
| `GUIDE.md` | **本文，AI 安装指引** |
| `CLAUDE.md` | 开发约束，二次开发时看 |

---

## 安装前置要求

- macOS（Apple Silicon，已测试 M 系列）
- [Homebrew](https://brew.sh)
- Microsoft Edge 或 Google Chrome（**自动模式**需要，手动模式不需要）
- 公司内网访问权限（WOA 渠道）

---

## AI 操作流程

当用户说「帮我安装 TokenPUA」，**先问用户怎么获取 Cookie**，不要直接执行。

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

如果用户没有本地文件（从 GitHub 远程安装），使用：

```bash
curl -fsSL https://raw.githubusercontent.com/dwf89044485/TokenPUA/master/install.sh -o /tmp/tpua-install.sh && bash /tmp/tpua-install.sh
```

脚本会自动检测并下载所需文件。

### 第三步：执行中告诉用户接下来会看到什么

#### 自动模式

> 好，我现在开始安装。等会儿你会看到一条钥匙串弹窗，内容是：
> **"osascript" wants to access the "Safe Storage" item in your keychain.**
> **请点「始终允许」（Always Allow）**，只点这一次以后就不会再弹了。

安装过程中用户会看到：

```
🔧 Cookie 模式：自动提取
...（安装 Homebrew、SwiftBar、Python、依赖）...
⚠️ 即将弹出钥匙串授权框，请点击「始终允许」
...（浏览器弹出来，如果还没登录就手动登录一下）...
✅ 安装完成
```

之后菜单栏就会出现额度图标，以后每次刷新都是全自动的。

#### 手动模式

> 好，我现在开始安装。等会儿会提示你粘贴 Cookie，你现在就可以准备：
>
> 1. 浏览器打开 `token.woa.com` 并登录
> 2. 按 `F12` → `Application` → `Cookies`，复制全部内容
> 3. 等脚本提示"粘贴 Cookie"时贴进去

安装过程中用户会看到：

```
🔧 Cookie 模式：手动输入
...（安装 Homebrew、SwiftBar、Python，跳过 cryptography）...
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

## 常见问题排查

### 菜单栏空白 / 没内容时

1. **终端测试**：

   ```bash
   "$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo "$HOME/.swiftbar-plugins")/tokens.3m.py"
   ```

   或用 venv Python：

   ```bash
   ~/.swiftbar-venv/bin/python3 ~/.swiftbar-plugins/tokens.3m.py
   ```

2. **确认插件目录**：

   ```bash
   defaults read com.ameba.SwiftBar PluginDirectory
   ```

   确认该目录下存在 `tokens.3m.py`。

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

## 踩坑记录

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

### 坑 8：管理环境 Python 的原生扩展签名冲突 ⚠️

如果本机安装了 WorkBuddy、asdf、pyenv、conda 等管理环境的 Python，`pip install cryptography` 装的原生 `.so` 文件会被这些环境签名，SwiftBar 加载时会因 **Team ID 不一致**而拒绝加载：

```
ImportError: dlopen(..._rust.abi3.so, 0x0002): code signature not valid for use in process:
mapping process and mapped file (non-platform) have different Team IDs
```

**`install.sh` 已自动处理**：脚本会优先使用系统 Python（`/usr/bin/python3`）或 Homebrew Python，拒绝管理环境 Python；同时创建 `~/.swiftbar-venv` 隔离安装依赖，确保签名兼容。

如果手动排查，检查当前 shebang 是否指向管理环境：

```bash
head -1 "$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo ~/.swiftbar-plugins)/tokens.3m.py"
```

如果路径含 `.workbuddy`、`.asdf`、`pyenv`、`conda`、`venv` 等，用以下命令修复：

```bash
# 用系统/Homebrew Python 创建独立 venv
/usr/bin/python3 -m venv ~/.swiftbar-venv
~/.swiftbar-venv/bin/pip install cryptography

# 更新 shebang
PLUGIN_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo ~/.swiftbar-plugins)"
sed -i '' "1s|.*|#!$HOME/.swiftbar-venv/bin/python3|" "$PLUGIN_DIR/tokens.3m.py"
```

---

## 修改后部署

修改 `tokens.3m.py` 源码后需要同步到 SwiftBar：

```bash
PLUGIN_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo "$HOME/.swiftbar-plugins")"
VENV_PYTHON="$HOME/.swiftbar-venv/bin/python3"

# 1. 复制插件到部署目录
cp tokens.3m.py "$PLUGIN_DIR/tokens.3m.py"

# 2. 确保 shebang 指向 venv Python
if [ -x "$VENV_PYTHON" ]; then
    sed -i '' "1s|.*|#!${VENV_PYTHON}|" "$PLUGIN_DIR/tokens.3m.py"
    chmod +x "$PLUGIN_DIR/tokens.3m.py"
fi

# 3. 刷新 SwiftBar
open "swiftbar://refreshplugin?name=tokens"
```

终端测试：

```bash
# 用 venv Python 运行（与 SwiftBar 环境一致）
~/.swiftbar-venv/bin/python3 tokens.3m.py
```
