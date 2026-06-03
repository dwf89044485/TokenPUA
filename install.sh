#!/bin/bash
# ═══════════════════════════════════════════════════════════
# TokenPUA — 一键安装脚本
# macOS 菜单栏显示每月 Token 额度使用进度
# ═══════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_PLUGIN="$SCRIPT_DIR/tokens.3m.py"
SOURCE_HELPER="$SCRIPT_DIR/cb_helper.py"
DEFAULT_PLUGIN_DIR="$HOME/.swiftbar-plugins"
SWIFTBAR_BUNDLE="com.ameba.SwiftBar"
LAUNCH_AGENT_LABEL="com.tokenpua.cbhelper"
LAUNCH_AGENT_PLIST="$HOME/Library/LaunchAgents/${LAUNCH_AGENT_LABEL}.plist"
CONFIG_DIR="$HOME/.config/tokens-woa"
LOG_DIR="$CONFIG_DIR/logs"
HELPER_STDOUT_LOG="$LOG_DIR/cb_helper.stdout.log"
HELPER_STDERR_LOG="$LOG_DIR/cb_helper.stderr.log"
DEFAULT_PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

if [ ! -f "$SOURCE_PLUGIN" ]; then
    echo "❌ 未找到插件源码: $SOURCE_PLUGIN"
    exit 1
fi

if [ ! -f "$SOURCE_HELPER" ]; then
    echo "❌ 未找到 helper 源码: $SOURCE_HELPER"
    exit 1
fi

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║   TokenPUA 安装工具                  ║"
echo "  ╚══════════════════════════════════════╝"
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

# ─── 1. 检查 Homebrew ────────────────────────────────────
if ! command -v brew >/dev/null 2>&1; then
    echo "❌ 未找到 Homebrew"
    echo "   请先安装: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
fi
echo "✅ Homebrew"

# ─── 2. 检查 Python 3 ────────────────────────────────────
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
    if ! "$PYTHON_BIN" -m pip install cryptography --break-system-packages 2>&1; then
        "$PYTHON_BIN" -m pip install cryptography --user 2>&1 || true
    fi
fi
if "$PYTHON_BIN" -c "import cryptography" >/dev/null 2>&1; then
    echo "✅ cryptography"
else
    echo "⚠️  cryptography 未安装成功（CC 浏览器 Cookie 自动提取不可用）"
fi

# ─── 5. 安装 Node.js ─────────────────────────────────────
NODE_BIN="$(find_bin node /opt/homebrew/bin/node /usr/local/bin/node || true)"
if [ -z "$NODE_BIN" ]; then
    echo "📦 安装 Node.js..."
    brew install node
    hash -r
    NODE_BIN="$(find_bin node /opt/homebrew/bin/node /usr/local/bin/node || true)"
fi
if [ -z "$NODE_BIN" ]; then
    echo "❌ Node.js 安装失败"
    exit 1
fi
NPM_BIN="$(find_bin npm /opt/homebrew/bin/npm /usr/local/bin/npm || true)"
if [ -z "$NPM_BIN" ]; then
    echo "❌ npm 未找到"
    exit 1
fi
echo "✅ Node.js ($($NODE_BIN --version), path=$NODE_BIN)"

# ─── 6. 安装 agent-browser ──────────────────────────────
AGENT_BROWSER_BIN="$(find_bin agent-browser /opt/homebrew/bin/agent-browser /usr/local/bin/agent-browser || true)"
if [ -z "$AGENT_BROWSER_BIN" ]; then
    echo "📦 安装 agent-browser..."
    "$NPM_BIN" install -g agent-browser
    hash -r
    AGENT_BROWSER_BIN="$(find_bin agent-browser /opt/homebrew/bin/agent-browser /usr/local/bin/agent-browser || true)"
fi
if [ -z "$AGENT_BROWSER_BIN" ]; then
    echo "❌ agent-browser 安装失败"
    exit 1
