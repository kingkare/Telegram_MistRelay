#!/bin/bash
set -e

# ==============================================================================
# MistRelay Edge Streaming Worker 一键自动化安装部署脚本
# ==============================================================================

RED="\033[31m"
GREEN="\033[32m"
YELLOW="\033[33m"
CYAN="\033[36m"
BOLD="\033[1m"
RESET="\033[0m"

echo -e "${CYAN}${BOLD}======================================================${RESET}"
echo -e "${CYAN}${BOLD}    MistRelay 边缘推流分流节点 (Edge Worker) 安装向导   ${RESET}"
echo -e "${CYAN}${BOLD}======================================================${RESET}"

if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}[ERROR] 此脚本必须以 root 权限运行，请执行: sudo bash $0${RESET}"
    exit 1
fi

MASTER_URL="${MASTER_URL:-{{MASTER_URL}}}"
TOKEN="${TOKEN:-{{TOKEN}}}"
PORT="${PORT:-{{PORT}}}"
PORT="${PORT:-8090}"

if [ -z "$TOKEN" ] || [ "$TOKEN" = "{{TOKEN}}" ]; then
    echo -e "${RED}[ERROR] 未检测到配对 Token，请通过 Master 面板生成一键命令后运行！${RESET}"
    exit 1
fi

echo -e "${GREEN}[1/5] 探测主机环境与公网 IP...${RESET}"
DETECTED_IP=$(curl -s4 --connect-timeout 5 ifconfig.me || curl -s4 --connect-timeout 5 api.ipify.org || hostname -I | awk '{print $1}')
echo -e "      检测到公网 IP: ${BOLD}${DETECTED_IP}${RESET}"

echo -e "${GREEN}[2/5] 向 Master 握手核销配对 Token...${RESET}"
REGISTER_RESP=$(curl -s -X POST "${MASTER_URL}/api/edge/nodes/register-with-token" \
    -H "Content-Type: application/json" \
    -d "{\"token\": \"${TOKEN}\", \"ip\": \"${DETECTED_IP}\", \"port\": ${PORT}}")

SUCCESS=$(echo "$REGISTER_RESP" | grep -o '"success"[^,]*' | grep -o 'true\|false' || true)
if [ "$SUCCESS" != "true" ]; then
    ERROR_MSG=$(echo "$REGISTER_RESP" | grep -o '"error":"[^"]*"' | cut -d'"' -f4 || echo "$REGISTER_RESP")
    echo -e "${RED}[ERROR] 节点注册失败: ${ERROR_MSG}${RESET}"
    exit 1
fi

AUTH_SECRET=$(echo "$REGISTER_RESP" | grep -o '"auth_secret":"[^"]*"' | cut -d'"' -f4)
NODE_ID=$(echo "$REGISTER_RESP" | grep -o '"node_id":[0-9]*' | cut -d':' -f2)
DOMAIN=$(echo "$REGISTER_RESP" | grep -o '"domain":"[^"]*"' | cut -d'"' -f4 || true)
if [ -z "$DOMAIN" ] && [ -n "$DETECTED_IP" ]; then
    DASHED_IP=$(echo "$DETECTED_IP" | tr '.' '-')
    DOMAIN="edge.${DASHED_IP}.sslip.io"
fi
echo -e "      配对成功！分配节点编号: #${BOLD}${NODE_ID}${RESET} | 绑定域名: ${BOLD}${DOMAIN}${RESET}"

echo -e "${GREEN}[3/5] 部署工作目录与边缘推流服务代码...${RESET}"
WORK_DIR="/opt/mistrelay-edge"
mkdir -p "$WORK_DIR"

curl -sSL "${MASTER_URL}/api/edge/worker-script" -o "${WORK_DIR}/worker_server.py"
chmod +x "${WORK_DIR}/worker_server.py"

echo -e "${GREEN}[4/5] 安装 Python 运行依赖、Certbot SSL 工具与配置防火墙...${RESET}"
if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq >/dev/null 2>&1 || true
    apt-get install -y -qq python3 python3-pip python3-venv python3-aiohttp python3-psutil python3-dev build-essential certbot curl >/dev/null 2>&1 || true
elif command -v yum >/dev/null 2>&1; then
    yum install -y -q python3 python3-pip certbot >/dev/null 2>&1 || true
elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache python3 py3-pip py3-aiohttp py3-psutil certbot curl >/dev/null 2>&1 || true
fi

# 安装 pip 依赖
python3 -m pip install --break-system-packages --quiet aiohttp pyrogram tgcrypto psutil >/dev/null 2>&1 || \
python3 -m pip install --quiet aiohttp pyrogram tgcrypto psutil >/dev/null 2>&1 || true

# 配置防火墙端口 (放行推流端口与 80 端口)
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q active; then
    ufw allow ${PORT}/tcp >/dev/null 2>&1 || true
    ufw allow 80/tcp >/dev/null 2>&1 || true
elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --add-port=${PORT}/tcp --permanent >/dev/null 2>&1 || true
    firewall-cmd --add-port=80/tcp --permanent >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
fi

# 优化 Linux 高并发网络栈与 BBR 拥塞控制算法
echo -e "${GREEN}      优化 Linux 高并发网络栈与 BBR 拥塞控制算法...${RESET}"
modprobe tcp_bbr >/dev/null 2>&1 || true
cat <<SYSCTLEOF > /etc/sysctl.d/99-mistrelay-edge.conf
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.ipv4.tcp_window_scaling = 1
net.ipv4.tcp_slow_start_after_idle = 0
fs.file-max = 1048576
SYSCTLEOF
sysctl --system >/dev/null 2>&1 || sysctl -p /etc/sysctl.d/99-mistrelay-edge.conf >/dev/null 2>&1 || true

# 自动化申请 Let's Encrypt 证书
USE_SSL_ARG=""
if [ -n "$DOMAIN" ]; then
    if [ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
        echo -e "${GREEN}      正在申请 Let's Encrypt 免费 SSL 证书 (${DOMAIN})...${RESET}"
        certbot certonly --standalone -d "${DOMAIN}" --non-interactive --agree-tos --register-unsafely-without-email --preferred-challenges http >/dev/null 2>&1 || true
    fi
    if [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
        USE_SSL_ARG="--ssl"
        if [ -d /etc/cron.d ]; then
            cat <<CRON_EOF > /etc/cron.d/certbot-mistrelay-edge
0 3 * * * root certbot renew --quiet --deploy-hook "systemctl restart mistrelay-edge"
CRON_EOF
            chmod 644 /etc/cron.d/certbot-mistrelay-edge
        fi
    fi
fi

echo -e "${GREEN}[5/5] 创建并启动 systemd 系统守护进程...${RESET}"
cat <<EOF > /etc/systemd/system/mistrelay-edge.service
[Unit]
Description=MistRelay Edge Streaming Worker
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${WORK_DIR}
Environment="PORT=${PORT}"
Environment="NODE_SECRET=${AUTH_SECRET}"
Environment="MASTER_URL=${MASTER_URL}"
Environment="DOMAIN=${DOMAIN}"
Environment="USE_SSL=1"
ExecStart=/usr/bin/python3 ${WORK_DIR}/worker_server.py --port ${PORT} --secret ${AUTH_SECRET} --master ${MASTER_URL} --domain "${DOMAIN}" ${USE_SSL_ARG}
Restart=always
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable mistrelay-edge >/dev/null 2>&1 || true
systemctl restart mistrelay-edge

sleep 2
if systemctl is-active --quiet mistrelay-edge; then
    echo -e "${GREEN}${BOLD}======================================================${RESET}"
    echo -e "${GREEN}${BOLD}  ✅ MistRelay 边缘节点部署成功并已正常运行！          ${RESET}"
    echo -e "${GREEN}${BOLD}======================================================${RESET}"
    if [ -n "$USE_SSL_ARG" ]; then
        echo -e "推流入口地址: ${CYAN}https://${DOMAIN}:${PORT}/stream/...${RESET}"
    else
        echo -e "推流入口地址: ${CYAN}http://${DETECTED_IP}:${PORT}/stream/...${RESET}"
    fi
    echo -e "状态检查命令: ${BOLD}systemctl status mistrelay-edge${RESET}"
    echo -e "日志查看命令: ${BOLD}journalctl -u mistrelay-edge -f${RESET}"
else
    echo -e "${RED}[ERROR] 服务启动失败，请使用 journalctl -u mistrelay-edge -n 50 查看详细日志${RESET}"
    exit 1
fi
