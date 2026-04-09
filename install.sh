#!/bin/bash
# ═══════════════════════════════════════════════════════════
# TokenPUA — 一键安装脚本
# macOS 菜单栏显示每月 Token 额度使用进度
# ═══════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_PLUGIN="$SCRIPT_DIR/tokens.3m.py"
DEFAULT_PLUGIN_DIR="$HOME/.swiftbar-plugins"
SWIFTBAR_BUNDLE="com.ameba.SwiftBar"

if [ ! -f "$SOURCE_PLUGIN" ]; then
    echo "❌ 未找到插件源码: $SOURCE_PLUGIN"
    exit 1
fi

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║   TokenPUA 安装工具             ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ─── 1. 检查 Homebrew ────────────────────────────────────
if ! command -v brew >/dev/null 2>&1; then
    echo "❌ 未找到 Homebrew"
    echo "   请先安装: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
fi
echo "✅ Homebrew"

# ─── 2. 检查 Python 3 ────────────────────────────────────
PYTHON_BIN=""
for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if [ -x "$candidate" ]; then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [ -z "$PYTHON_BIN" ] && command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "📦 安装 Python 3..."
    brew install python
    if [ -x /opt/homebrew/bin/python3 ]; then
        PYTHON_BIN="/opt/homebrew/bin/python3"
    elif [ -x /usr/local/bin/python3 ]; then
        PYTHON_BIN="/usr/local/bin/python3"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3)"
    fi
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Python 3 安装失败，未找到可执行文件"
    exit 1
fi

echo "✅ Python 3 ($($PYTHON_BIN --version), path=$PYTHON_BIN)"

# ─── 3. 安装 SwiftBar ───────────────────────────────────
if [ ! -d "/Applications/SwiftBar.app" ]; then
    echo "📦 安装 SwiftBar..."
    brew install --cask swiftbar
    echo "✅ SwiftBar 已安装"
else
    echo "✅ SwiftBar"
fi

# ─── 4. 检查 Python 依赖 ────────────────────────────────
if ! "$PYTHON_BIN" -c "import cryptography" >/dev/null 2>&1; then
    echo "📦 安装 Python 依赖 cryptography..."
    "$PYTHON_BIN" -m pip install cryptography --break-system-packages >/dev/null 2>&1 || \
    "$PYTHON_BIN" -m pip install cryptography --user >/dev/null 2>&1 || true
fi

if "$PYTHON_BIN" -c "import cryptography" >/dev/null 2>&1; then
    echo "✅ cryptography"
else
    echo "⚠️  cryptography 未安装成功（不会阻断安装，Codebuddy 自动取 Cookie 可能不可用）"
fi

# ─── 5. 识别 SwiftBar 插件目录 ─────────────────────────
PLUGIN_DIR="$(defaults read "$SWIFTBAR_BUNDLE" PluginDirectory 2>/dev/null || true)"
if [ -z "$PLUGIN_DIR" ]; then
    PLUGIN_DIR="$DEFAULT_PLUGIN_DIR"
fi
mkdir -p "$PLUGIN_DIR"

echo "✅ SwiftBar 插件目录: $PLUGIN_DIR"

# ─── 6. 部署插件（重写 shebang 到本机 Python） ─────────
TMP_PLUGIN="$(mktemp)"
{
    printf '#!%s\n' "$PYTHON_BIN"
    /usr/bin/tail -n +2 "$SOURCE_PLUGIN"
} > "$TMP_PLUGIN"

cp "$TMP_PLUGIN" "$PLUGIN_DIR/tokens.3m.py"
rm -f "$TMP_PLUGIN"
chmod +x "$PLUGIN_DIR/tokens.3m.py"

defaults write "$SWIFTBAR_BUNDLE" PluginDirectory "$PLUGIN_DIR" 2>/dev/null || true

echo "✅ 插件已部署到 $PLUGIN_DIR/tokens.3m.py"

# ─── 7. 配置 Cookie（WOA） ─────────────────────────────
echo ""
echo "  ┌─────────────────────────────────────────────────┐"
echo "  │ 配置 WOA Cookie（首次必填，过期后可在菜单更新） │"
echo "  │                                                  │"
echo "  │ 步骤：                                           │"
echo "  │ 1. 用浏览器打开 tokens-nbyxw43y... 并登录       │"
echo "  │ 2. F12 → Network，点任意 /api/ 请求             │"
echo "  │ 3. Headers 里复制 Cookie: 后面的整段值           │"
echo "  └─────────────────────────────────────────────────┘"
echo ""
read -r -p "  粘贴 Cookie 值（直接回车跳过）: " COOKIE

if [ -n "$COOKIE" ]; then
    security delete-generic-password -s tokens-woa -a cookie 2>/dev/null || true
    security add-generic-password -s tokens-woa -a cookie -w "$COOKIE"
    mkdir -p "$HOME/.config/tokens-woa"
    printf '%s' "$COOKIE" > "$HOME/.config/tokens-woa/cookie"
    chmod 600 "$HOME/.config/tokens-woa/cookie"
    echo "  ✅ WOA Cookie 已保存"
else
    echo "  ⏭️  已跳过（可在菜单栏里点“更新 WOA Cookie”）"
fi

# ─── 8. 如果插件被禁用，自动解除 ───────────────────────
PREF_PLIST="$HOME/Library/Preferences/${SWIFTBAR_BUNDLE}.plist"
if [ -f "$PREF_PLIST" ] && /usr/libexec/PlistBuddy -c "Print :DisabledPlugins" "$PREF_PLIST" >/dev/null 2>&1; then
    idx=0
    while /usr/libexec/PlistBuddy -c "Print :DisabledPlugins:$idx" "$PREF_PLIST" >/dev/null 2>&1; do
        entry="$(/usr/libexec/PlistBuddy -c "Print :DisabledPlugins:$idx" "$PREF_PLIST" 2>/dev/null || true)"
        if [ "$entry" = "tokens.3m.py" ]; then
            /usr/libexec/PlistBuddy -c "Delete :DisabledPlugins:$idx" "$PREF_PLIST" >/dev/null 2>&1 || true
            continue
        fi
        idx=$((idx + 1))
    done
fi

# ─── 9. 启动并刷新 SwiftBar ────────────────────────────
echo ""
echo "🚀 启动 SwiftBar..."
pkill -x "SwiftBar" 2>/dev/null || true
open -a "SwiftBar" || true
sleep 2
open "swiftbar://refreshplugin?name=tokens" || true
open "swiftbar://refreshallplugins" || true

echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║   ✅ 安装完成                                 ║"
echo "  ║                                              ║"
echo "  ║   已部署插件: $PLUGIN_DIR/tokens.3m.py"
echo "  ║   如菜单无内容，先在终端执行：               ║"
echo "  ║   $PYTHON_BIN $PLUGIN_DIR/tokens.3m.py"
echo "  ╚══════════════════════════════════════════════╝"
echo ""