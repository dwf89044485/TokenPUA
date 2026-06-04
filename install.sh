#!/bin/bash
# ═══════════════════════════════════════════════════════
# TokenPUA — 一键安装脚本
# macOS 菜单栏显示每月 Token 额度使用进度
# ═══════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_PLUGIN="$SCRIPT_DIR/tokens.3m.py"
DEFAULT_PLUGIN_DIR="$HOME/.swiftbar-plugins"
SWIFTBAR_BUNDLE="com.ameba.SwiftBar"
CONFIG_DIR="$HOME/.config/tokens-woa"
DEFAULT_PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

if [ ! -f "$SOURCE_PLUGIN" ]; then
    echo "❌ 未找到插件源码: $SOURCE_PLUGIN"
    exit 1
fi

echo ""
echo "  ╔════════════════════════════════╗"
echo "  ║   TokenPUA 安装工具                  ║"
echo "  ╚════════════════════════════════╝"
echo ""

find_bin() {
    local name="$1"
    shift || true
    for candidate in "$@"; do
        if [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    local bin_path
    bin_path="$(command -v "$name" 2>/dev/null)"
    if [ -n "$bin_path" ]; then
        printf '%s\n' "$bin_path"
        return 0
    fi
    return 1
}

deploy_python_script() {
    local source_file="$1"
    local target_file="$2"
    sed "1s|.*|#!${PYTHON_BIN}|" "$source_file" > "$target_file"
    chmod +x "$target_file"
}

# ─── 1. 检查 Homebrew ────────────────────────────
if ! command -v brew >/dev/null 2>&1; then
    echo "❌ 未找到 Homebrew"
    echo "   请先安装: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
fi
echo "✅ Homebrew"

# ─── 2. 检查 Python 3 ────────────────────────────
PYTHON_BIN="$(find_bin python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 || true)"
if [ -z "$PYTHON_BIN" ]; then
    echo "📦 安装 Python 3..."
    brew install python
    PYTHON_BIN="$(find_bin python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 || true)"
fi
if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Python 3 安装失败"
    exit 1
fi
echo "✅ Python 3 ($($PYTHON_BIN --version 2>&1) path=$PYTHON_BIN"

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
    if ! "$PYTHON_BIN" -m pip install cryptography --break-system-packages 2>&1; then
        "$PYTHON_BIN" -m pip install cryptography --user 2>&1 || true
    fi
fi
if "$PYTHON_BIN" -c "import cryptography" >/dev/null 2>&1; then
    echo "✅ cryptography"
else
    echo "⚠️  cryptography 未安装成功（CC 浏览器 Cookie 自动提取不可用）"
fi

# ─── 5. 识别 SwiftBar 插件目录 ─────────────────────────
PLUGIN_DIR="$(defaults read "$SWIFTBAR_BUNDLE" PluginDirectory 2>/dev/null || true)"
if [ -z "$PLUGIN_DIR" ]; then
    PLUGIN_DIR="$DEFAULT_PLUGIN_DIR"
fi
mkdir -p "$PLUGIN_DIR" "$CONFIG_DIR"
echo "✅ SwiftBar 插件目录: $PLUGIN_DIR"

# ─── 6. 部署插件（重写 shebang）────────────────────────
deploy_python_script "$SOURCE_PLUGIN" "$PLUGIN_DIR/tokens.3m.py"
defaults write "$SWIFTBAR_BUNDLE" PluginDirectory "$PLUGIN_DIR" 2>/dev/null || true
echo "✅ 已部署 tokens.3m.py"

# ─── 7. 如果插件被禁用，自动解除 ───────────────────────
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

# ─── 8. 启动 SwiftBar ──────────────────────────────────
echo ""
echo "🚀 启动 SwiftBar..."
pkill -x "SwiftBar" 2>/dev/null || true
open -a "SwiftBar" || true
sleep 2

# ─── 9. 初始化 CC ──────────────────────────────────────
echo ""
echo "  正在初始化 CC 登录..."
echo ""
"$PYTHON_BIN" "$PLUGIN_DIR/tokens.3m.py" --setup

# ─── 10. 刷新 SwiftBar ──────────────────────────────────
open "swiftbar://refreshplugin?name=tokens" 2>/dev/null || true

echo ""
echo "  ╔════════════════════════════════╗"
echo "  ║   ✅ 安装完成                                 ║"
echo "  ║                                              ║"
echo "  ║   CC 已初始化，菜单栏即可看到进度         ║"
echo "  ╚════════════════════════════════╝"
echo ""
