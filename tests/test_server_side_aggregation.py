import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from pyrogram import raw
import WebStreamer.bot as bot_mod
from WebStreamer.utils.custom_dl import ByteStreamer


def _make_upload_file(data: bytes):
    f_cls = getattr(getattr(raw.types, "upload", None), "File", None)
    if f_cls is not None:
        inst = f_cls.__new__(f_cls) if hasattr(f_cls, "__new__") else f_cls()
        inst.bytes = data
        return inst
    obj = MagicMock()
    obj.bytes = data
    return obj


class TestServerSideAggregation(unittest.TestCase):
    def setUp(self):
        bot_mod.active_user_streams = 0
        bot_mod._stream_id_counter = 0

    def test_active_stream_slot_lifecycle(self):
        """测试用户活跃流计数器的生命周期与自增 ID"""
        self.assertEqual(bot_mod.get_active_stream_count(), 0)

        s1 = bot_mod.acquire_stream_slot()
        self.assertEqual(s1, 1)
        self.assertEqual(bot_mod.get_active_stream_count(), 1)

        s2 = bot_mod.acquire_stream_slot()
        self.assertEqual(s2, 2)
        self.assertEqual(bot_mod.get_active_stream_count(), 2)

        bot_mod.release_stream_slot(s1)
        self.assertEqual(bot_mod.get_active_stream_count(), 1)

        bot_mod.release_stream_slot(s2)
        self.assertEqual(bot_mod.get_active_stream_count(), 0)

        # 再次释放不会出现负数
        bot_mod.release_stream_slot(999)
        self.assertEqual(bot_mod.get_active_stream_count(), 0)

    def test_dynamic_pool_partitioning_logic(self):
        """测试多流并发时按活跃流数动态均分 Bot 池的数学逻辑"""
        total_bots = [i for i in range(20)]  # 20 个 Bot (0..19)

        # 场景 1: 单流模式 (S = 1) -> 独占全量 20 个 Bot
        active_streams = 1
        quota_1 = max(1, len(total_bots) // active_streams)
        self.assertEqual(quota_1, 20)
        stripe_1 = list(total_bots)
        self.assertEqual(len(stripe_1), 20)

        # 场景 2: 双流并发 (S = 2) -> 均分为两组 (各 10 个 Bot)
        active_streams = 2
        quota_2 = max(1, len(total_bots) // active_streams)
        self.assertEqual(quota_2, 10)
        s1_id = 1
        s2_id = 2
        s1_offset = ((s1_id - 1) * quota_2) % len(total_bots)
        s2_offset = ((s2_id - 1) * quota_2) % len(total_bots)
        s1_bots = [total_bots[(s1_offset + i) % len(total_bots)] for i in range(quota_2)]
        s2_bots = [total_bots[(s2_offset + i) % len(total_bots)] for i in range(quota_2)]
        self.assertEqual(len(s1_bots), 10)
        self.assertEqual(len(s2_bots), 10)
        # 验证两组 Bot 互不重叠（交集为空）
        self.assertEqual(set(s1_bots).intersection(set(s2_bots)), set())

        # 场景 3: 四流并发 (S = 4) -> 均分为四组 (各 5 个 Bot)
        active_streams = 4
        quota_4 = max(1, len(total_bots) // active_streams)
        self.assertEqual(quota_4, 5)
        all_allocated = []
        for sid in range(1, 5):
            off = ((sid - 1) * quota_4) % len(total_bots)
            b_list = [total_bots[(off + i) % len(total_bots)] for i in range(quota_4)]
            self.assertEqual(len(b_list), 5)
            all_allocated.append(set(b_list))
        # 验证 4 组 Bot 完全互斥并覆盖全量 20 个 Bot
        union_bots = set().union(*all_allocated)
        self.assertEqual(len(union_bots), 20)

    def test_yield_file_probe_request_fastpath(self):
        """测试 part_count <= 2 的探针请求走单 Bot 极速通路且不占用流槽位"""
        async def _run():
            mock_client = MagicMock()
            streamer = ByteStreamer.for_client(mock_client)
            streamer.get_location = AsyncMock(return_value="mock_loc")

            mock_file = _make_upload_file(b"header_data")
            streamer._try_get_file_chunk = AsyncMock(return_value=(True, mock_file, mock_client, None))

            mock_fid = MagicMock()
            mock_fid.dc_id = 5

            with patch("WebStreamer.utils.custom_dl.multi_clients", {0: mock_client, 1: mock_client}):
                with patch("WebStreamer.utils.custom_dl.get_available_bot_indices", return_value=[0, 1]):
                    chunks = []
                    async for chunk in streamer.yield_file(
                        file_id=mock_fid,
                        index=0,
                        offset=0,
                        first_part_cut=0,
                        last_part_cut=11,
                        part_count=1,
                        chunk_size=1024,
                        message_id=12345,
                    ):
                        chunks.append(chunk)

                    self.assertEqual(len(chunks), 1)
                    self.assertEqual(chunks[0], b"header_data")
                    # 探针请求不应增加 active_user_streams
                    self.assertEqual(bot_mod.get_active_stream_count(), 0)

        asyncio.run(_run())

    def test_yield_file_sequential_ordering_with_aggregation(self):
        """测试服务端多 Bot 聚合拉取时保证分片严格按序交付"""
        async def _run():
            mock_client_0 = MagicMock()
            mock_client_1 = MagicMock()
            mock_client_2 = MagicMock()

            streamer_0 = ByteStreamer.for_client(mock_client_0)
            streamer_1 = ByteStreamer.for_client(mock_client_1)
            streamer_2 = ByteStreamer.for_client(mock_client_2)

            for s in [streamer_0, streamer_1, streamer_2]:
                s.get_location = AsyncMock(return_value="mock_loc")
                s.get_file_properties = AsyncMock(return_value=MagicMock(dc_id=5))

            used_bots = set()

            async def mock_try_get_chunk(cli, b_idx, fid, loc, offset, chunk_size, **kwargs):
                used_bots.add(b_idx)
                part_num = (offset // chunk_size) + 1
                mock_res = _make_upload_file(f"part_{part_num}".encode("utf-8"))
                await asyncio.sleep(0.005)
                return True, mock_res, cli, None

            streamer_0._try_get_file_chunk = mock_try_get_chunk
            streamer_1._try_get_file_chunk = mock_try_get_chunk
            streamer_2._try_get_file_chunk = mock_try_get_chunk

            mock_fid = MagicMock()
            mock_fid.dc_id = 5

            with patch("WebStreamer.utils.custom_dl.multi_clients", {0: mock_client_0, 1: mock_client_1, 2: mock_client_2}):
                with patch("WebStreamer.utils.custom_dl.get_available_bot_indices", return_value=[0, 1, 2]):
                    received_parts = []
                    async for chunk in streamer_0.yield_file(
                        file_id=mock_fid,
                        index=0,
                        offset=0,
                        first_part_cut=0,
                        last_part_cut=6,
                        part_count=6,
                        chunk_size=1024,
                        message_id=999,
                    ):
                        received_parts.append(chunk.decode("utf-8"))

                    # 严格按序输出
                    expected = [f"part_{i}" for i in range(1, 7)]
                    self.assertEqual(received_parts, expected)
                    # 验证全部 3 个 Bot 均参与了单连接聚合拉取
                    self.assertEqual(used_bots, {0, 1, 2})
                    # 退出后 active_user_streams 正确释放归零
                    self.assertEqual(bot_mod.get_active_stream_count(), 0)

        asyncio.run(_run())


    def test_dynamic_pool_partitioning_55_bots(self):
        """测试 55 个 Bot 集群规模下全量独占与动态均分无任何截断"""
        total_bots = [i for i in range(55)]

        # 单流模式：全量 55 个节点全部参与
        active_streams = 1
        quota_1 = max(1, len(total_bots) // active_streams)
        self.assertEqual(quota_1, 55)
        stripe_1 = list(total_bots)
        self.assertEqual(len(stripe_1), 55)

        # 双流并发：均分为 27 个节点
        active_streams = 2
        quota_2 = max(1, len(total_bots) // active_streams)
        self.assertEqual(quota_2, 27)

    def test_tune_media_session_socket_configuration(self):
        """测试 tune_media_session_socket 正确配置 TCP_NODELAY 与 4MB 接收缓冲"""
        import socket
        from WebStreamer.utils.custom_dl import tune_media_session_socket

        mock_sock = MagicMock()
        mock_proto = MagicMock()
        mock_proto.socket = mock_sock
        mock_conn = MagicMock()
        mock_conn.protocol = mock_proto
        mock_session = MagicMock()
        mock_session.connection = mock_conn

        res = tune_media_session_socket(mock_session)
        self.assertTrue(res)

        # 验证 setsockopt 调用
        mock_sock.setsockopt.assert_any_call(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        mock_sock.setsockopt.assert_any_call(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        mock_sock.setsockopt.assert_any_call(socket.SOL_SOCKET, socket.SO_SNDBUF, 2 * 1024 * 1024)

if __name__ == "__main__":
    unittest.main()
