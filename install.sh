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

GITHUB_RAW="https://raw.githubusercontent.com/dwf89044485/TokenPUA/master"
SOURCE_DIR="$HOME/.config/tokens-woa/sources"
DEFAULT_PLUGIN_DIR="$HOME/.swiftbar-plugins"
SWIFTBAR_BUNDLE="com.ameba.SwiftBar"
CONFIG_DIR="$HOME/.config/tokens-woa"
VENV_DIR="$HOME/.swiftbar-venv"
COOKIE_MODE=""  # auto | manual | ""

# ─── 检测运行模式 ───────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo "")"
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/tokens.3m.py" ]; then
    # 本地模式：从同目录读取
    SOURCE_PLUGIN="$SCRIPT_DIR/tokens.3m.py"
    echo "📁 本地模式: $SCRIPT_DIR"
else
    # 远程模式：从 GitHub 下载到固定位置
    echo "🌐 远程模式：下载 TokenPUA..."
    mkdir -p "$SOURCE_DIR"
    if ! curl -fsSL "$GITHUB_RAW/tokens.3m.py" -o "$SOURCE_DIR/tokens.3m.py"; then
        echo "❌ 下载失败，请检查网络连接后重试"
        exit 1
    fi
    # 也下载 GUIDE.md 供 AI 参考
    curl -fsSL "$GITHUB_RAW/GUIDE.md" -o "$SOURCE_DIR/GUIDE.md" 2>/dev/null || true
    SOURCE_PLUGIN="$SOURCE_DIR/tokens.3m.py"
    chmod +x "$SOURCE_PLUGIN"
    echo "✅ 已下载到 $SOURCE_DIR"
fi

if [ ! -f "$SOURCE_PLUGIN" ]; then
    echo "❌ 未找到插件源码: $SOURCE_PLUGIN"
    exit 1
fi

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

# ─── Python 检测 ─────────────────────────────────────
# 优先系统 Python，再 Homebrew，拒绝管理环境
find_safe_python() {
    # 1) 系统内置 Python（Apple 签名，最安全）
    if [ -x /usr/bin/python3 ]; then
        printf '%s\n' "/usr/bin/python3"
        return 0
    fi
    # 2) Homebrew Python（常用位置）
    for p in /opt/homebrew/bin/python3 /usr/local/bin/python3; do
        if [ -x "$p" ]; then
            printf '%s\n' "$p"
            return 0
        fi
    done
    # 3) 更精确的 Homebrew 版本（brew 可能装的是 python@3.13/python@3.12）
    for p in /opt/homebrew/opt/python@3.13/bin/python3.13 \
             /opt/homebrew/opt/python@3.12/bin/python3.12 \
             /usr/local/opt/python@3.13/bin/python3.13 \
             /usr/local/opt/python@3.12/bin/python3.12; do
        if [ -x "$p" ]; then
            printf '%s\n' "$p"
            return 0
        fi
    done
    # 4) PATH 搜索，但过滤管理环境（签名冲突来源）
    local bp
    bp="$(command -v python3 2>/dev/null || true)"
    if [ -n "$bp" ]; then
        case "$bp" in
            *".workbuddy"*|*".asdf"*|*"pyenv"*|*"conda"*|*"venv"*|*"virtualenv"*)
                echo "⚠️  跳过管理环境 Python: $bp" >&2
                ;;
            *)
                printf '%s\n' "$bp"
                return 0
                ;;
        esac
    fi
    return 1
}

PYTHON_BIN="$(find_safe_python || true)"
if [ -z "$PYTHON_BIN" ]; then
    echo "📦 安装 Python 3..."
    if brew install python 2>/dev/null || brew install python@3.13 2>/dev/null || brew install python@3.12 2>/dev/null; then
        PYTHON_BIN="$(find_safe_python || true)"
    else
        echo "❌ Homebrew 安装 Python 失败（可能无写权限）"
        echo ""
        echo "   尝试手动安装:"
        echo "   brew install python"
        echo ""
        echo "   或将已有 Python 硬链接到本脚本的 venv:"
        echo "   /path/to/your/python3 -m venv ~/.swiftbar-venv"
        echo "   然后重新执行 bash install.sh"
        exit 1
    fi
fi
echo "✅ Python 3 ($($PYTHON_BIN --version 2>&1) path=$PYTHON_BIN"

