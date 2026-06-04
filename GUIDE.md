# TokenPUA — AI 安装指引

**本文给 AI 读。** 用户说「根据 GUIDE.md 安装好这个项目」时，AI 按以下步骤执行。

---

## 前置条件

- macOS（Apple Silicon）
- [Homebrew](https://brew.sh)（安装脚本会自动检测安装）
- 浏览器 Edge 或 Chrome（自动模式需要；手动模式不需要）
- 公司内网访问权限

---

## 第一步：获取项目文件

执行以下命令，把安装脚本和插件下载到本地：

```bash
# 创建临时目录
mkdir -p /tmp/tokenpua && cd /tmp/tokenpua

# 下载核心文件
curl -fsSL https://raw.githubusercontent.com/dwf89044485/TokenPUA/master/install.sh -o install.sh
curl -fsSL https://raw.githubusercontent.com/dwf89044485/TokenPUA/master/tokens.3m.py -o tokens.3m.py

chmod +x install.sh tokens.3m.py
```

---

## 第二步：询问用户 Cookie 方式

**先问用户，不要直接执行。**

```
我：我有两种方式获取登录态，你选哪种？

方案 1：我自动从浏览器拿（推荐）
  ✅ 你什么都不用做，我帮你从 Edge/Chrome 里提取
  ✅ Cookie 过期后自动刷新，后续不用再管
  ⚠️ 需要装一个 Python 包
  ⚠️ 会弹一次钥匙串授权框（点「始终允许」就行，只弹一次）

方案 2：你手动复制 Cookie 给我
  ✅ 不需要装额外东西，不会弹任何系统框
  ✅ 适合隐私敏感的人
  ⚠️ 你需要去浏览器 DevTools 复制 Cookie 粘贴给我
  ⚠️ Cookie 过期后要重新复制一次

你选哪个？
```

### 根据回答执行

| 用户选了 | 执行命令 |
|---------|---------|
| 方案 1（自动） | `bash /tmp/tokenpua/install.sh --auto` |
| 方案 2（手动） | `bash /tmp/tokenpua/install.sh --manual` |

---

## 第三步：执行中提示用户

### 自动模式

执行 `--auto` 前先告诉用户：

> 等会儿你会看到一条钥匙串弹窗，内容是：
> **"osascript" wants to access the "Safe Storage" item in your keychain.**
> **请点「始终允许」（Always Allow）**，只点这一次以后不会再弹。

安装过程中用户会看到：

```
🔧 Cookie 模式：自动提取
✅ Homebrew（如果未安装会自动安装）
...
⚠️ 即将弹出钥匙串授权框，请点击「始终允许」
...（浏览器弹出来，如果还没登录就登录一下）...
✅ 安装完成
```

### 手动模式

执行 `--manual` 前先告诉用户：

> 你现在就可以准备：
> 1. 浏览器打开 `token.woa.com` 并登录
> 2. 按 `F12` → `Application` → `Cookies`，复制全部内容
> 3. 等脚本提示"粘贴 Cookie"时贴进去

安装过程中用户会看到：

```
🔧 Cookie 模式：手动输入
请手动输入 CC Cookie：
粘贴 Cookie: [用户粘贴]
✅ Cookie 已保存
✅ 安装完成
```

---

## 第四步：验证

检查菜单栏是否出现 TokenPUA 图标：

```bash
# 终端测试
~/.swiftbar-venv/bin/python3 ~/.swiftbar-plugins/tokens.3m.py
```

输出第一行是菜单栏标题（如 `🟢 ¥283/¥1000 · 完美`）即成功。

### Cookie 过期后

| 自动模式 | 手动模式 |
|---------|---------|
| 什么都不用做，菜单栏自动恢复 | 点击菜单栏「重新输入 Cookie」重新粘贴 |

---

## 常见问题

### 菜单栏空白

```bash
# 1. 测试插件输出
"$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo "$HOME/.swiftbar-plugins")/tokens.3m.py"

# 2. 检查是否被禁用
defaults read com.ameba.SwiftBar DisabledPlugins
# 如果有 tokens.3m.py，重新运行 install.sh

# 3. 检查隐身模式
defaults read com.ameba.SwiftBar StealthMode
# 如果为 1，关闭：defaults write com.ameba.SwiftBar StealthMode -bool false && pkill -x SwiftBar && open -a SwiftBar
```

### 报错 cryptography 签名冲突

报错：`ImportError: code signature not valid for use in process: mapping process and mapped file (non-platform) have different Team IDs`

**`install.sh` 已自动处理**（创建 `~/.swiftbar-venv` 隔离）。如仍遇到：

```bash
# 手动创建 venv 安装
/usr/bin/python3 -m venv ~/.swiftbar-venv
~/.swiftbar-venv/bin/pip install cryptography

# 更新 shebang
PLUGIN_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo ~/.swiftbar-plugins)"
sed -i '' "1s|.*|#!$HOME/.swiftbar-venv/bin/python3|" "$PLUGIN_DIR/tokens.3m.py"
```

### 修改代码后部署

```bash
PLUGIN_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo "$HOME/.swiftbar-plugins")"
cp tokens.3m.py "$PLUGIN_DIR/tokens.3m.py"
open "swiftbar://refreshplugin?name=tokens"
```
