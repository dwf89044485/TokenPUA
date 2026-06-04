# TokenPUA

macOS 菜单栏工具，实时显示每月 Token 额度使用进度，帮你把额度花完不浪费。

**CC（WOA 渠道）**：按模型展示花费（¥），支持工作日 pacing 计算。

---

## 效果

菜单栏显示：`🟢 ¥283/¥1000 · 完美`

下拉内容：

```
月进度 | size=11 color=#888888
 额度  █████░░░░░░░░░░  28%  ¥283/¥1000 | ansi=true size=12 font=Menlo bash=/usr/bin/true terminal=false
 时间  ██████░░░░░░░░░░  30%  9/30天 | ansi=true size=12 font=Menlo bash=/usr/bin/true terminal=false
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

## 快速安装

拿到项目后，在终端执行：

```bash
bash install.sh
```

安装脚本会自动完成：

- 安装 SwiftBar、Python、Python 依赖（`cryptography`）
- 部署 `tokens.3m.py` 到 SwiftBar 插件目录（自动修正 shebang）
- 拉起浏览器完成 CC 登录，保存 Cookie
- 重启并刷新 SwiftBar

执行完后，菜单栏会出现 TokenPUA 图标。

---

## 首次使用流程

1. 执行 `bash install.sh`
2. 脚本自动打开浏览器，在浏览器中完成 **CC 登录**
3. 登录成功后 Cookie 自动保存，SwiftBar 每次刷新时自动拉取数据

---

## 自定义配置

修改 `tokens.3m.py` 顶部 Config 区域（少量场景需要）：

| 变量              | 说明                  | 默认值                                        |
| --------------- | ------------------- | ------------------------------------------ |
| `BASE_URL`      | API 基础地址            | `https://token.woa.com`                    |
| `PLATFORMS`     | 统计的产品平台             | `all`                                      |
| `DASHBOARD_URL` | 菜单「打开 Token 看板」跳转地址 | `https://token.woa.com/?product=codebuddy` |

月度额度（`total_quota`）从 API 动态获取，不需要手动配置。

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

---

## 前置要求

- macOS（Apple Silicon，已测试 M 系列）
- [Homebrew](https://brew.sh)
- Microsoft Edge 或 Google Chrome（用于首次登录态获取）
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
