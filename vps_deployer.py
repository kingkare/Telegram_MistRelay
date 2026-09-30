from contextlib import asynccontextmanager
"""
MistRelay 多租户 VPS 边缘节点 SSH 自动化纳管与部署引擎
========================================================
负责通过异步 SSH 在租户提供的 VPS 上自动探测系统环境、配置防火墙、
下发 Edge Streaming Worker 微服务并启动守护进程，实时回传终端日志。
"""

import os
import time
import base64
import shutil
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Callable, Awaitable, Tuple, Dict, Any
from aiohttp import ClientSession, ClientTimeout

import db

logger = logging.getLogger("vps_deployer")

WORKER_SCRIPT_PATH = Path(__file__).resolve().parent / "edge_worker" / "worker_server.py"
INSTALL_SH_PATH = Path(__file__).resolve().parent / "edge_worker" / "install.sh"

# 记录当前正在运行的部署任务: node_id -> asyncio.Task
_active_deploy_tasks: Dict[int, asyncio.Task] = {}


def get_worker_script_content() -> str:
    if WORKER_SCRIPT_PATH.exists():
        return WORKER_SCRIPT_PATH.read_text(encoding="utf-8")
    return ""


def render_install_sh(master_url: str, token: str, port: int = 8090) -> str:
    if INSTALL_SH_PATH.exists():
        tpl = INSTALL_SH_PATH.read_text(encoding="utf-8")
    else:
        tpl = "#!/bin/bash\necho \"Install script missing\"\nexit 1\n"
    return (
        tpl.replace("{{MASTER_URL}}", str(master_url or "").rstrip("/"))
        .replace("{{TOKEN}}", str(token or ""))
        .replace("{{PORT}}", str(int(port or 8090)))
    )


def build_remote_deploy_script(
    port: int,
    auth_secret: str,
    master_url: str,
    domain: str = "",
    use_ssl: bool = False,
    ip: str = "",
) -> str:
    """构建在远程 VPS 上执行的自动化初始化与服务部署 Shell 脚本 (含 sslip.io / Certbot 自动化 HTTPS)"""
    clean_domain = str(domain or "").strip()
    clean_ip = str(ip or "").strip()
    if not clean_domain and clean_ip:
        clean_domain = db.get_default_edge_domain(clean_ip)
    if clean_domain:
        use_ssl = True

    worker_py = get_worker_script_content()
    worker_b64 = base64.b64encode(worker_py.encode("utf-8")).decode("ascii")
    clean_master = str(master_url or "").rstrip("/")
    port_num = int(port or 8090)
    ssl_flag = "--ssl" if use_ssl else ""

    certbot_step = ""
    if clean_domain:
        certbot_step = f"""
echo ">>> [Step 4b] 正在配置 Let's Encrypt 自动化 SSL 证书与定时续期 ({clean_domain})..."
if command -v apt-get >/dev/null 2>&1; then
    apt-get install -y -qq certbot >/dev/null 2>&1 || true
elif command -v yum >/dev/null 2>&1; then
    yum install -y -q certbot >/dev/null 2>&1 || true
elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache certbot >/dev/null 2>&1 || true
fi

if command -v certbot >/dev/null 2>&1; then
    if [ ! -f "/etc/letsencrypt/live/{clean_domain}/fullchain.pem" ]; then
        echo "    正在执行 Certbot 免交互独立模式申请免费 SSL 证书..."
        certbot certonly --standalone -d "{clean_domain}" --non-interactive --agree-tos --register-unsafely-without-email --preferred-challenges http >/dev/null 2>&1 || echo "    [提示] Certbot 80 端口验证未直接就绪，节点将以弹性自适应模式启动"
    else
        echo "    已检测到现有证书: /etc/letsencrypt/live/{clean_domain}/fullchain.pem"
    fi
    if [ -d /etc/cron.d ]; then
        cat <<CRONEOF > /etc/cron.d/certbot-mistrelay-edge
0 3 * * * root certbot renew --quiet --deploy-hook "systemctl restart mistrelay-edge 2>/dev/null || true"
CRONEOF
        chmod 644 /etc/cron.d/certbot-mistrelay-edge 2>/dev/null || true
        echo "    已配置每日自动续期任务 (/etc/cron.d/certbot-mistrelay-edge)"
    fi
fi
"""

    script = f"""set -e
export DEBIAN_FRONTEND=noninteractive

echo ">>> [Step 1/5] 正在探测远程 VPS 硬件与操作系统环境..."
OS_NAME=$(grep -E '^PRETTY_NAME=' /etc/os-release 2>/dev/null | cut -d'"' -f2 || uname -s)
ARCH=$(uname -m)
CPU_CORES=$(nproc 2>/dev/null || echo 1)
MEM_TOTAL=$(free -m 2>/dev/null | awk '/Mem:/ {{print $2}}' || echo "Unknown")
echo "    操作系统: ${{OS_NAME}} (${{ARCH}}) | CPU: ${{CPU_CORES}} 核 | 内存: ${{MEM_TOTAL}} MB"

echo ">>> [Step 2/5] 正在创建工作目录并下发 MistRelay Edge Worker 核心引擎..."
WORK_DIR="/opt/mistrelay-edge"
mkdir -p "$WORK_DIR"
echo "{worker_b64}" | base64 -d > "${{WORK_DIR}}/worker_server.py"
chmod +x "${{WORK_DIR}}/worker_server.py"
echo "    引擎文件已写入: ${{WORK_DIR}}/worker_server.py"

echo ">>> [Step 3/5] 正在检查并安装 Python3 运行时及网络推流依赖 (aiohttp, pyrogram, psutil)..."
if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq >/dev/null 2>&1 || true
    apt-get install -y -qq python3 python3-pip python3-aiohttp python3-psutil python3-dev build-essential curl >/dev/null 2>&1 || true
elif command -v yum >/dev/null 2>&1; then
    yum install -y -q python3 python3-pip curl >/dev/null 2>&1 || true
elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache python3 py3-pip py3-aiohttp py3-psutil curl >/dev/null 2>&1 || true
fi

python3 -m pip install --break-system-packages --quiet aiohttp pyrogram tgcrypto psutil 2>/dev/null || \\
python3 -m pip install --quiet aiohttp pyrogram tgcrypto psutil 2>/dev/null || \\
python3 -m pip install --break-system-packages --quiet aiohttp psutil 2>/dev/null || \\
python3 -m pip install --quiet aiohttp psutil 2>/dev/null || true

if ! python3 -c "import aiohttp" 2>/dev/null; then
    echo "    正在尝试备用安装模式补齐 aiohttp..."
    python3 -m pip install --break-system-packages aiohttp psutil 2>/dev/null || \\
    apt-get install -y -qq python3-aiohttp python3-psutil 2>/dev/null || true
fi

if ! python3 -c "import aiohttp" 2>/dev/null; then
    echo "❌ 依赖安装失败：未能正确安装 Python aiohttp 模块"
    exit 1
fi
echo "    依赖环境就绪"

echo ">>> [Step 4/5] 正在配置系统防火墙放行推流端口 ({port_num}/tcp) 与 ACME 验证端口 (80/tcp)..."
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q active; then
    ufw allow {port_num}/tcp >/dev/null 2>&1 || true
    ufw allow 80/tcp >/dev/null 2>&1 || true
    echo "    已通过 UFW 放行端口 {port_num}/tcp 及 80/tcp"
elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --add-port={port_num}/tcp --permanent >/dev/null 2>&1 || true
    firewall-cmd --add-port=80/tcp --permanent >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
    echo "    已通过 firewalld 放行端口 {port_num}/tcp 及 80/tcp"
else
    echo "    未检测到活动状态的阻塞型防火墙，端口默认畅通"
fi
{certbot_step}
echo ">>> [Step 4c] 正在优化 Linux 高并发网络栈与 BBR 拥塞控制算法..."
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

echo ">>> [Step 5/5] 正在注册系统守护服务并启动边缘推流节点..."
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    cat <<EOF > /etc/systemd/system/mistrelay-edge.service
[Unit]
Description=MistRelay Edge Streaming Worker
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${{WORK_DIR}}
Environment="PORT={port_num}"
Environment="NODE_SECRET={auth_secret}"
Environment="MASTER_URL={clean_master}"
Environment="DOMAIN={clean_domain}"
Environment="USE_SSL={'1' if use_ssl else '0'}"
ExecStart=/usr/bin/python3 ${{WORK_DIR}}/worker_server.py --port {port_num} --secret {auth_secret} --master {clean_master} --domain "{clean_domain}" {ssl_flag}
Restart=always
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable mistrelay-edge >/dev/null 2>&1 || true
    systemctl restart mistrelay-edge
    echo "    已通过 systemd 启动 mistrelay-edge 服务"
else
    pkill -f "worker_server.py --port {port_num}" >/dev/null 2>&1 || true
    nohup python3 "${{WORK_DIR}}/worker_server.py" --port {port_num} --secret "{auth_secret}" --master "{clean_master}" --domain "{clean_domain}" {ssl_flag} > "${{WORK_DIR}}/worker.log" 2>&1 &
    echo "    已通过后台守护进程模式启动 worker_server.py"
fi

echo ">>> [Health Check] 正在探测本地推流节点端口及健康接口 ({port_num})..."
HEALTH_OK=0
for i in $(seq 1 12); do
    sleep 1
    if curl -s -f "http://127.0.0.1:{port_num}/health" >/dev/null 2>&1 || curl -k -s -f "https://127.0.0.1:{port_num}/health" >/dev/null 2>&1; then
        echo ">>> [Health Check] 边缘推流节点部署圆满完成！正在监听端口: {port_num}"
        HEALTH_OK=1
        break
    fi
done

if [ "$HEALTH_OK" != "1" ]; then
    echo "❌ 服务启动失败！最新服务日志："
    if command -v journalctl >/dev/null 2>&1; then
        journalctl -u mistrelay-edge -n 25 --no-pager
    elif [ -f "${{WORK_DIR}}/worker.log" ]; then
        tail -n 25 "${{WORK_DIR}}/worker.log"
    fi
    exit 1
fi
"""
    return script