fi
echo "🔧 初始化 agent-browser..."
if ! "$AGENT_BROWSER_BIN" install >/dev/null 2>&1; then
    "$AGENT_BROWSER_BIN" install || true
fi
echo "✅ agent-browser ($AGENT_BROWSER_BIN)"

# ─── 7. 识别 SwiftBar 插件目录 ─────────────────────────
PLUGIN_DIR="$(defaults read "$SWIFTBAR_BUNDLE" PluginDirectory 2>/dev/null || true)"
if [ -z "$PLUGIN_DIR" ]; then
    PLUGIN_DIR="$DEFAULT_PLUGIN_DIR"
fi
mkdir -p "$PLUGIN_DIR" "$CONFIG_DIR" "$LOG_DIR" "$HOME/Library/LaunchAgents"
echo "✅ SwiftBar 插件目录: $PLUGIN_DIR"

# ─── 8. 部署插件与 helper（重写 shebang） ───────────────
deploy_python_script "$SOURCE_PLUGIN" "$PLUGIN_DIR/tokens.3m.py"
deploy_python_script "$SOURCE_HELPER" "$PLUGIN_DIR/cb_helper.py"
defaults write "$SWIFTBAR_BUNDLE" PluginDirectory "$PLUGIN_DIR" 2>/dev/null || true
echo "✅ 已部署 tokens.3m.py 和 cb_helper.py"

# ─── 9. 如果插件被禁用，自动解除 ───────────────────────
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

# ─── 10. 写入 LaunchAgent ───────────────────────────────
: > "$HELPER_STDOUT_LOG"
: > "$HELPER_STDERR_LOG"
cat > "$LAUNCH_AGENT_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LAUNCH_AGENT_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON_BIN}</string>
    <string>${PLUGIN_DIR}/cb_helper.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${PLUGIN_DIR}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${DEFAULT_PATH}</string>
    <key>TOKEN_PUA_AGENT_BROWSER</key>
    <string>${AGENT_BROWSER_BIN}</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>180</integer>
  <key>StandardOutPath</key>
  <string>${HELPER_STDOUT_LOG}</string>
  <key>StandardErrorPath</key>
  <string>${HELPER_STDERR_LOG}</string>
</dict>
</plist>
EOF
launchctl bootout "gui/$(id -u)" "$LAUNCH_AGENT_PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENT_PLIST"
launchctl kickstart -k "gui/$(id -u)/${LAUNCH_AGENT_LABEL}" >/dev/null 2>&1 || true
echo "✅ CB helper 后台刷新已安装 (${LAUNCH_AGENT_LABEL})"

# ─── 11. 启动 SwiftBar ──────────────────────────────────
echo ""
echo "🚀 启动 SwiftBar..."
pkill -x "SwiftBar" 2>/dev/null || true
open -a "SwiftBar" || true
sleep 2

# ─── 12. 初始化 CC ──────────────────────────────────────
echo ""
echo "  正在初始化 CC 登录..."
echo ""
"$PYTHON_BIN" "$PLUGIN_DIR/tokens.3m.py" --setup

# ─── 13. 初始化 CB helper（可见登录） ──────────────────
echo ""
echo "  正在初始化 CB helper..."
echo "  如弹出 agent-browser 浏览器窗口，请在其中完成首次登录"
echo ""
"$PYTHON_BIN" "$PLUGIN_DIR/cb_helper.py" --interactive || true

# ─── 14. 刷新 SwiftBar ──────────────────────────────────
open "swiftbar://refreshplugin?name=tokens" 2>/dev/null || true

echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║   ✅ 安装完成                                 ║"
echo "  ║                                              ║"
echo "  ║   CC 已初始化，CB 将由 helper 后台刷新      ║"
echo "  ║   如 CB 未显示，请先完成弹窗中的首次登录     ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""
echo "  日志位置: $HELPER_STDERR_LOG"
echo ""
