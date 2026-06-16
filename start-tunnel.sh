#!/bin/bash
# realtime-flow 外网访问启动脚本
# 方案：Cloudflare Tunnel + Cookie 认证
#
# 敏感配置（域名、密码）从 .env 文件读取，.env 不提交到 git
#
# 使用方式：
#   bash start-tunnel.sh setup    # 首次安装配置
#   bash start-tunnel.sh start    # 启动服务（带认证）
#   bash start-tunnel.sh stop     # 停止服务
#   bash start-tunnel.sh status   # 查看状态
#   bash start-tunnel.sh logs     # 查看日志

set -e

# ─── 加载 .env 配置（敏感信息不进 git） ─────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "❌ 未找到 .env 文件: $ENV_FILE"
    echo "   请复制 .env.example 为 .env 并填写实际配置："
    echo "   cp .env.example .env"
    echo "   vi .env"
    exit 1
fi

# 安全地加载 .env（只读取 KEY=VALUE 格式，忽略注释和空行）
set -a
while IFS='=' read -r key value; do
    # 跳过注释和空行
    case "$key" in
        ''|\#*) continue ;;
    esac
    # 去除可能的引号
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    export "$key=$value"
done < "$ENV_FILE"
set +a

# ─── 配置（从环境变量读取，有默认值） ───────────────
DOMAIN="${TUNNEL_DOMAIN:-example.com}"
SUBDOMAIN="${TUNNEL_SUBDOMAIN:-stock.example.com}"
TUNNEL_NAME="${TUNNEL_NAME:-realtime-flow}"
LOCAL_PORT="${LOCAL_PORT:-8899}"

# 认证凭据（从环境变量读取）
AUTH_USER="${AUTH_USER:-admin}"
AUTH_PASS="${AUTH_PASS:-changeme}"

# cloudflared 二进制路径（支持 brew 和手动安装）
CLOUDFLARED_BIN=""
if command -v cloudflared &> /dev/null; then
    CLOUDFLARED_BIN="cloudflared"
elif [ -x "$HOME/.cloudflared/bin/cloudflared" ]; then
    CLOUDFLARED_BIN="$HOME/.cloudflared/bin/cloudflared"
    export PATH="$HOME/.cloudflared/bin:$PATH"
fi

# 文件路径（使用脚本所在目录，不硬编码用户路径）
PROJECT_DIR="$SCRIPT_DIR"
CLOUDFLARED_DIR="$HOME/.cloudflared"
CLOUDFLARED_CONFIG="$CLOUDFLARED_DIR/config.yml"
CLOUDFLARED_LOG="/tmp/cloudflared.log"
SERVICE_LOG="/tmp/realtime-flow.log"
PID_FILE="/tmp/realtime-flow.pid"
TUNNEL_PID_FILE="/tmp/cloudflared.pid"

# ─── 命令实现 ────────────────────────────────────────

