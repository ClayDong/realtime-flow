#!/bin/bash
# realtime-flow 管理脚本
# Usage: bash start.sh {start|stop|restart|status|logs|launchd-install|launchd-remove}

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="/tmp/realtime-flow.log"
PLIST_NAME="com.realtime-flow.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"
PORT=8899

case "${1:-status}" in
  start)
    echo "🚀 启动 realtime-flow..."
    cd "$APP_DIR"
    
    PID=$(lsof -ti :$PORT 2>/dev/null)
    if [ -n "$PID" ]; then
      echo "   释放端口 $PORT (PID=$PID)..."
      kill -9 $PID 2>/dev/null; sleep 2
    fi
    
    nohup python3 main.py > "$LOG_FILE" 2>&1 &
    PID=$!; disown; sleep 4
    
    if curl -s --max-time 2 http://localhost:$PORT/health > /dev/null 2>&1; then
      echo "✅ 启动成功! PID=$PID"
      echo "   访问: http://localhost:$PORT"
    else
      echo "⚠️  启动检查失败:"
      tail -5 "$LOG_FILE"
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
      curl -s http://localhost:$PORT/api/stats | python3 -m json.tool 2>/dev/null
    else
      echo "❌ realtime-flow 未运行"
    fi
    ;;
    
  logs) tail -f "$LOG_FILE" ;;
    
  launchd-install)
    echo "📦 安装 LaunchAgent..."
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>    <string>com.realtime-flow</string>
    <key>ProgramArguments</key> <array><string>/usr/local/bin/python3</string><string>${APP_DIR}/main.py</string></array>
    <key>WorkingDirectory</key> <string>${APP_DIR}</string>
    <key>RunAtLoad</key> <true/>
    <key>KeepAlive</key> <true/>
    <key>StandardOutPath</key> <string>${LOG_FILE}</string>
    <key>StandardErrorPath</key> <string>${LOG_FILE}</string>
</dict>
</plist>
PLIST
    launchctl load "$PLIST_PATH"
    echo "✅ 已安装，重启后自动启动"
    ;;
    
  launchd-remove)
    launchctl unload "$PLIST_PATH" 2>/dev/null; rm -f "$PLIST_PATH"
    echo "✅ 已移除"
    ;;
    
  *) echo "用法: bash $0 {start|stop|restart|status|logs|launchd-install|launchd-remove}" ;;
esac
