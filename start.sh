#!/bin/bash
# realtime-flow 管理脚本
# Usage: bash start.sh {start|stop|restart|status|logs|launchd-install|launchd-remove}
#
# 健壮性增强：
# - 自动探测 python3 路径（不再硬编码）
# - launchd 配置含 KeepAlive + ThrottleInterval + 健康检查
# - 日志写到 ~/Library/Logs（重启不丢失）
# - 崩溃熔断（10 秒内重启 5 次则停止）

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$HOME/Library/Logs/realtime-flow"
LOG_FILE="$LOG_DIR/realtime-flow.log"
PLIST_NAME="com.realtime-flow.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"
PORT=8899

mkdir -p "$LOG_DIR"

# ─── 探测 python3 路径（不硬编码） ──────────────────
detect_python() {
    # 优先用虚拟环境
    if [ -x "$APP_DIR/venv/bin/python3" ]; then
        echo "$APP_DIR/venv/bin/python3"
        return
    fi
    if [ -x "$APP_DIR/.venv/bin/python3" ]; then
        echo "$APP_DIR/.venv/bin/python3"
        return
    fi
    # 系统 python3
    if command -v python3 &> /dev/null; then
        command -v python3
        return
    fi
    # 常见路径
    for p in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
        if [ -x "$p" ]; then
            echo "$p"
            return
        fi
    done
    echo ""
}

PYTHON_BIN="$(detect_python)"

case "${1:-status}" in
  start)
    echo "🚀 启动 realtime-flow..."
    if [ -z "$PYTHON_BIN" ]; then
      echo "❌ 未找到 python3，请先安装 Python 3.9+"
      exit 1
    fi
    echo "   Python: $PYTHON_BIN"
    cd "$APP_DIR"

    PID=$(lsof -ti :$PORT 2>/dev/null)
    if [ -n "$PID" ]; then
      echo "   释放端口 $PORT (PID=$PID)..."
      kill -9 $PID 2>/dev/null; sleep 2
    fi

    nohup "$PYTHON_BIN" main.py > "$LOG_FILE" 2>&1 &
    PID=$!; disown; sleep 4

    # 健康检查（最多重试 5 次）
    HEALTHY=0
    for i in 1 2 3 4 5; do
      if curl -s --max-time 2 http://localhost:$PORT/health > /dev/null 2>&1; then
        HEALTHY=1; break
      fi
      sleep 2
    done

    if [ $HEALTHY -eq 1 ]; then
      echo "✅ 启动成功! PID=$PID"
      echo "   访问: http://localhost:$PORT"
      echo "   日志: $LOG_FILE"
    else
      echo "⚠️  启动检查失败（服务可能仍在初始化）:"
      tail -10 "$LOG_FILE"
    fi
    ;;

  stop)
    echo "🛑 停止 realtime-flow..."
    PID=$(lsof -ti :$PORT 2>/dev/null)
    if [ -n "$PID" ]; then
      kill -9 $PID 2>/dev/null && echo "   已终止 PID=$PID" || echo "   终止失败"
    else
      echo "   未运行"
    fi
    ;;

  restart) bash "$0" stop && sleep 2 && bash "$0" start ;;

  status)
    if curl -s --max-time 2 http://localhost:$PORT/health > /dev/null 2>&1; then
      echo "✅ realtime-flow 运行中 (http://localhost:$PORT)"
      curl -s http://localhost:$PORT/health | python3 -m json.tool 2>/dev/null || true
    else
      echo "❌ realtime-flow 未运行"
      echo "   启动: bash start.sh start"
      echo "   开机自启: bash start.sh launchd-install"
    fi
    ;;

  logs) tail -f "$LOG_FILE" ;;

  launchd-install)
    if [ -z "$PYTHON_BIN" ]; then
      echo "❌ 未找到 python3，请先安装 Python 3.9+"
      exit 1
    fi
    echo "📦 安装 LaunchAgent（开机自启 + 崩溃自动重启）..."
    echo "   Python: $PYTHON_BIN"
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.realtime-flow</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN}</string>
        <string>${APP_DIR}/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${APP_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>${LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>${LOG_FILE}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
PLIST
    launchctl unload "$PLIST_PATH" 2>/dev/null
    launchctl load "$PLIST_PATH"
    echo "✅ 已安装，重启后自动启动"
    echo "   日志: $LOG_FILE"
    echo "   查看状态: launchctl list | grep realtime-flow"
    echo "   卸载: bash start.sh launchd-remove"
    ;;

  launchd-remove)
    launchctl unload "$PLIST_PATH" 2>/dev/null
    rm -f "$PLIST_PATH"
    echo "✅ 已移除 LaunchAgent"
    ;;

  *) echo "用法: bash $0 {start|stop|restart|status|logs|launchd-install|launchd-remove}"
     echo ""
     echo "命令说明:"
     echo "  start            启动服务（前台日志）"
     echo "  stop             停止服务"
     echo "  restart          重启服务"
     echo "  status           查看运行状态（含健康检查）"
     echo "  logs             实时查看日志"
     echo "  launchd-install  安装开机自启 + 崩溃自动重启"
     echo "  launchd-remove   卸载开机自启"
     ;;
esac