cmd_setup() {
    echo "=== Cloudflare Tunnel 首次配置 ==="
    echo ""

    # 1. 检查 cloudflared 是否安装（支持 brew 和手动安装两种方式）
    CLOUDFLARED_BIN=""
    if command -v cloudflared &> /dev/null; then
        CLOUDFLARED_BIN="cloudflared"
        echo "✓ cloudflared 已在 PATH: $(cloudflared --version)"
    elif [ -x "$HOME/.cloudflared/bin/cloudflared" ]; then
        CLOUDFLARED_BIN="$HOME/.cloudflared/bin/cloudflared"
        export PATH="$HOME/.cloudflared/bin:$PATH"
        echo "✓ cloudflared 已安装: $($CLOUDFLARED_BIN --version)"
    else
        echo "📦 cloudflared 未安装，开始下载..."
        echo "   （绕过 brew，直接下载二进制，避免 GitHub 网络问题）"
        mkdir -p $HOME/.cloudflared/bin

        # 尝试多个下载源（GitHub 指定版本最稳定）
        URLS=(
          "https://github.com/cloudflare/cloudflared/releases/download/2024.6.1/cloudflared-darwin-amd64.tgz"
          "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz"
        )

        DOWNLOADED=0
        for url in "${URLS[@]}"; do
            echo "   尝试: $url"
            if curl -L --retry 3 --retry-delay 2 --connect-timeout 15 --max-time 180 -o /tmp/cloudflared.tgz "$url" 2>&1 | tail -2; then
                SIZE=$(stat -f%z /tmp/cloudflared.tgz 2>/dev/null || echo 0)
                if [ "$SIZE" -gt 5000000 ] && file /tmp/cloudflared.tgz | grep -q "gzip"; then
                    echo "   ✓ 下载成功 ($SIZE bytes)"
                    DOWNLOADED=1
                    break
                fi
            fi
        done

        if [ $DOWNLOADED -eq 0 ]; then
            echo "❌ 自动下载失败"
            echo ""
            echo "请手动下载："
            echo "  1. 浏览器打开 https://github.com/cloudflare/cloudflared/releases"
            echo "  2. 下载 cloudflared-darwin-amd64.tgz"
            echo "  3. 执行以下命令安装："
            echo "     mkdir -p ~/.cloudflared/bin"
            echo "     tar -xzf ~/Downloads/cloudflared-darwin-amd64.tgz -C ~/.cloudflared/bin/"
            echo "     chmod +x ~/.cloudflared/bin/cloudflared"
            echo "  4. 重新运行: bash start-tunnel.sh setup"
            exit 1
        fi

        # 解压安装
        tar -xzf /tmp/cloudflared.tgz -C $HOME/.cloudflared/bin/
        chmod +x $HOME/.cloudflared/bin/cloudflared
        rm -f /tmp/cloudflared.tgz

        # 添加到 PATH
        if ! grep -q "cloudflared/bin" ~/.bash_profile 2>/dev/null; then
            echo '' >> ~/.bash_profile
            echo '# cloudflared 二进制路径' >> ~/.bash_profile
            echo 'export PATH="$HOME/.cloudflared/bin:$PATH"' >> ~/.bash_profile
        fi
        export PATH="$HOME/.cloudflared/bin:$PATH"
        CLOUDFLARED_BIN="$HOME/.cloudflared/bin/cloudflared"
        echo "✓ 安装完成: $($CLOUDFLARED_BIN --version)"
    fi

    # 2. 登录认证
    echo ""
    echo "🔐 开始登录 Cloudflare（会打开浏览器）..."
    echo "   请在浏览器中选择 $DOMAIN 域名授权"
    $CLOUDFLARED_BIN tunnel login

    # 3. 创建 Tunnel
    echo ""
    echo "🏗️  创建 Tunnel..."
    $CLOUDFLARED_BIN tunnel create $TUNNEL_NAME

    # 4. 获取 Tunnel UUID
    TUNNEL_UUID=$($CLOUDFLARED_BIN tunnel list | grep $TUNNEL_NAME | awk '{print $1}')
    if [ -z "$TUNNEL_UUID" ]; then
        echo "❌ 无法获取 Tunnel UUID，请手动执行: $CLOUDFLARED_BIN tunnel create $TUNNEL_NAME"
        exit 1
    fi
    echo "✓ Tunnel UUID: $TUNNEL_UUID"

    # 5. 创建配置文件
    echo ""
    echo "📝 创建配置文件..."
    mkdir -p $CLOUDFLARED_DIR
    cat > $CLOUDFLARED_CONFIG << EOF
tunnel: $TUNNEL_UUID
credentials-file: $CLOUDFLARED_DIR/$TUNNEL_UUID.json

loglevel: info
transport-loglevel: warn

ingress:
  - hostname: $SUBDOMAIN
    service: http://localhost:$LOCAL_PORT
  - hostname: $DOMAIN
    service: http://localhost:$LOCAL_PORT
  - service: http_status:404
EOF
    echo "✓ 配置文件: $CLOUDFLARED_CONFIG"

    # 6. 添加 DNS 记录
    echo ""
    echo "🌐 添加 DNS 记录..."
    $CLOUDFLARED_BIN tunnel route dns $TUNNEL_NAME $SUBDOMAIN
    $CLOUDFLARED_BIN tunnel route dns $TUNNEL_NAME $DOMAIN
    echo "✓ DNS 记录已添加"

    echo ""
    echo "=== 配置完成 ==="
    echo "访问地址: https://$SUBDOMAIN"
    echo "认证账号: $AUTH_USER"
    echo "认证密码: $AUTH_PASS"
    echo ""
    echo "现在可以运行: bash start-tunnel.sh start"
}

