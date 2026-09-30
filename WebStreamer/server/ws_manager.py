"""
WebSocket 连接管理器
用于管理所有 WebSocket 客户端连接，并推送实时状态更新（支持多租户按 user_id / role 隔离广播）
"""
import asyncio
import json
import logging
from typing import Set, Dict, Any, Optional
from aiohttp import web
from threading import Lock

logger = logging.getLogger(__name__)


class WebSocketManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self.connections: Set[web.WebSocketResponse] = set()
        self.connection_meta: Dict[web.WebSocketResponse, Dict[str, Any]] = {}
        self.lock = asyncio.Lock()
        # 为每种消息类型维护独立的序列号生成器（线程安全）
        self._seq_lock = Lock()
        self._sequence_numbers: Dict[str, int] = {
            "download_update": 0,
            "upload_update": 0,
            "cleanup_update": 0,
            "statistics_update": 0,
            "edge_node_update": 0,
            "edge_nodes_update": 0,
            "edge_deploy_log": 0,
            "edge_node_deleted": 0,
            "edge_token_used": 0,
        }

    def _get_next_seq(self, message_type: str) -> int:
        """获取指定消息类型的下一个序列号（线程安全）"""
        with self._seq_lock:
            if message_type not in self._sequence_numbers:
                self._sequence_numbers[message_type] = 0
            self._sequence_numbers[message_type] += 1
            return self._sequence_numbers[message_type]

    def start_background_broadcast_task(self):
        """启动后台定时状态推送任务，提供真实实时推流体验"""
        if hasattr(self, "_bg_task") and self._bg_task and not self._bg_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._bg_task = loop.create_task(self._background_broadcast_loop())
        except RuntimeError:
            pass

    async def _background_broadcast_loop(self):
        while True:
            try:
                await asyncio.sleep(3.0)
                if not self.connections:
                    continue
                import db
                from edge_node_manager import compute_edge_summary
                all_nodes = db.list_edge_nodes(tenant_id=None, include_secrets=False)
                if not all_nodes:
                    continue

                # 自动对失联节点执行超时收敛与指标归零（超过 45 秒未上报心跳）
                from datetime import datetime, timezone
                now_utc = datetime.now(timezone.utc)
                for n in all_nodes:
                    if n.get("status") == "online":
                        last_seen = n.get("last_seen_at")
                        is_stale = False
                        if last_seen:
                            try:
                                dt = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
                                if dt.tzinfo is None:
                                    dt = dt.replace(tzinfo=timezone.utc)
                                if (now_utc - dt).total_seconds() > 45.0:
                                    is_stale = True
                            except Exception:
                                pass
                        if is_stale:
                            n["status"] = "offline"
                            metrics = dict(n.get("metrics") or {})
                            metrics.update({"active_streams": 0, "net_tx": 0, "net_rx": 0, "cpu": 0.0})
                            n["metrics"] = metrics
                            try:
                                db.update_edge_node(n["id"], status="offline", metrics=metrics)
                            except Exception:
                                pass
                
                admin_summary = compute_edge_summary(all_nodes)
                await self.send_edge_nodes_update(
                    nodes_data=all_nodes,
                    summary=admin_summary,
                    target_user_id=None,
                )
                
                tenant_uids = self.get_connected_tenant_user_ids()
                for uid in tenant_uids:
                    t_nodes = [n for n in all_nodes if n.get("tenant_id") == uid]
                    t_summary = compute_edge_summary(t_nodes)
                    await self.send_edge_nodes_update(
                        nodes_data=t_nodes,
                        summary=t_summary,
                        target_user_id=uid,
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"后台边缘节点广播异常: {e}")

    async def add_connection(
        self,
        ws: web.WebSocketResponse,
        user_id: Optional[int] = None,
        role: str = "admin",
    ):
        """添加 WebSocket 连接并记录租户身份"""
        async with self.lock:
            self.connections.add(ws)
            self.connection_meta[ws] = {
                "user_id": user_id,
                "role": role or "admin",
            }
            logger.info(f"WebSocket 连接已添加，当前连接数: {len(self.connections)}")
            self.start_background_broadcast_task()

    async def remove_connection(self, ws: web.WebSocketResponse):
        """移除 WebSocket 连接"""
        async with self.lock:
            self.connections.discard(ws)
            self.connection_meta.pop(ws, None)
            logger.info(f"WebSocket 连接已移除，当前连接数: {len(self.connections)}")

    def get_connected_tenant_user_ids(self) -> Set[int]:
        """获取当前在线的所有非管理员租户 user_id 集合"""
        uids: Set[int] = set()
        for ws, meta in list(self.connection_meta.items()):
            if not getattr(ws, "closed", False) and meta.get("role") != "admin" and meta.get("user_id") is not None:
                uids.add(int(meta["user_id"]))
        return uids

    async def broadcast(
        self,
        message: Dict[str, Any],
        target_user_id: Optional[int] = None,
        admin_only: bool = False,
        exact_target: bool = False,
    ):
        """广播消息到符合权限范围的连接的客户端"""
        if not self.connections:
            return

        message_json = json.dumps(message, ensure_ascii=False)
        disconnected = set()

        async with self.lock:
            for ws in self.connections:
                try:
                    if ws.closed:
                        disconnected.add(ws)
                        continue
                    meta = self.connection_meta.get(ws, {"role": "admin", "user_id": None})
                    role = meta.get("role", "admin")
                    conn_uid = meta.get("user_id")

                    # 1. 仅限管理员接收的消息，非管理员跳过
                    if admin_only and role != "admin":
                        continue

                    # 2. 精确目标用户推送：仅目标用户本人可接收（管理员若非本人也不接收，防止租户数据冲刷管理员全局视角）
                    if target_user_id is not None and exact_target and conn_uid != target_user_id:
                        continue

                    # 3. 普通目标用户推送（附带管理员旁路监听）：目标用户本人接收，管理员默认可旁路监听
                    if target_user_id is not None and not exact_target and role != "admin" and conn_uid != target_user_id:
                        continue

                    await ws.send_str(message_json)
                except Exception as e:
                    logger.error(f"发送 WebSocket 消息失败: {e}", exc_info=True)
                    disconnected.add(ws)

            # 清理已断开的连接
            for ws in disconnected:
                self.connections.discard(ws)
                self.connection_meta.pop(ws, None)

    async def send_download_update(self, download_data: Dict[str, Any], target_user_id: Optional[int] = None):
        """发送下载状态更新（按任务所属租户隔离）"""
        uid = target_user_id if target_user_id is not None else download_data.get("user_id")
        await self.broadcast(
            {
                "type": "download_update",
                "seq": self._get_next_seq("download_update"),
                "data": download_data,
            },
            target_user_id=uid,
            admin_only=(uid is None),
        )

    async def send_upload_update(self, upload_data: Dict[str, Any], target_user_id: Optional[int] = None):
        """发送上传状态更新（按任务所属租户隔离）"""
        uid = target_user_id if target_user_id is not None else upload_data.get("user_id")
        await self.broadcast(
            {
                "type": "upload_update",
                "seq": self._get_next_seq("upload_update"),
                "data": upload_data,
            },
            target_user_id=uid,
            admin_only=(uid is None),
        )

    async def send_cleanup_update(self, cleanup_data: Dict[str, Any], target_user_id: Optional[int] = None):
        """发送清理状态更新（按任务所属租户隔离）"""
        uid = target_user_id if target_user_id is not None else cleanup_data.get("user_id")
        await self.broadcast(
            {
                "type": "cleanup_update",
                "seq": self._get_next_seq("cleanup_update"),
                "data": cleanup_data,
            },
            target_user_id=uid,
            admin_only=(uid is None),
        )

    async def send_statistics_update(self, statistics: Dict[str, Any], target_user_id: Optional[int] = None):
        """发送统计信息更新（按管理员或指定租户推送，租户数据不污染管理员全局视角）"""
        await self.broadcast(
            {
                "type": "statistics_update",
                "seq": self._get_next_seq("statistics_update"),
                "data": statistics,
            },
            target_user_id=target_user_id,
            admin_only=(target_user_id is None),
            exact_target=(target_user_id is not None),
        )


    async def send_edge_node_update(
        self,
        node_data: Dict[str, Any],
        summary: Optional[Dict[str, Any]] = None,
        target_user_id: Optional[int] = None,
        admin_only: Optional[bool] = None,
        exact_target: bool = False,
    ):
        """发送单个边缘节点更新（负载指标、状态、健康度等）"""
        if admin_only is None:
            uid = target_user_id if target_user_id is not None else node_data.get("tenant_id")
            is_admin_only = (target_user_id is None and not node_data.get("tenant_id"))
        else:
            uid = target_user_id
            is_admin_only = admin_only

        await self.broadcast(
            {
                "type": "edge_node_update",
                "seq": self._get_next_seq("edge_node_update"),
                "data": {
                    "node": node_data,
                    "summary": summary,
                },
            },
            target_user_id=uid,
            admin_only=is_admin_only,
            exact_target=exact_target,
        )

    async def send_edge_nodes_update(
        self,
        nodes_data: list,
        summary: Optional[Dict[str, Any]] = None,
        target_user_id: Optional[int] = None,
    ):
        """发送全量或租户边缘节点列表更新（租户节点列表严格定向推送，绝不污染覆盖管理员全集群列表）"""
        await self.broadcast(
            {
                "type": "edge_nodes_update",
                "seq": self._get_next_seq("edge_nodes_update"),
                "data": {
                    "nodes": nodes_data,
                    "summary": summary,
                },
            },
            target_user_id=target_user_id,
            admin_only=(target_user_id is None),
            exact_target=(target_user_id is not None),
        )

    async def send_edge_deploy_log(
        self,
        node_id: int,
        line: Optional[str] = None,
        deploy_log: Optional[str] = None,
        status: Optional[str] = None,
        target_user_id: Optional[int] = None,
    ):
        """实时推送边缘节点部署终端日志流"""
        await self.broadcast(
            {
                "type": "edge_deploy_log",
                "seq": self._get_next_seq("edge_deploy_log"),
                "data": {
                    "node_id": node_id,
                    "line": line,
                    "deploy_log": deploy_log,
                    "status": status,
                },
            },
            target_user_id=target_user_id,
            admin_only=(target_user_id is None),
        )

    async def send_edge_node_deleted(
        self,
        node_id: int,
        summary: Optional[Dict[str, Any]] = None,
        target_user_id: Optional[int] = None,
        exact_target: bool = False,
    ):
        """发送边缘节点删除事件"""
        await self.broadcast(
            {
                "type": "edge_node_deleted",
                "seq": self._get_next_seq("edge_node_deleted"),
                "data": {
                    "node_id": node_id,
                    "summary": summary,
                },
            },
            target_user_id=target_user_id,
            admin_only=(target_user_id is None),
            exact_target=exact_target,
        )

    async def send_edge_token_used(
        self,
        token: str,
        node_data: Dict[str, Any],
        target_user_id: Optional[int] = None,
    ):
        """发送免密一键脚本配对成功事件"""
        uid = target_user_id if target_user_id is not None else node_data.get("tenant_id")
        await self.broadcast(
            {
                "type": "edge_token_used",
                "seq": self._get_next_seq("edge_token_used"),
                "data": {
                    "token": token,
                    "node": node_data,
                },
            },
            target_user_id=uid,
            admin_only=(uid is None),
        )


# 全局 WebSocket 管理器实例
ws_manager = WebSocketManager()