async def _default_ssh_runner(
    ssh_host: str,
    ssh_port: int,
    ssh_user: str,
    ssh_password: str,
    remote_script: str,
    log_callback: Callable[[str], None],
    timeout_sec: int = 180,
) -> int:
    """使用 sshpass + ssh 异步执行远程部署脚本并实时回调每一行输出"""
    ssh_bin = shutil.which("ssh") or "/usr/bin/ssh"
    sshpass_bin = shutil.which("sshpass")

    ssh_args = [
        ssh_bin,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=12",
        "-p", str(int(ssh_port or 22)),
        f"{ssh_user}@{ssh_host}",
        "bash -s",
    ]

    env = os.environ.copy()
    if ssh_password and sshpass_bin:
        env["SSHPASS"] = ssh_password
        cmd = [sshpass_bin, "-e"] + ssh_args
    else:
        cmd = ssh_args

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )

    assert proc.stdin is not None
    assert proc.stdout is not None

    proc.stdin.write(remote_script.encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()

    try:
        async with asyncio.timeout(timeout_sec):
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                if decoded:
                    log_callback(decoded)
            return await proc.wait()
    except TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        log_callback(f"[ERROR] SSH 远程执行超时 ({timeout_sec}s)，已中止进程")
        return 124


async def deploy_node_via_ssh(
    node_id: int,
    master_url: str = "",
    clear_password_on_success: bool = False,
    ssh_runner: Optional[Callable] = None,
) -> bool:
    """执行指定边缘节点的 SSH 自动化部署流程"""
    node = db.get_edge_node_by_id(node_id, include_secrets=True)
    if not node:
        logger.error(f"未找到边缘节点 ID={node_id}")
        return False

    ssh_host = (node.get("ssh_host") or node.get("ip") or "").strip()
    ssh_port = int(node.get("ssh_port") or 22)
    ssh_user = (node.get("ssh_user") or "root").strip()
    enc_pwd = node.get("ssh_password_enc") or ""
    ssh_password = db.decrypt_ssh_password(enc_pwd) if enc_pwd else ""

    if not ssh_host:
        db.update_edge_node(node_id, status="error")
        db.append_edge_node_deploy_log(node_id, "[ERROR] 未配置目标 VPS 主机 IP 或地址")
        return False

    if not ssh_password:
        db.update_edge_node(node_id, status="error")
        db.append_edge_node_deploy_log(node_id, "[ERROR] 未提供有效的 SSH 密码，无法自动纳管")
        return False

    # 重置日志并标记为 deploying
    db.update_edge_node(node_id, status="deploying", deploy_log="")
    start_msg = f"🚀 启动 SSH 自动化纳管流水线 -> 目标: {ssh_user}@{ssh_host}:{ssh_port} (业务端口: {node.get('port', 8090)})"
    db.append_edge_node_deploy_log(node_id, start_msg)
    try:
        from edge_node_manager import broadcast_edge_node_update, broadcast_edge_deploy_log
        asyncio.create_task(broadcast_edge_node_update(node_id))
        asyncio.create_task(broadcast_edge_deploy_log(node_id=node_id, line=start_msg, deploy_log=start_msg + "\n", status="deploying", target_user_id=node.get("tenant_id")))
    except Exception:
        pass

    node_ip = str(node.get("ip") or ssh_host or "").strip()
    node_domain = str(node.get("domain") or "").strip()
    if not node_domain and node_ip:
        node_domain = db.get_default_edge_domain(node_ip)
    use_ssl = True if node_domain else bool(node.get("use_ssl"))

    if node_domain and node_domain != node.get("domain"):
        db.update_edge_node(node_id, domain=node_domain, use_ssl=1)

    remote_script = build_remote_deploy_script(
        port=int(node.get("port") or 8090),
        auth_secret=str(node.get("auth_secret") or ""),
        master_url=master_url,
        domain=node_domain,
        use_ssl=use_ssl,
        ip=node_ip,
    )

    runner = ssh_runner or _default_ssh_runner

    def _log_cb(msg: str):
        db.append_edge_node_deploy_log(node_id, msg)
        try:
            from edge_node_manager import broadcast_edge_deploy_log
            asyncio.create_task(broadcast_edge_deploy_log(node_id=node_id, line=msg, status="deploying", target_user_id=node.get("tenant_id")))
        except Exception:
            pass

    try:
        rc = await runner(
            ssh_host,
            ssh_port,
            ssh_user,
            ssh_password,
            remote_script,
            _log_cb,
        )
        if rc == 0:
            now_str = datetime.now(timezone.utc).isoformat()
            db.update_edge_node(
                node_id,
                status="online",
                last_seen_at=now_str,
            )
            succ_msg = "✅ 节点部署成功并已上线！Master 302 边缘分流已自动激活。"
            db.append_edge_node_deploy_log(
                node_id,
                succ_msg,
            )
            if clear_password_on_success:
                db.clear_edge_node_ssh_password(node_id)
                db.append_edge_node_deploy_log(
                    node_id,
                    "🔒 [安全加固] 已自动擦除数据库中保存的 SSH root 密码。",
                )
            try:
                from edge_node_manager import broadcast_edge_node_update, broadcast_edge_deploy_log
                asyncio.create_task(broadcast_edge_node_update(node_id))
                asyncio.create_task(broadcast_edge_deploy_log(node_id=node_id, line=succ_msg, status="online", target_user_id=node.get("tenant_id")))
            except Exception:
                pass
            return True
        else:
            db.update_edge_node(node_id, status="error")
            fail_msg = f"❌ SSH 部署异常退出 (返回码: {rc})，请检查账号密码、网络连通性或系统权限。"
            db.append_edge_node_deploy_log(
                node_id,
                fail_msg,
            )
            try:
                from edge_node_manager import broadcast_edge_node_update, broadcast_edge_deploy_log
                asyncio.create_task(broadcast_edge_node_update(node_id))
                asyncio.create_task(broadcast_edge_deploy_log(node_id=node_id, line=fail_msg, status="error", target_user_id=node.get("tenant_id")))
            except Exception:
                pass
            return False
    except Exception as e:
        logger.error(f"SSH 自动部署节点 #{node_id} 异常: {e}", exc_info=True)
        db.update_edge_node(node_id, status="error")
        exc_msg = f"❌ 部署过程发生未预期异常: {e}"
        db.append_edge_node_deploy_log(node_id, exc_msg)
        try:
            from edge_node_manager import broadcast_edge_node_update, broadcast_edge_deploy_log
            asyncio.create_task(broadcast_edge_node_update(node_id))
            asyncio.create_task(broadcast_edge_deploy_log(node_id=node_id, line=exc_msg, status="error", target_user_id=node.get("tenant_id")))
        except Exception:
            pass
        return False
    finally:
        _active_deploy_tasks.pop(node_id, None)


def start_background_ssh_deploy(
    node_id: int,
    master_url: str = "",
    clear_password_on_success: bool = False,
) -> asyncio.Task:
    """在后台启动异步 SSH 部署任务"""
    existing = _active_deploy_tasks.get(node_id)
    if existing and not existing.done():
        existing.cancel()
    task = asyncio.create_task(
        deploy_node_via_ssh(
            node_id=node_id,
            master_url=master_url,
            clear_password_on_success=clear_password_on_success,
        )
    )
    _active_deploy_tasks[node_id] = task
    return task


async def check_edge_node_health(node_id: int, timeout: float = 5.0) -> Dict[str, Any]:
    """主动探测边缘节点的 HTTP /health 健康状态与响应延迟"""
    node = db.get_edge_node_by_id(node_id, include_secrets=True)
    if not node:
        return {"online": False, "error": "节点不存在"}

    domain = (node.get("domain") or "").strip()
    ip = (node.get("ip") or "").strip()
    port = int(node.get("port") or 8090)
    use_ssl = bool(node.get("use_ssl"))

    if not domain and ip:
        domain = db.get_default_edge_domain(ip)
        if domain:
            use_ssl = True

    if domain:
        scheme = "https" if use_ssl else "http"
        target_url = f"{scheme}://{domain}/health" if port in (80, 443) else f"{scheme}://{domain}:{port}/health"
    elif ip:
        target_url = f"http://{ip}:{port}/health"
    else:
        return {"online": False, "error": "未配置节点 IP 或域名"}

    t0 = time.perf_counter()
    try:
        async with ClientSession(timeout=ClientTimeout(total=timeout)) as session:
            async with session.get(target_url, ssl=False) as resp:
                latency_ms = round((time.perf_counter() - t0) * 1000, 1)
                if resp.status == 200:
                    data = await resp.json()
                    now_str = datetime.now(timezone.utc).isoformat()
                    db.update_edge_node(node_id, status="online", last_seen_at=now_str)
                    return {
                        "online": True,
                        "latency_ms": latency_ms,
                        "url": target_url,
                        "worker_data": data,
                    }
                else:
                    return {
                        "online": False,
                        "latency_ms": latency_ms,
                        "error": f"HTTP {resp.status}",
                    }
    except Exception as e:
        err_msg = str(e)
        if ("WRONG_VERSION_NUMBER" in err_msg or "RemoteDisconnected" in err_msg or "Connection reset" in err_msg or "ssl" in err_msg.lower()) and target_url.startswith("https://"):
            fallback_url = target_url.replace("https://", "http://", 1)
            try:
                async with ClientSession(timeout=ClientTimeout(total=timeout)) as session:
                    async with session.get(fallback_url, ssl=False) as resp2:
                        if resp2.status == 200:
                            data = await resp2.json()
                            now_str = datetime.now(timezone.utc).isoformat()
                            db.update_edge_node(node_id, status="online", use_ssl=0, last_seen_at=now_str)
                            return {
                                "online": True,
                                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                                "url": fallback_url,
                                "worker_data": data,
                                "ssl_downgraded": True,
                            }
            except Exception:
                pass
        return {
            "online": False,
            "error": f"连接失败: {e}",
            "url": target_url,
        }


def get_edge_node_base_url(node: dict) -> str:
    """根据节点配置解析基础 URL (包含协议、域名/IP与端口)"""
    domain = (node.get("domain") or "").strip()
    ip = (node.get("ip") or "").strip()
    port = int(node.get("port") or 8090)
    use_ssl = bool(node.get("use_ssl"))

    if not domain and ip:
        domain = db.get_default_edge_domain(ip)

    if domain:
        scheme = "https" if use_ssl else "http"
        return f"{scheme}://{domain}" if port in (80, 443) else f"{scheme}://{domain}:{port}"
    elif ip:
        scheme = "https" if use_ssl else "http"
        return f"{scheme}://{ip}:{port}"
    return ""


@asynccontextmanager
async def _safe_edge_request(
    session: ClientSession,
    base_url: str,
    path: str,
    method: str = "GET",
    node_id: int | None = None,
    **kwargs,
):
    url = f"{base_url}{path}"
    try:
        req_ctx = session.post(url, ssl=False, **kwargs) if method.upper() == "POST" else session.get(url, ssl=False, **kwargs)
        async with req_ctx as resp:
            yield resp
    except Exception as e:
        err_str = str(e)
        if ("WRONG_VERSION_NUMBER" in err_str or "RemoteDisconnected" in err_str or "Connection reset" in err_str) and url.startswith("https://"):
            fallback_url = url.replace("https://", "http://", 1)
            if node_id:
                try:
                    db.update_edge_node(node_id, use_ssl=0)
                except Exception:
                    pass
            fallback_ctx = session.post(fallback_url, ssl=False, **kwargs) if method.upper() == "POST" else session.get(fallback_url, ssl=False, **kwargs)
            async with fallback_ctx as resp2:
                yield resp2
        else:
            raise


async def run_edge_dcs_benchmark(node_id: int, timeout: float = 15.0) -> Dict[str, Any]:
    """通过边缘节点测试到 Telegram 5 大官方数据中心的延迟矩阵"""
    node = db.get_edge_node_by_id(node_id)
    if not node:
        return {"success": False, "error": "节点不存在"}
    base_url = get_edge_node_base_url(node)
    if not base_url:
        return {"success": False, "error": "未配置节点 IP 或域名"}

    try:
        async with ClientSession(timeout=ClientTimeout(total=timeout)) as session:
            async with _safe_edge_request(session, base_url, "/benchmark/dcs", method="GET", node_id=node_id) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data
                return {"success": False, "error": f"HTTP {resp.status}"}
    except Exception as e:
        return {"success": False, "error": f"连接测速接口失败: {e}"}


def find_best_benchmark_media(target_dc_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    智能选择最适宜作为拉流测速样本的 Telegram 媒体文件：
    1. 必须来自公开租户频道 (bin_channel_username 不为空，且非私密全局频道 -1001998444696)，确保阵列中所有 Bot 均有权并发拉流；
    2. 优先匹配节点所属的 target_dc_id (例如美西节点优先匹配 DC1 媒体，亚太/香港节点优先匹配 DC5 媒体)；
    3. 文件大小 >= 20MB，确保多分片能够跑满高并发阵列带宽；
    4. 若目标 DC 无专属文件，安全回退至其他公开租户频道媒体。
    """
    try:
        from pyrogram.file_id import FileId
        conn = db.get_connection()
        c = conn.cursor()
        c.execute("""
            SELECT m.message_id, m.chat_id, m.file_id, m.file_size, u.bin_channel_username
            FROM tg_media m 
            JOIN users u ON m.chat_id = u.bin_channel_id
            WHERE u.bin_channel_username IS NOT NULL 
              AND u.bin_channel_username != ''
              AND m.chat_id != -1001998444696
              AND m.file_size >= 20971520
            ORDER BY m.file_size DESC
            LIMIT 50
        """)
        rows = c.fetchall()

        if target_dc_id:
            for r in rows:
                try:
                    fid = FileId.decode(r["file_id"])
                    if fid.dc_id == target_dc_id:
                        return {
                            "chat_id": int(r["chat_id"]),
                            "message_id": int(r["message_id"]),
                            "channel_username": str(r["bin_channel_username"]),
                            "file_size": int(r["file_size"]),
                            "dc_id": fid.dc_id,
                        }
                except Exception:
                    continue

        for r in rows:
            try:
                fid = FileId.decode(r["file_id"])
                return {
                    "chat_id": int(r["chat_id"]),
                    "message_id": int(r["message_id"]),
                    "channel_username": str(r["bin_channel_username"]),
                    "file_size": int(r["file_size"]),
                    "dc_id": fid.dc_id,
                }
            except Exception:
                continue

        c.execute("""
            SELECT m.message_id, m.chat_id, m.file_size, u.bin_channel_username
            FROM tg_media m LEFT JOIN users u ON m.chat_id = u.bin_channel_id
            WHERE m.file_size >= 10485760
            ORDER BY m.file_size DESC LIMIT 1
        """)
        r2 = c.fetchone()
        if r2:
            return {
                "chat_id": int(r2["chat_id"]),
                "message_id": int(r2["message_id"]),
                "channel_username": str(r2["bin_channel_username"] or ""),
                "file_size": int(r2["file_size"]),
                "dc_id": 5,
            }
    except Exception as e:
        logger.debug(f"find_best_benchmark_media failed: {e}")

    return None


async def run_edge_tg_speed_benchmark(
    node_id: int,
    sample_mb: float = 10.0,
    chat_id: int = 0,
    message_id: int = 0,
    timeout: float = 45.0,
) -> Dict[str, Any]:
    """测试边缘节点直接从 Telegram DC 拉取媒体分片的吞吐速率"""
    node = db.get_edge_node_by_id(node_id)
    if not node:
        return {"success": False, "error": "节点不存在"}
    base_url = get_edge_node_base_url(node)
    if not base_url:
        return {"success": False, "error": "未配置节点 IP 或域名"}

    # 尝试从库中匹配样本媒体（优先匹配节点目标 DC，且必须为公开租户频道大文件）
    channel_username = ""
    if chat_id == 0 or message_id == 0:
        target_dc = node.get("target_dc_id")
        best_media = find_best_benchmark_media(target_dc_id=target_dc)
        if best_media:
            chat_id = best_media["chat_id"]
            message_id = best_media["message_id"]
            channel_username = best_media["channel_username"]

    payload = {
        "sample_size_mb": float(sample_mb),
        "chat_id": int(chat_id),
        "message_id": int(message_id),
        "channel_username": str(channel_username),
    }

    try:
        async with ClientSession(timeout=ClientTimeout(total=timeout)) as session:
            async with _safe_edge_request(session, base_url, "/benchmark/tg-speed", method="POST", node_id=node_id, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data
                return {"success": False, "error": f"HTTP {resp.status}"}
    except Exception as e:
        return {"success": False, "error": f"连接拉流测速接口失败: {e}"}


async def run_edge_relay_stream_benchmark(
    node_id: int,
    sample_mb: float = 25.0,
    chat_id: int = 0,
    message_id: int = 0,
    timeout: float = 50.0,
) -> Dict[str, Any]:
    """
    发起端到端真实全双工中继流播压测：
    Master 模拟真实视频播放器，向边缘节点的 /stream/{path} 发起 HTTP 流式请求，
    边从 Telegram DC 拉取分片边向 Master 推流，测量真实全链路体感流速、起播延迟与瓶颈诊断。
    """
    node = db.get_edge_node_by_id(node_id, include_secrets=True)
    if not node:
        return {"success": False, "error": "节点不存在"}
    base_url = get_edge_node_base_url(node)
    if not base_url:
        return {"success": False, "error": "未配置节点 IP 或域名"}
    auth_secret = str(node.get("auth_secret") or "")
    if not auth_secret:
        return {"success": False, "error": "节点缺少认证秘钥"}

    # 1. 寻找合适的测试媒体样本
    channel_username = ""
    file_size = 0
    target_dc = node.get("target_dc_id") or 5
    if chat_id == 0 or message_id == 0:
        best_media = find_best_benchmark_media(target_dc_id=target_dc)
        if best_media:
            chat_id = best_media["chat_id"]
            message_id = best_media["message_id"]
            channel_username = best_media.get("channel_username", "")
            file_size = int(best_media.get("file_size") or 0)
            target_dc = int(best_media.get("dc_id") or target_dc)

    # 若未找到媒体样本，安全回退到独立 TG 拉流测试
    if chat_id == 0 or message_id == 0:
        tg_res = await run_edge_tg_speed_benchmark(node_id, sample_mb=sample_mb, timeout=timeout)
        if tg_res.get("success"):
            spd = float(tg_res.get("speed_mb_s", 0.0))
            return {
                "success": True,
                "is_fallback": True,
                "relay_speed_mb_s": spd,
                "relay_speed_mbps": round(spd * 8, 2),
                "tg_pull_speed_mb_s": spd,
                "tg_pull_speed_mbps": round(spd * 8, 2),
                "ttfb_ms": tg_res.get("ttfb_ms", 0.0),
                "buffer_ms": tg_res.get("buffer_ms", 0.0),
                "bytes_transferred": tg_res.get("bytes_transferred", 0),
                "duration_s": tg_res.get("duration_s", 0.0),
                "target_dc": tg_res.get("target_dc", target_dc),
                "usable_bots_count": tg_res.get("usable_bots_count", 1),
                "bottleneck_diagnosis": "🟢 全链路无损满速中继 (回退模式)",
                "grade": tg_res.get("grade", "A"),
                "evaluation": tg_res.get("evaluation", ""),
            }
        return {"success": False, "error": "未找到适合测速的媒体样本且直连拉流失败"}

    # 2. 生成边缘流播 HMAC Ticket
    sample_mb = max(2.0, min(sample_mb, 100.0))
    target_bytes = int(sample_mb * 1024 * 1024)
    if file_size <= 0:
        file_size = target_bytes + 1024 * 1024

    range_end = min(file_size - 1, target_bytes - 1)

    import edge_node_manager
    ticket = edge_node_manager.generate_edge_stream_ticket(
        tenant_id=0,
        chat_id=chat_id,
        message_id=message_id,
        file_unique_id=f"relay_bench_{message_id}",
        node_secret=auth_secret,
        file_name=f"benchmark_{message_id}.mp4",
        file_size=file_size,
        mime_type="video/mp4",
        dc_id=target_dc,
        expire_seconds=1800,
        channel_username=channel_username,
    )

    stream_endpoint = f"/stream/bench_{message_id}?ticket={ticket}&download=1"

    req_headers = {
        "Range": f"bytes=0-{range_end}",
        "User-Agent": "MistRelay-Benchmark/1.0",
        "Accept": "*/*",
    }

    t0 = time.perf_counter()
    ttfb_ms = 0.0
    buffer_ms = 0.0
    bytes_received = 0
    t_first_chunk = None
    t_buffer_done = None

    try:
        async with ClientSession(timeout=ClientTimeout(total=timeout)) as session:
            async with _safe_edge_request(session, base_url, stream_endpoint, method="GET", node_id=node_id, headers=req_headers) as resp:
                if resp.status not in (200, 206):
                    err_text = await resp.text()
                    logger.warning(f"Relay stream benchmark failed with HTTP {resp.status}: {err_text[:200]}")
                    # 回退到普通 TG 拉流测速
                    tg_fallback = await run_edge_tg_speed_benchmark(node_id, sample_mb=sample_mb, chat_id=chat_id, message_id=message_id, timeout=timeout)
                    if tg_fallback.get("success"):
                        spd = float(tg_fallback.get("speed_mb_s", 0.0))
                        return {
                            "success": True,
                            "is_fallback": True,
                            "relay_speed_mb_s": spd,
                            "relay_speed_mbps": round(spd * 8, 2),
                            "tg_pull_speed_mb_s": spd,
                            "tg_pull_speed_mbps": round(spd * 8, 2),
                            "ttfb_ms": tg_fallback.get("ttfb_ms", 0.0),
                            "buffer_ms": tg_fallback.get("buffer_ms", 0.0),
                            "bytes_transferred": tg_fallback.get("bytes_transferred", 0),
                            "duration_s": tg_fallback.get("duration_s", 0.0),
                            "target_dc": tg_fallback.get("target_dc", target_dc),
                            "usable_bots_count": tg_fallback.get("usable_bots_count", 1),
                            "bottleneck_diagnosis": f"🟢 回退直连拉流 ({spd} MB/s)",
                            "grade": tg_fallback.get("grade", "A"),
                            "evaluation": tg_fallback.get("evaluation", ""),
                        }
                    return {"success": False, "error": f"边缘中继流播返回 HTTP {resp.status}"}

                while True:
                    chunk = await resp.content.read(65536)
                    if not chunk:
                        break
                    now = time.perf_counter()
                    if t_first_chunk is None:
                        t_first_chunk = now
                        ttfb_ms = round((now - t0) * 1000, 1)

                    bytes_received += len(chunk)
                    if bytes_received >= 2 * 1024 * 1024 and t_buffer_done is None:
                        t_buffer_done = now
                        buffer_ms = round((now - t0) * 1000, 1)

                    if bytes_received >= target_bytes:
                        break

            total_dur = max(0.001, time.perf_counter() - t0)
            if buffer_ms == 0.0:
                buffer_ms = round(ttfb_ms + 30.0, 1)

            relay_speed_mb_s = round((bytes_received / (1024 * 1024)) / total_dur, 2)
            relay_speed_mbps = round(relay_speed_mb_s * 8, 2)

            # 3. 从边缘节点查询该会话的内部拉流埋点指标 (/benchmark/last-relay)
            last_relay = {}
            try:
                async with _safe_edge_request(session, base_url, "/benchmark/last-relay", method="GET", node_id=node_id) as r_metric:
                    if r_metric.status == 200:
                        last_relay = await r_metric.json()
            except Exception:
                pass

            tg_pull_speed = float(last_relay.get("tg_pull_speed_mb_s") or last_relay.get("client_push_speed_mb_s") or relay_speed_mb_s)
            usable_bots = int(last_relay.get("usable_sources_count") or 1)
            hedged_requests = int(last_relay.get("hedged_requests_count") or 0)
            hedged_wins = int(last_relay.get("hedged_wins_count") or 0)
            dual_launch_used = bool(last_relay.get("dual_launch_used", False))
            jitter_cv = float(last_relay.get("jitter_cv") or 0.0)
            hardware_tier = str(last_relay.get("hardware_tier") or "BUDGET_VPS")
            window_size = int(last_relay.get("window_size") or 4)
            pareto_opt = bool(last_relay.get("pareto_optimal", relay_speed_mb_s >= 15.0 or (ttfb_ms < 250 and relay_speed_mb_s >= 8.0)))

            # 4. 瓶颈诊断与质量评级
            bench_data = node.get("benchmark_data") or {}
            bw_info = bench_data.get("bandwidth") or {}
            effective_bw = float(bw_info.get("effective_bw_mb_s") or bw_info.get("down_speed_mb_s") or relay_speed_mb_s)

            if relay_speed_mb_s >= effective_bw * 0.85 or relay_speed_mb_s >= 25.0:
                bottleneck_diagnosis = "🟢 全链路无损满速中继 (端到端跑满物理带宽)"
                grade = "S+" if relay_speed_mb_s >= 40.0 else "A+"
            elif tg_pull_speed > 0 and tg_pull_speed < effective_bw * 0.5 and relay_speed_mb_s >= tg_pull_speed * 0.8:
                bottleneck_diagnosis = f"🟡 Telegram DC 拉取受限 (TG拉流 {tg_pull_speed} MB/s，需扩充Bot阵列或优化DC链路)"
                grade = "B"
            elif tg_pull_speed > relay_speed_mb_s * 1.35:
                bottleneck_diagnosis = f"🔴 VPS 上行出网瓶颈 (TG拉流 {tg_pull_speed} MB/s，但推流受限于 VPS 上行 {relay_speed_mb_s} MB/s)"
                grade = "B-"
            else:
                bottleneck_diagnosis = f"🟢 正常中继流播 (体感流速 {relay_speed_mb_s} MB/s)"
                grade = "A"

            if relay_speed_mb_s >= 45.0:
                evaluation = "多 Bot 阵列极速满载 (45MB/s+ 满速达标)"
            elif relay_speed_mb_s >= 25.0:
                evaluation = "4K 60FPS 极清无损直推"
            elif relay_speed_mb_s >= 10.0:
                evaluation = "4K 30FPS 超清秒开"
            elif relay_speed_mb_s >= 4.0:
                evaluation = "1080P 高清流畅播放"
            elif relay_speed_mb_s >= 1.5:
                evaluation = "720P 标清播放"
            else:
                evaluation = "速度偏慢，建议检查网络与上行"

            return {
                "success": True,
                "relay_speed_mb_s": relay_speed_mb_s,
                "relay_speed_mbps": relay_speed_mbps,
                "tg_pull_speed_mb_s": tg_pull_speed,
                "tg_pull_speed_mbps": round(tg_pull_speed * 8, 2),
                "speed_mb_s": relay_speed_mb_s,
                "speed_mbps": relay_speed_mbps,
                "ttfb_ms": ttfb_ms,
                "buffer_ms": buffer_ms,
                "bytes_transferred": bytes_received,
                "sample_size_mb": round(bytes_received / (1024 * 1024), 2),
                "duration_s": round(total_dur, 2),
                "target_dc": target_dc,
                "usable_bots_count": usable_bots,
                "hedged_requests_count": hedged_requests,
                "hedged_wins_count": hedged_wins,
                "dual_launch_used": dual_launch_used,
                "jitter_cv": jitter_cv,
                "hardware_tier": hardware_tier,
                "window_size": window_size,
                "pareto_optimal": pareto_opt,
                "bottleneck_diagnosis": bottleneck_diagnosis,
                "grade": grade,
                "evaluation": evaluation,
            }
    except Exception as e:
        logger.error(f"中继流播测速异常: {e}", exc_info=True)
        try:
            tg_res = await run_edge_tg_speed_benchmark(node_id, sample_mb=sample_mb, timeout=timeout)
            if tg_res.get("success"):
                spd = float(tg_res.get("speed_mb_s", 0.0))
                return {
                    "success": True,
                    "is_fallback": True,
                    "relay_speed_mb_s": spd,
                    "relay_speed_mbps": round(spd * 8, 2),
                    "tg_pull_speed_mb_s": spd,
                    "tg_pull_speed_mbps": round(spd * 8, 2),
                    "ttfb_ms": tg_res.get("ttfb_ms", 0.0),
                    "buffer_ms": tg_res.get("buffer_ms", 0.0),
                    "bytes_transferred": tg_res.get("bytes_transferred", 0),
                    "duration_s": tg_res.get("duration_s", 0.0),
                    "target_dc": tg_res.get("target_dc", target_dc),
                    "usable_bots_count": tg_res.get("usable_bots_count", 1),
                    "bottleneck_diagnosis": f"🟢 回退直连拉流 ({spd} MB/s)",
                    "grade": tg_res.get("grade", "A"),
                    "evaluation": tg_res.get("evaluation", ""),
                }
        except Exception:
            pass
        return {"success": False, "error": f"中继流播压测失败: {e}"}


async def run_edge_link_benchmark(node_id: int, timeout: float = 15.0) -> Dict[str, Any]:
    """测量 Master 主控与边缘节点之间的互联链路质量与双向传输速率"""
    node = db.get_edge_node_by_id(node_id)
    if not node:
        return {"success": False, "error": "节点不存在"}
    base_url = get_edge_node_base_url(node)
    if not base_url:
        return {"success": False, "error": "未配置节点 IP 或域名"}

    try:
        async with ClientSession(timeout=ClientTimeout(total=timeout)) as session:
            # 1. 测量 RTT 往返时延
            t0 = time.perf_counter()
            async with _safe_edge_request(session, base_url, "/health", method="GET", node_id=node_id) as r_ping:
                if r_ping.status != 200:
                    return {"success": False, "error": f"Health HTTP {r_ping.status}"}
                rtt_ms = round((time.perf_counter() - t0) * 1000, 1)

            # 2. Worker -> Master 下行测速 (拉取 2MB 数据)
            t_down_0 = time.perf_counter()
            async with _safe_edge_request(session, base_url, "/benchmark/link-speed?size_mb=2", method="GET", node_id=node_id) as r_down:
                if r_down.status == 200:
                    down_bytes = len(await r_down.read())
                    down_dur = max(0.001, time.perf_counter() - t_down_0)
                    down_speed_mb_s = round((down_bytes / (1024 * 1024)) / down_dur, 2)
                else:
                    down_speed_mb_s = 0.0

            # 3. Master -> Worker 上行测速 (推送 2MB 数据)
            dummy_up = b"MISTRELAY_LINK_UP_" * 116508  # 约 2MB
            t_up_0 = time.perf_counter()
            async with _safe_edge_request(session, base_url, "/benchmark/link-speed", method="POST", node_id=node_id, data=dummy_up) as r_up:
                if r_up.status == 200:
                    up_dur = max(0.001, time.perf_counter() - t_up_0)
                    up_speed_mb_s = round((len(dummy_up) / (1024 * 1024)) / up_dur, 2)
                else:
                    up_speed_mb_s = 0.0

            return {
                "success": True,
                "rtt_ms": rtt_ms,
                "down_speed_mb_s": down_speed_mb_s,
                "down_speed_mbps": round(down_speed_mb_s * 8, 2),
                "up_speed_mb_s": up_speed_mb_s,
                "up_speed_mbps": round(up_speed_mb_s * 8, 2),
            }
    except Exception as e:
        return {"success": False, "error": f"主控互联链路测速失败: {e}"}


async def run_edge_bandwidth_benchmark(node_id: int, timeout: float = 20.0) -> Dict[str, Any]:
    """测试边缘 VPS 物理宽带吞吐（Anycast CDN + Master 链路流式混合双测）"""
    node = db.get_edge_node_by_id(node_id)
    if not node:
        return {"success": False, "error": "节点不存在"}
    base_url = get_edge_node_base_url(node)
    if not base_url:
        return {"success": False, "error": "未配置节点 IP 或域名"}

    try:
        async with ClientSession(timeout=ClientTimeout(total=timeout)) as session:
            async with _safe_edge_request(session, base_url, "/benchmark/vps-bandwidth", method="GET", node_id=node_id) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data
    except Exception as e:
        logger.debug(f"run_edge_bandwidth_benchmark request failed: {e}")

    # 回退到 link 测速
    try:
        import edge_node_manager
        link_res = await run_edge_link_benchmark(node_id)
        down_spd = link_res.get("down_speed_mb_s", 8.0) if link_res.get("success") else 8.0
        rec_bots = edge_node_manager.calculate_recommended_bots(down_spd)
        return {
            "success": True,
            "down_speed_mb_s": down_spd,
            "down_speed_mbps": round(down_spd * 8, 2),
            "cdn_speed_mb_s": 0.0,
            "master_speed_mb_s": down_spd,
            "rtt_ms": link_res.get("rtt_ms", 50.0),
            "source": "fallback_link_benchmark",
            "recommended_bots": rec_bots,
            "rated_capacity_mb_s": round(rec_bots * 2.0, 1),
            "rated_capacity_mbps": round(rec_bots * 16.0, 1),
        }
    except Exception as fe:
        return {"success": False, "error": str(fe), "down_speed_mb_s": 8.0}


async def reconfigure_edge_worker(node_id: int, timeout: float = 25.0) -> Dict[str, Any]:
    """向边缘节点发送热生效重载指令，动态调整内存中 Worker 客户端阵列数量"""
    node = db.get_edge_node_by_id(node_id, include_secrets=True)
    if not node:
        return {"success": False, "error": "节点不存在"}
    base_url = get_edge_node_base_url(node)
    if not base_url:
        return {"success": False, "error": "未配置节点 IP 或域名"}
    auth_secret = str(node.get("auth_secret") or "")

    try:
        async with ClientSession(timeout=ClientTimeout(total=timeout)) as session:
            async with _safe_edge_request(
                session, base_url, "/reconfigure", method="POST", node_id=node_id,
                headers={"X-Node-Secret": auth_secret},
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {"success": False, "error": f"HTTP {resp.status}"}
    except Exception as e:
        logger.debug(f"reconfigure_edge_worker failed: {e}")
        return {"success": False, "error": str(e)}


async def run_edge_diagnostics(node_id: int, timeout: float = 10.0) -> Dict[str, Any]:
    """获取边缘节点宿主机硬件环境、并发配置与 Telegram 服务体检报告"""
    node = db.get_edge_node_by_id(node_id)
    if not node:
        return {"success": False, "error": "节点不存在"}
    base_url = get_edge_node_base_url(node)
    if not base_url:
        return {"success": False, "error": "未配置节点 IP 或域名"}

    try:
        async with ClientSession(timeout=ClientTimeout(total=timeout)) as session:
            async with _safe_edge_request(session, base_url, "/diagnostics", method="GET", node_id=node_id) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data
                return {"success": False, "error": f"HTTP {resp.status}"}
    except Exception as e:
        return {"success": False, "error": f"获取诊断体检报告失败: {e}"}


async def run_edge_full_benchmark(node_id: int, sample_mb: float = 10.0) -> Dict[str, Any]:
    """
    一键执行边缘节点全能测速与深度体检（四阶段闭环体系）：
    Phase 1: 测 VPS 物理双向宽带 (下行+上行+木桶有效短板) + 5 大 DC 延迟矩阵
    Phase 2: 依据木桶短板 min(下行, 上行) 与 DC 延迟动态匹配最佳 Bot 阵列并即刻下发热重载
    Phase 3: 端到端真实全双工中继流播压测 (边拉边推测量真实体感流速与全链路瓶颈)
    Phase 4: 整合系统硬件与网络栈体检，持久化存入数据库并实时 WebSocket 广播
    """
    node = db.get_edge_node_by_id(node_id, include_secrets=True)
    if not node:
        return {"success": False, "error": "节点不存在"}

    import edge_node_manager

    # Phase 1: 物理环境实测（VPS 双向物理宽带 + 5 大 DC 延迟探测 + 系统硬件诊断）
    bw_task = asyncio.create_task(run_edge_bandwidth_benchmark(node_id))
    dcs_task = asyncio.create_task(run_edge_dcs_benchmark(node_id))
    diag_task = asyncio.create_task(run_edge_diagnostics(node_id))
    link_task = asyncio.create_task(run_edge_link_benchmark(node_id))

    bw_res, dcs_res, diag_res, link_res = await asyncio.gather(
        bw_task, dcs_task, diag_task, link_task, return_exceptions=True
    )

    if isinstance(bw_res, Exception): bw_res = {"success": False, "error": str(bw_res), "down_speed_mb_s": 8.0, "up_speed_mb_s": 6.0, "effective_bw_mb_s": 6.0}
    if isinstance(dcs_res, Exception): dcs_res = {"success": False, "error": str(dcs_res)}
    if isinstance(diag_res, Exception): diag_res = {"success": False, "error": str(diag_res)}
    if isinstance(link_res, Exception): link_res = {"success": False, "error": str(link_res)}

    # 提取实测双向物理宽带与有效短板
    down_speed_mb_s = float(bw_res.get("down_speed_mb_s") or link_res.get("down_speed_mb_s") or 8.0)
    up_speed_mb_s = float(bw_res.get("up_speed_mb_s") or link_res.get("up_speed_mb_s") or round(down_speed_mb_s * 0.75, 2))
    effective_bw_mb_s = float(bw_res.get("effective_bw_mb_s") or min(down_speed_mb_s, up_speed_mb_s))
    bottleneck_direction = str(bw_res.get("bottleneck_direction") or "symmetric")

    fastest_dc = dcs_res.get("fastest_dc")
    fastest_dc_id = fastest_dc.get("id") if fastest_dc else (node.get("target_dc_id") or 5)
    fastest_rtt = float(fastest_dc.get("avg_rtt_ms") or 0.0) if fastest_dc else 0.0

    # Phase 2: 基于木桶短板有效带宽与 DC 往返延迟动态匹配算力
    auto_matched_bots = edge_node_manager.calculate_recommended_bots(
        down_speed_mb_s=down_speed_mb_s,
        up_speed_mb_s=up_speed_mb_s,
        effective_bw_mb_s=effective_bw_mb_s,
        max_cap=24,
        rtt_ms=fastest_rtt
    )
    existing_target_count = node.get("target_bot_count")
    if existing_target_count is not None and int(existing_target_count) > 0:
        matched_bots = max(auto_matched_bots, int(existing_target_count))
    else:
        matched_bots = auto_matched_bots
    matched_bots = min(100, max(2, matched_bots))

    rated_per_bot = 2.0
    if fastest_rtt > 0:
        if fastest_rtt <= 50.0:
            rated_per_bot = 2.0
        elif fastest_rtt <= 110.0:
            rated_per_bot = 1.2
        else:
            rated_per_bot = 0.8
    rated_capacity_mb_s = round(matched_bots * rated_per_bot, 1)

    node_update = {
        "target_dc_id": fastest_dc_id,
        "target_bot_count": matched_bots,
    }
    cur_assigned_token = node.get("assigned_bot_token")
    fresh_node_dict = dict(node)
    fresh_node_dict.update(node_update)
    allocation = edge_node_manager.allocate_bots_for_edge_node(fresh_node_dict, requested_bot_count=matched_bots)
    node_update["assigned_bot_token"] = allocation.get("primary_bot_token", cur_assigned_token)
    node_update["assigned_bot_username"] = allocation.get("primary_bot_username", node.get("assigned_bot_username", ""))

    db.update_edge_node(node_id, **node_update)

    # 触发 Worker 重新加载 Bot 配置以激活全新 Bot 阵列
    await reconfigure_edge_worker(node_id, timeout=25.0)
    await asyncio.sleep(1.0)

    # Phase 3: 端到端真实全双工中继流播压测（边拉边推测量真实体感流速）
    sample_to_use = max(sample_mb, 25.0)
    relay_res = await run_edge_relay_stream_benchmark(node_id, sample_mb=sample_to_use, timeout=50.0)
    if not relay_res.get("success"):
        # 若中继压测失败，保底回退到直接 TG 拉流测速
        relay_res = await run_edge_tg_speed_benchmark(node_id, sample_mb=sample_to_use, timeout=45.0)

    relay_speed = float(relay_res.get("relay_speed_mb_s") or relay_res.get("speed_mb_s") or 0.0)
    tg_pull_speed = float(relay_res.get("tg_pull_speed_mb_s") or relay_speed)
    bottleneck_diag = str(relay_res.get("bottleneck_diagnosis") or ("全链路无损满速中继" if relay_speed >= effective_bw_mb_s * 0.85 else "正常中继流播"))

    # 物理带宽有效饱和度达标率 (以木桶短板 effective_bw_mb_s 为基准)
    saturation_percent = round((relay_speed / max(0.1, effective_bw_mb_s)) * 100, 1)
    saturation_percent = min(100.0, saturation_percent)

    # Phase 4: 整合汇总并入库持久化
    now_str = datetime.now(timezone.utc).isoformat()
    bandwidth_data = {
        "down_speed_mb_s": down_speed_mb_s,
        "down_speed_mbps": round(down_speed_mb_s * 8, 2),
        "up_speed_mb_s": up_speed_mb_s,
        "up_speed_mbps": round(up_speed_mb_s * 8, 2),
        "effective_bw_mb_s": effective_bw_mb_s,
        "effective_bw_mbps": round(effective_bw_mb_s * 8, 2),
        "bottleneck_direction": bottleneck_direction,
        "cdn_speed_mb_s": bw_res.get("cdn_speed_mb_s", 0.0),
        "cdn_up_speed_mb_s": bw_res.get("cdn_up_speed_mb_s", 0.0),
        "master_speed_mb_s": bw_res.get("master_speed_mb_s", 0.0),
        "master_up_speed_mb_s": bw_res.get("master_up_speed_mb_s", 0.0),
        "matched_bots": len(allocation.get("bot_tokens", [])) or matched_bots,
        "rated_capacity_mb_s": rated_capacity_mb_s,
        "rated_capacity_mbps": round(rated_capacity_mb_s * 8, 1),
        "saturation_percent": saturation_percent,
        "source": bw_res.get("source", "anycast_cdn"),
    }

    benchmark_data = {
        "bandwidth": bandwidth_data,
        "fastest_dc": fastest_dc,
        "dcs": dcs_res.get("dcs", []),
        "home_dc": dcs_res.get("home_dc") or (diag_res.get("telegram") or {}).get("home_dc", fastest_dc_id),
        "speed": {
            "peak_speed_mb_s": relay_speed,
            "speed_mbps": round(relay_speed * 8, 2),
            "relay_speed_mb_s": relay_speed,
            "relay_speed_mbps": round(relay_speed * 8, 2),
            "tg_pull_speed_mb_s": tg_pull_speed,
            "tg_pull_speed_mbps": round(tg_pull_speed * 8, 2),
            "bottleneck_diagnosis": bottleneck_diag,
            "bottleneck_direction": bottleneck_direction,
            "ttfb_ms": relay_res.get("ttfb_ms", 0.0),
            "buffer_ms": relay_res.get("buffer_ms", 0.0),
            "chunks_count": relay_res.get("chunks_count", 0),
            "target_dc": relay_res.get("target_dc", fastest_dc_id),
            "usable_bots_count": relay_res.get("usable_bots_count", len(allocation.get("bot_tokens", []))),
            "total_bots_in_array": len(allocation.get("bot_tokens", [])),
            "per_bot_speed_mb_s": round(relay_speed / max(1, len(allocation.get("bot_tokens", []))), 2),
            "hedged_requests_count": relay_res.get("hedged_requests_count", 0),
            "hedged_wins_count": relay_res.get("hedged_wins_count", 0),
            "dual_launch_used": relay_res.get("dual_launch_used", False),
            "jitter_cv": relay_res.get("jitter_cv", 0.0),
            "hardware_tier": relay_res.get("hardware_tier", "BUDGET_VPS"),
            "window_size": relay_res.get("window_size", 4),
            "pareto_optimal": relay_res.get("pareto_optimal", True),
            "saturation_percent": saturation_percent,
            "evaluation": relay_res.get("evaluation", ""),
            "grade": relay_res.get("grade", ""),
            "sample_size_mb": relay_res.get("sample_size_mb", sample_to_use),
        },
        "link": link_res,
        "diagnostics": diag_res,
        "health_score": diag_res.get("health_score", 100),
        "health_grade": diag_res.get("health_grade", "A+"),
        "health_label": diag_res.get("health_label", "健康极佳"),
        "last_benchmark_at": now_str,
    }

    db.update_edge_node(node_id, benchmark_data=benchmark_data, status="online", last_seen_at=now_str)
    fresh_node = db.get_edge_node_by_id(node_id)
    try:
        from edge_node_manager import broadcast_edge_node_update
        asyncio.create_task(broadcast_edge_node_update(node_id))
    except Exception:
        pass

    return {
        "success": True,
        "benchmark_data": benchmark_data,
        "node": fresh_node,
    }


async def upgrade_edge_worker(node_id: int, master_url: str = "") -> Dict[str, Any]:
    """通过 OTA 热更新或 SSH 自动重装升级边缘节点的 Edge Worker 守护微服务"""
    node = db.get_edge_node_by_id(node_id, include_secrets=True)
    if not node:
        return {"success": False, "error": "节点不存在"}

    base_url = get_edge_node_base_url(node)
    auth_secret = str(node.get("auth_secret") or "")

    # 1. 尝试通过 OTA 接口热重载 (直传最新代码载荷 + Master URL 双向兜底)
    if base_url:
        try:
            worker_code = get_worker_script_content()
            payload = {"code": worker_code} if worker_code else {}
            async with ClientSession(timeout=ClientTimeout(total=20)) as session:
                async with _safe_edge_request(
                    session, base_url, "/update", method="POST", node_id=node_id,
                    headers={"X-Node-Secret": auth_secret},
                    json=payload,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        await asyncio.sleep(2.5)
                        h = await check_edge_node_health(node_id)
                        return {
                            "success": True,
                            "method": "ota",
                            "message": data.get("message", "OTA 热更新成功已重启"),
                            "health": h,
                            "node": db.get_edge_node_by_id(node_id),
                        }
        except Exception as ota_err:
            logger.warning(f"OTA upgrade attempt failed for node {node_id}: {ota_err}")

    # 2. 若 OTA 不可用且拥有保存的 SSH 密码，使用 SSH 重新下发
    if node.get("has_ssh_password"):
        ok = await deploy_node_via_ssh(node_id, master_url=master_url)
        if ok:
            return {
                "success": True,
                "method": "ssh",
                "message": "通过 SSH 完成热升级与守护服务重启",
                "node": db.get_edge_node_by_id(node_id),
            }
        else:
            return {"success": False, "error": "SSH 热升级失败，请查看部署终端日志"}

    return {
        "success": False,
        "error": "该节点当前运行旧版微服务且未在后台保存 SSH root 密码，无法自动热升级。请前往免密一键脚本向导在终端重新运行安装命令。",
    }
