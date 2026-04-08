#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Token Budget Pacing — 一键安装脚本
# macOS 菜单栏显示每月 Token 额度使用进度
# ═══════════════════════════════════════════════════════════
set -e

PLUGIN_DIR="$HOME/.swiftbar-plugins"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║   Token Budget Pacing 安装工具       ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ─── 1. 检查 Homebrew ────────────────────────────────────
if ! command -v brew &>/dev/null; then
    echo "❌ 未找到 Homebrew"
    echo "   请先安装: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
fi
echo "✅ Homebrew"

# ─── 2. 检查 Python 3 (homebrew) ────────────────────────
if [ ! -x /opt/homebrew/bin/python3 ]; then
    echo "📦 安装 Python 3..."
    brew install python3
fi
echo "✅ Python 3 ($(/opt/homebrew/bin/python3 --version))"

# ─── 3. 安装 SwiftBar ───────────────────────────────────
if [ ! -d "/Applications/SwiftBar.app" ]; then
    echo "📦 安装 SwiftBar..."
    brew install --cask swiftbar
    echo "✅ SwiftBar 已安装"
else
    echo "✅ SwiftBar"
fi

# ─── 4. 部署插件 ────────────────────────────────────────
mkdir -p "$PLUGIN_DIR"
cp "$SCRIPT_DIR/tokens.3m.py" "$PLUGIN_DIR/tokens.3m.py"
chmod +x "$PLUGIN_DIR/tokens.3m.py"
echo "✅ 插件已部署到 $PLUGIN_DIR/"

# ─── 5. 设置 SwiftBar 插件目录 ──────────────────────────
defaults write com.ameba.SwiftBar PluginDirectory "$PLUGIN_DIR" 2>/dev/null || true
echo "✅ SwiftBar 插件目录已配置"

# ─── 6. 配置 Cookie ─────────────────────────────────────
echo ""
echo "  ┌─────────────────────────────────────────────────┐"
echo "  │ 配置 Cookie（访问 tokens.woa.com 所需）          │"
echo "  │                                                  │"
echo "  │ 步骤：                                           │"
echo "  │ 1. 用浏览器打开 tokens.woa.com 并登录            │"
echo "  │ 2. 按 F12 → Network 标签                        │"
echo "  │ 3. 刷新页面，点击任意 /api/ 开头的请求            │"
echo "  │    （如 user、platforms、query-quota 都行）       │"
echo "  │ 4. 右侧 Headers → Request Headers → Cookie      │"
echo "  │ 5. 复制 Cookie: 后面的整段值                     │"
echo "  └─────────────────────────────────────────────────┘"
echo ""
read -p "  粘贴 Cookie 值（直接回车跳过，稍后可在菜单栏设置）: " COOKIE

if [ -n "$COOKIE" ]; then
    # Keychain
    security delete-generic-password -s tokens-woa -a cookie 2>/dev/null || true
    security add-generic-password -s tokens-woa -a cookie -w "$COOKIE"
    # File fallback
    mkdir -p "$HOME/.config/tokens-woa"
    echo -n "$COOKIE" > "$HOME/.config/tokens-woa/cookie"
    chmod 600 "$HOME/.config/tokens-woa/cookie"
    echo "  ✅ Cookie 已保存"
else
    echo "  ⏭️  已跳过（启动后点菜单栏 🔑 按钮设置）"
fi

# ─── 7. 启动 SwiftBar ───────────────────────────────────
echo ""
echo "🚀 启动 SwiftBar..."
killall SwiftBar 2>/dev/null || true
sleep 1
open -a SwiftBar

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║   ✅ 安装完成！                      ║"
echo "  ║                                      ║"
echo "  ║   菜单栏将显示 Token 用量进度         ║"
echo "  ║   每 3 分钟自动刷新                   ║"
echo "  ║                                      ║"
echo "  ║   🔑 Cookie 过期后点菜单栏更新        ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