# ─── 创建专用 venv ────────────────────────────────────
# 用找到的 Python 创建独立虚拟环境，避免原生扩展签名冲突
echo "📦 创建插件运行环境（venv）..."
if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
VENV_PYTHON="$VENV_DIR/bin/python3"

# 确认 venv 可用
if [ ! -x "$VENV_PYTHON" ]; then
    echo "⚠️  venv 创建失败，退而使用原 Python: $PYTHON_BIN"
    VENV_PYTHON="$PYTHON_BIN"
else
    echo "✅ venv: $VENV_DIR"
fi

# ─── 1. 检查 Homebrew ────────────────────────────────
if ! command -v brew >/dev/null 2>&1; then
    echo "❌ 未找到 Homebrew"
    echo "   请先安装: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
fi
echo "✅ Homebrew"

# ─── 2. 安装 SwiftBar ───────────────────────────────────
if [ ! -d "/Applications/SwiftBar.app" ]; then
    echo "📦 安装 SwiftBar..."
    brew install --cask swiftbar
    echo "✅ SwiftBar 已安装"
else
    echo "✅ SwiftBar"
fi

# ─── 3. 安装 Python 依赖（仅自动模式需要）────────────────
if [ "$COOKIE_MODE" = "auto" ]; then
    if ! "$VENV_PYTHON" -c "import cryptography" >/dev/null 2>&1; then
        echo "📦 安装 cryptography 到 venv..."
        "$VENV_PYTHON" -m pip install cryptography 2>&1 || true
    fi
    if "$VENV_PYTHON" -c "import cryptography" >/dev/null 2>&1; then
        echo "✅ cryptography"
    else
        echo "⚠️  cryptography 未安装成功，将切换为手动输入 Cookie 模式"
        echo "   如需自动提取，请手动安装: $VENV_PYTHON -m pip install cryptography"
        COOKIE_MODE="manual"
    fi
else
    echo "⏭️  跳过 cryptography 安装（手动模式）"
fi

# ─── 4. 识别 SwiftBar 插件目录 ─────────────────────────
PLUGIN_DIR="$(defaults read "$SWIFTBAR_BUNDLE" PluginDirectory 2>/dev/null || true)"
if [ -z "$PLUGIN_DIR" ]; then
    PLUGIN_DIR="$DEFAULT_PLUGIN_DIR"
fi
mkdir -p "$PLUGIN_DIR" "$CONFIG_DIR"
echo "✅ SwiftBar 插件目录: $PLUGIN_DIR"

# ─── 5. 部署插件（shebang → venv Python）────────────────
deploy_python_script() {
    local source_file="$1"
    local target_file="$2"
    sed "1s|.*|#!${VENV_PYTHON}|" "$source_file" > "$target_file"
    chmod +x "$target_file"
}
deploy_python_script "$SOURCE_PLUGIN" "$PLUGIN_DIR/tokens.3m.py"
defaults write "$SWIFTBAR_BUNDLE" PluginDirectory "$PLUGIN_DIR" 2>/dev/null || true
echo "✅ 已部署 tokens.3m.py"

# ─── 6. 如果插件被禁用，自动解除 ────────────────────────
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

# ─── 7. 启动 SwiftBar ──────────────────────────────────
echo ""
echo "🚀 启动 SwiftBar..."
if ! pkill -x "SwiftBar" 2>/dev/null; then
    true  # 未运行是正常情况
fi
if ! open -a "SwiftBar" 2>/dev/null; then
    echo "⚠️  自动启动失败，请在应用程序中手动打开 SwiftBar"
fi
sleep 2

# ─── 8. 初始化 CC（根据模式分支）─────────────────────────
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
    echo "  正在初始化 CC 登录..."
    echo "  将从 Edge/Chrome 自动提取 Cookie"
    echo ""
    echo "  ⚠️  即将弹出钥匙串授权框，询问是否允许访问「Safe Storage」"
    echo "     请点击「始终允许」（Always Allow），只点一次以后不会再弹"
    echo ""
    "$VENV_PYTHON" "$PLUGIN_DIR/tokens.3m.py" --setup
fi

# ─── 9. 刷新 SwiftBar ──────────────────────────────────
if ! open "swiftbar://refreshplugin?name=tokens" 2>/dev/null; then
    echo "💡 如菜单栏未刷新，请手动点击菜单栏「刷新」按钮"
fi

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
