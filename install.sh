#!/bin/bash
# ════════════════════════════════════════════════════
# TokenPUA — 一键安装脚本
# macOS 菜单栏显示每月 Token 额度使用进度
#
# 用法:
#   bash install.sh             交互式选择 Cookie 获取方式
#   bash install.sh --auto     自动从浏览器提取 Cookie
#   bash install.sh --manual   手动输入 Cookie
# ════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_PLUGIN="$SCRIPT_DIR/tokens.3m.py"
DEFAULT_PLUGIN_DIR="$HOME/.swiftbar-plugins"
SWIFTBAR_BUNDLE="com.ameba.SwiftBar"
CONFIG_DIR="$HOME/.config/tokens-woa"
COOKIE_MODE=""  # auto | manual | ""

# ─── 解析参数 ──────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --auto)   COOKIE_MODE="auto" ;;
        --manual) COOKIE_MODE="manual" ;;
        --help|-h)
            echo "用法: bash install.sh [--auto|--manual]"
            echo "  --auto    自动从浏览器提取 Cookie（需要 cryptography + Keychain 访问权限）"
            echo "  --manual  手动输入 Cookie（无需安装额外依赖，Cookie 过期后需重新输入）"
            exit 0
            ;;
    esac
done

if [ ! -f "$SOURCE_PLUGIN" ]; then
    echo "❌ 未找到插件源码: $SOURCE_PLUGIN"
    exit 1
fi

echo ""
echo "  ╔══════════════════════════════╗"
echo "  ║   TokenPUA 安装工具           ║"
echo "  ╚══════════════════════════════╝"
echo ""

# ─── Cookie 模式选择 ──────────────────────────────────
if [ -z "$COOKIE_MODE" ]; then
    echo "请选择 Cookie 获取方式："
    echo ""
    echo "  [1] 自动提取（推荐）"
    echo "      ✅ 无需手动操作，安装完成后即生效"
    echo "      ✅ Cookie 过期后自动从浏览器刷新，无需重新配置"
    echo "      ⚠️  需要安装 cryptography 依赖"
    echo "      ⚠️  需要访问浏览器 Keychain（可能弹出密码提示）"
    echo ""
    echo "  [2] 手动输入"
    echo "      ✅ 无需安装 cryptography"
    echo "      ✅ 无需访问 Keychain，无弹窗"
    echo "      ⚠️  Cookie 过期后需手动重新填入"
    echo ""
    printf "选择 [1/2，默认 1]: "
    read -r choice
    if [ "$choice" = "2" ]; then
        COOKIE_MODE="manual"
    else
        COOKIE_MODE="auto"
    fi
fi

echo ""
if [ "$COOKIE_MODE" = "manual" ]; then
    echo "🔧 Cookie 模式：手动输入"
else
    echo "🔧 Cookie 模式：自动提取"
fi

# 持久化模式标记
mkdir -p "$CONFIG_DIR"
printf '%s\n' "$COOKIE_MODE" > "$CONFIG_DIR/mode"

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

# ─── 4. 检查 Python 依赖（仅自动模式需要）───────────────────────
if [ "$COOKIE_MODE" = "auto" ]; then
    if ! "$PYTHON_BIN" -c "import cryptography" >/dev/null 2>&1; then
        echo "📦 安装 Python 依赖 cryptography..."
        if ! "$PYTHON_BIN" -m pip install cryptography --break-system-packages 2>&1; then
            "$PYTHON_BIN" -m pip install cryptography --user 2>&1 || true
        fi
    fi
    if "$PYTHON_BIN" -c "import cryptography" >/dev/null 2>&1; then
        echo "✅ cryptography"
    else
        echo "⚠️  cryptography 未安装成功，将切换为手动输入 Cookie 模式"
        echo "   如需自动提取，请手动安装: $PYTHON_BIN -m pip install cryptography"
        COOKIE_MODE="manual"
    fi
else
    echo "⏭️  跳过 cryptography 安装（手动模式）"
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

# ─── 9. 初始化 CC（根据模式分支）─────────────────────────────
echo ""
if [ "$COOKIE_MODE" = "manual" ]; then
    echo "  请手动输入 CC Cookie："
    echo "  获取方式：在浏览器登录 token.woa.com 后，"
    echo "  打开开发者工具 → Application → Cookies → 复制全部 Cookie"
    echo ""
    printf "  粘贴 Cookie: "
    read -r user_cookie
    if [ -n "$user_cookie" ]; then
        mkdir -p "$CONFIG_DIR"
        echo "$user_cookie" > "$CONFIG_DIR/cc_cookie"
        chmod 600 "$CONFIG_DIR/cc_cookie"
        echo "✅ Cookie 已保存"
    else
        echo "⚠️  未输入 Cookie，稍后可在菜单栏点击「点击登录」手动输入"
    fi
else
    echo "  正在初始化 CC 登录（自动从浏览器提取 Cookie）..."
    echo ""
    echo "  ⚠️  即将弹出钥匙串授权框，询问是否允许访问「Safe Storage」"
    echo "     请点击「始终允许」（Always Allow），只点一次以后不会再弹"
    echo ""
    "$PYTHON_BIN" "$PLUGIN_DIR/tokens.3m.py" --setup
fi

# ─── 10. 刷新 SwiftBar ──────────────────────────────────
open "swiftbar://refreshplugin?name=tokens" 2>/dev/null || true

echo ""
echo "  ╔══════════════════════════════╗"
echo "  ║   ✅ 安装完成                 ║"
if [ "$COOKIE_MODE" = "manual" ]; then
    echo "  ║                              ║"
    echo "  ║   Cookie 手动模式             ║"
    echo "  ║   Cookie 过期后需重新输入     ║"
fi
echo "  ╚══════════════════════════════╝"
echo ""