cmd_start() {
    echo "=== 启动 realtime-flow（带认证）==="

    # 1. 启动主服务（带认证环境变量）
    if [ -f "$PID_FILE" ] && kill -0 $(cat $PID_FILE) 2>/dev/null; then
        echo "⚠️  服务已在运行 (PID: $(cat $PID_FILE))"
    else
        echo "🚀 启动 FastAPI 服务..."
        cd $PROJECT_DIR
        AUTH_USER="$AUTH_USER" AUTH_PASS="$AUTH_PASS" python3 main.py > $SERVICE_LOG 2>&1 &
        echo $! > $PID_FILE
        sleep 3

        if kill -0 $(cat $PID_FILE) 2>/dev/null; then
            echo "✓ 服务已启动 (PID: $(cat $PID_FILE))"
            echo "  本地访问: http://localhost:$LOCAL_PORT (无需密码)"
            echo "  日志: tail -f $SERVICE_LOG"
        else
            echo "❌ 服务启动失败，查看日志: $SERVICE_LOG"
            tail -20 $SERVICE_LOG
            exit 1
        fi
    fi

    # 2. 启动 Cloudflare Tunnel
    if [ -f "$TUNNEL_PID_FILE" ] && kill -0 $(cat $TUNNEL_PID_FILE) 2>/dev/null; then
        echo "⚠️  Tunnel 已在运行 (PID: $(cat $TUNNEL_PID_FILE))"
    else
        if [ -z "$CLOUDFLARED_BIN" ]; then
            echo "❌ cloudflared 未安装，请先运行: bash start-tunnel.sh setup"
            exit 1
        fi
        echo ""
        echo "🌐 启动 Cloudflare Tunnel..."
        $CLOUDFLARED_BIN tunnel run $TUNNEL_NAME > $CLOUDFLARED_LOG 2>&1 &
        echo $! > $TUNNEL_PID_FILE
        sleep 3

        if kill -0 $(cat $TUNNEL_PID_FILE) 2>/dev/null; then
            echo "✓ Tunnel 已启动 (PID: $(cat $TUNNEL_PID_FILE))"
        else
            echo "❌ Tunnel 启动失败，查看日志: $CLOUDFLARED_LOG"
            tail -20 $CLOUDFLARED_LOG
            exit 1
        fi
    fi

    echo ""
    echo "=== 启动完成 ==="
    echo "🌐 外网访问: https://$SUBDOMAIN"
    echo "🔐 认证账号: $AUTH_USER"
    echo "🔐 认证密码: $AUTH_PASS"
    echo ""
    echo "本地访问无需密码: http://localhost:$LOCAL_PORT"
}

cmd_stop() {
    echo "=== 停止服务 ==="

    # 停止 Tunnel
    if [ -f "$TUNNEL_PID_FILE" ]; then
        PID=$(cat $TUNNEL_PID_FILE)
        if kill -0 $PID 2>/dev/null; then
            kill $PID
            echo "✓ Tunnel 已停止 (PID: $PID)"
        fi
        rm -f $TUNNEL_PID_FILE
    fi

    # 停止主服务
    if [ -f "$PID_FILE" ]; then
        PID=$(cat $PID_FILE)
        if kill -0 $PID 2>/dev/null; then
            kill $PID
            echo "✓ 服务已停止 (PID: $PID)"
        fi
        rm -f $PID_FILE
    fi

    echo "=== 已全部停止 ==="
}

cmd_status() {
    echo "=== 服务状态 ==="

    # 主服务状态
    if [ -f "$PID_FILE" ] && kill -0 $(cat $PID_FILE) 2>/dev/null; then
        PID=$(cat $PID_FILE)
        echo "✓ FastAPI 服务: 运行中 (PID: $PID)"
        echo "  本地: http://localhost:$LOCAL_PORT"
    else
        echo "✗ FastAPI 服务: 未运行"
    fi

    # Tunnel 状态
    if [ -f "$TUNNEL_PID_FILE" ] && kill -0 $(cat $TUNNEL_PID_FILE) 2>/dev/null; then
        PID=$(cat $TUNNEL_PID_FILE)
        echo "✓ Cloudflare Tunnel: 运行中 (PID: $PID)"
        echo "  外网: https://$SUBDOMAIN"
    else
        echo "✗ Cloudflare Tunnel: 未运行"
    fi

    # 认证状态
    if [ -n "$AUTH_USER" ] && [ -n "$AUTH_PASS" ]; then
        echo "✓ 访问认证: 已启用 (用户: $AUTH_USER)"
    else
        echo "✗ 访问认证: 未启用"
    fi
}

cmd_logs() {
    echo "=== 实时日志（Ctrl+C 退出）==="
    echo ""
    tail -f $SERVICE_LOG $CLOUDFLARED_LOG
}

# ─── 主入口 ─────────────────────────────────────────
case "${1:-}" in
    setup)  cmd_setup ;;
    start)  cmd_start ;;
    stop)   cmd_stop ;;
    status) cmd_status ;;
    logs)   cmd_logs ;;
    restart) cmd_stop; sleep 2; cmd_start ;;
    *)
        echo "用法: bash $0 {setup|start|stop|restart|status|logs}"
        echo ""
        echo "命令说明:"
        echo "  setup   首次安装配置（登录Cloudflare、创建Tunnel、添加DNS）"
        echo "  start   启动服务（带认证）+ Cloudflare Tunnel"
        echo "  stop    停止所有服务"
        echo "  restart 重启服务"
        echo "  status  查看运行状态"
        echo "  logs    实时查看日志"
        echo ""
        echo "配置:"
        echo "  域名: https://$SUBDOMAIN"
        echo "  认证: $AUTH_USER / $AUTH_PASS"
        ;;
esac
