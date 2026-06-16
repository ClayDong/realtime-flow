#!/bin/bash
# 修复 Cloudflare DNS 解析问题
# 问题：公司内网 DNS (10.28.7.2) 无法解析 api.cloudflare.com
# 方案：在 /etc/hosts 添加静态解析记录
#
# 使用方式：
#   bash fix-cloudflare-dns.sh
#
# 需要输入 sudo 密码

set -e

echo "=== 修复 Cloudflare DNS 解析 ==="
echo ""

# 1. 用公共 DNS 获取 Cloudflare IP
echo "1. 获取 Cloudflare API IP..."
API_IP=$(nslookup api.cloudflare.com 8.8.8.8 2>/dev/null | grep "Address:" | tail -1 | awk '{print $2}')
DASH_IP=$(nslookup dash.cloudflare.com 8.8.8.8 2>/dev/null | grep "Address:" | tail -1 | awk '{print $2}')

if [ -z "$API_IP" ] || [ -z "$DASH_IP" ]; then
    echo "❌ 无法获取 IP，请检查网络"
    exit 1
fi

echo "   api.cloudflare.com  -> $API_IP"
echo "   dash.cloudflare.com -> $DASH_IP"
echo ""

# 2. 备份 hosts
echo "2. 备份 /etc/hosts..."
sudo cp /etc/hosts /etc/hosts.backup.$(date +%Y%m%d%H%M%S)
echo "   ✓ 已备份"
echo ""

# 3. 添加 hosts 记录
echo "3. 添加 hosts 记录（需要 sudo 密码）..."
if grep -q "api.cloudflare.com" /etc/hosts; then
    echo "   ✓ hosts 已有记录，跳过"
else
    echo "" | sudo tee -a /etc/hosts > /dev/null
    echo "# Cloudflare DNS 临时解析（realtime-flow 配置用，配置完成后可删除）" | sudo tee -a /etc/hosts > /dev/null
    echo "$API_IP api.cloudflare.com" | sudo tee -a /etc/hosts > /dev/null
    echo "$DASH_IP dash.cloudflare.com" | sudo tee -a /etc/hosts > /dev/null
    echo "   ✓ 已添加"
fi
echo ""

# 4. 验证
echo "4. 验证解析..."
echo "   hosts 内容："
grep -i "cloudflare" /etc/hosts | sed 's/^/     /'
echo ""

echo "   DNS 解析测试："
if nslookup api.cloudflare.com 2>&1 | grep -q "Address:.*104"; then
    echo "   ✓ api.cloudflare.com 解析成功"
else
    echo "   ⚠️  nslookup 可能仍走 DNS，但 curl 会用 hosts"
fi

echo ""
echo "   curl 连通性测试："
if curl -sI --max-time 10 https://api.cloudflare.com/client/v4/user 2>&1 | head -1 | grep -q "HTTP"; then
    echo "   ✓ API 连通"
else
    echo "   ⚠️  连接失败，可能需要刷新 DNS 缓存"
    echo "   执行: sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder"
fi

echo ""
echo "=== 完成 ==="
echo ""
echo "现在可以重新运行:"
echo "  bash start-tunnel.sh setup"
echo ""
echo "配置完成后，可删除 hosts 记录："
echo "  sudo sed -i '' '/cloudflare/d' /etc/hosts"
