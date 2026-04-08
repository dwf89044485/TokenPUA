# Token Budget Pacing

macOS 菜单栏工具，实时显示每月 Token 额度使用进度，帮你把额度花完不浪费。

## 效果

菜单栏常驻显示：`🟥 $192/$1000 · 加速!`

点击展开看详情：
- 已用金额 / 总预算 / 百分比
- 理论应花 vs 实际（按工作日计算）
- 当前日均 vs 目标日均
- 月底预测金额
- 每个模型的花费分布
- 加速 / 减速建议

## 安装

```bash
chmod +x install.sh
./install.sh
```

安装脚本会自动：
1. 检查并安装 Homebrew Python 3 和 SwiftBar
2. 部署插件到 `~/.swiftbar-plugins/`
3. 引导你配置 Cookie

## Cookie 获取方法

1. 浏览器打开 [tokens.woa.com](https://tokens.woa.com/?product=codebuddy) 并登录
2. 按 `F12` 打开开发者工具 → `Network` 标签
3. 刷新页面，点击任意 `/api/` 开头的请求（如 `user`、`platforms`、`query-quota`）
4. 右侧 `Headers` → `Request Headers` → 找到 `Cookie:` 那一行
5. 复制 `Cookie:` 后面的整段值

Cookie 过期后菜单栏会提示，点 🔑 按钮重新粘贴即可。

## 自定义预算

编辑 `~/.swiftbar-plugins/tokens.3m.py`，修改 `BUDGET = 1000.0` 为你的月度预算金额。

## 状态含义

| 图标 | 含义 | 说明 |
|------|------|------|
| 🟥 | 加速! | 目标日均 > 当前日均 × 1.3 |
| 🟡 | 稍加速 | 目标日均 > 当前日均 × 1.1 |
| 🟢 | 完美 | 差距在 ±10% 内 |
| 🟡 | 可放缓 | 目标日均 < 当前日均 × 0.9 |
| 🔵 | 省着用 | 目标日均 < 当前日均 × 0.7 |

## 前置要求

- macOS（Apple Silicon，已测试 M 系列芯片）
- [Homebrew](https://brew.sh)
- 公司内网访问权限
