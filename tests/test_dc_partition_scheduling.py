import tests  # noqa: F401
import os
import sys
import unittest
from types import SimpleNamespace

if "pyrogram" not in sys.modules:
    import types
    pyrogram_mod = types.ModuleType("pyrogram")
    pyrogram_mod.__path__ = []
    pyrogram_file_id = types.ModuleType("pyrogram.file_id")
    class DummyFileId:
        def __init__(self, dc_id=5):
            self.dc_id = dc_id
            self.file_type = 4
        @classmethod
        def decode(cls, s):
            # If string contains 'dc1' or 'dc4', decode accordingly
            if "dc1" in str(s).lower():
                return DummyFileId(dc_id=1)
            elif "dc4" in str(s).lower():
                return DummyFileId(dc_id=4)
            return DummyFileId(dc_id=5)
    pyrogram_file_id.FileId = DummyFileId
    pyrogram_mod.file_id = pyrogram_file_id
    sys.modules["pyrogram"] = pyrogram_mod
    sys.modules["pyrogram.file_id"] = pyrogram_file_id

import WebStreamer.bot as bot_mod
from WebStreamer.utils.custom_dl import get_available_bot_indices


class TestDCPartitionScheduling(unittest.TestCase):
    def setUp(self):
        bot_mod.multi_clients.clear()
        bot_mod.work_loads.clear()
        bot_mod.bot_runtime.clear()
        bot_mod.channel_accessible_clients.clear()
        bot_mod.channel_write_clients.clear()
        bot_mod.bot_channel_modes.clear()

        # 模拟 4 个测试客户端
        # bot 0: DC5 (主控)
        # bot 1: DC1
        # bot 2: DC5
        # bot 3: DC4 (热连接 DC5)
        for i in range(4):
            cli = SimpleNamespace(username=f"bot_{i}", is_connected=True)
            bot_mod.multi_clients[i] = cli
            bot_mod.register_bot_client(i)
            bot_mod.channel_accessible_clients.add(i)

        bot_mod.set_bot_home_dc(0, 5)
        bot_mod.set_bot_home_dc(1, 1)
        bot_mod.set_bot_home_dc(2, 5)
        bot_mod.set_bot_home_dc(3, 4)
        bot_mod.mark_bot_warm_dc(3, 5)  # bot 3 已预热 DC5

    def tearDown(self):
        bot_mod.multi_clients.clear()
        bot_mod.work_loads.clear()
        bot_mod.bot_runtime.clear()

    def test_dc_runtime_and_summary(self):
        """测试 DC 运行时属性与分区汇总统计"""
        sample_records = [
            {"file_id": "test_dc5_fid_1"},
            {"file_id": "test_dc5_fid_2"},
            {"file_id": "test_dc1_fid_3"},
            {"file_id": "test_dc4_fid_4"},
        ]
        summary = bot_mod.get_dc_partition_summary(sample_records)
        
        # DC5: home_bots 应包含 0 和 2，warm_bots 包含 0, 2, 3
        self.assertIn(0, summary["5"]["home_bots"])
        self.assertIn(2, summary["5"]["home_bots"])
        self.assertIn(3, summary["5"]["warm_bots"])
        self.assertEqual(summary["5"]["files_count"], 2)

        # DC1: home_bots 应包含 1
        self.assertIn(1, summary["1"]["home_bots"])
        self.assertEqual(summary["1"]["files_count"], 1)

        # DC4: home_bots 应包含 3
        self.assertIn(3, summary["4"]["home_bots"])
        self.assertEqual(summary["4"]["files_count"], 1)

    def test_select_stream_bot_dc_affinity(self):
        """测试调度器在指定 target_dc 时优先选择同区节点"""
        # 请求 DC5 文件：应从同区 0 或 2 中选取
        selected = bot_mod.select_stream_bot(target_dc=5)
        self.assertIn(selected, [0, 2])

        # 请求 DC1 文件：应直接命中 bot 1
        selected_dc1 = bot_mod.select_stream_bot(target_dc=1)
        self.assertEqual(selected_dc1, 1)

        # 请求 DC4 文件：应直接命中 bot 3
        selected_dc4 = bot_mod.select_stream_bot(target_dc=4)
        self.assertEqual(selected_dc4, 3)

    def test_select_stream_bot_spillover(self):
        """测试当同区节点高负载时平滑溢出至预热节点与冷节点"""
        # 令同区节点 0 和 2 处于较高并发负载 (各 3 个并发)
        bot_mod.work_loads[0] = 3
        bot_mod.work_loads[2] = 3

        # 请求 DC5 文件：此时 bot 3 具备 warm_dcs={5} 且负载为 0，惩罚 0.2 < 3.0，优先溢出到 bot 3
        selected = bot_mod.select_stream_bot(target_dc=5)
        self.assertEqual(selected, 3)

        # 令 bot 3 也处于高负载 (3 个并发)
        bot_mod.work_loads[3] = 3

        # 请求 DC5 文件：bot 1 虽然是冷节点 (惩罚 0.5)，但负载为 0，0.5 < 3.0，平滑溢出到 bot 1
        selected_cold = bot_mod.select_stream_bot(target_dc=5)
        self.assertEqual(selected_cold, 1)

    def test_get_available_bot_indices_sorting(self):
        """测试条带化（Striping）候选 Bot 队列按 DC 亲和性排序"""
        # 目标 DC5：排序应为同区 (0, 2) -> 预热区 (3) -> 跨区冷节点 (1)
        ordered = get_available_bot_indices(primary_index=0, target_dc=5)
        self.assertEqual(ordered[0], 0)
        self.assertEqual(ordered[1], 2)
        self.assertEqual(ordered[2], 3)
        self.assertEqual(ordered[3], 1)


if __name__ == "__main__":
    unittest.main()
