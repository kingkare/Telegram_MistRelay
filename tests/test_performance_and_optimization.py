import tests  # noqa: F401
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

import db


def _make_mock_media(
    chat_id: int,
    message_id: int,
    file_name: str,
    file_unique_id: str,
    file_size: int = 1024,
    mime_type: str = "video/mp4",
    media_group_id: str = None,
    msg_date = None,
):
    msg = SimpleNamespace(
        id=message_id,
        caption="test caption",
        media_group_id=media_group_id,
        date=msg_date,
        chat=SimpleNamespace(id=chat_id)
    )
    media = SimpleNamespace(
        file_unique_id=file_unique_id,
        file_id=f"fid_{file_unique_id}",
        file_name=file_name,
        file_size=file_size,
        mime_type=mime_type
    )
    return msg, media


class TestPerformanceAndOptimization(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self._tmp.name
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        if hasattr(self, "_tmp") and os.path.exists(self._tmp.name):
            try:
                os.remove(self._tmp.name)
            except OSError:
                pass

    def test_sqlite_engine_pragmas(self):
        """验证连接层已启用 NORMAL 级别刷盘、64MB 缓存、内存临时表与 mmap 映射"""
        with db.db_conn() as conn:
            sync = conn.execute("PRAGMA synchronous;").fetchone()[0]
            cache = conn.execute("PRAGMA cache_size;").fetchone()[0]
            temp_store = conn.execute("PRAGMA temp_store;").fetchone()[0]
            mmap = conn.execute("PRAGMA mmap_size;").fetchone()[0]
            fk = conn.execute("PRAGMA foreign_keys;").fetchone()[0]

            self.assertEqual(sync, 1, "synchronous should be 1 (NORMAL)")
            self.assertEqual(cache, -64000, "cache_size should be -64000 (64MB)")
            self.assertEqual(temp_store, 2, "temp_store should be 2 (MEMORY)")
            self.assertEqual(mmap, 268435456, "mmap_size should be 268435456 (256MB)")
            self.assertEqual(fk, 1, "foreign_keys should be ON")

    def test_indexes_created_and_redundancy_cleaned(self):
        """验证关键高频索引已建立，且冗余同构索引已清除"""
        with db.db_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
            idx_names = {row[0] for row in cur.fetchall()}

            # 验证新增的覆盖索引
            self.assertIn("idx_tg_media_chat_date", idx_names)
            self.assertIn("idx_tg_media_chat_message", idx_names)
            self.assertIn("idx_downloads_user_id", idx_names)
            self.assertIn("idx_edge_tokens_tenant", idx_names)
            self.assertIn("idx_edge_tokens_node", idx_names)

            # 验证历史冗余重复索引已被移除
            self.assertNotIn("idx_tg_media_chat_msg", idx_names)

    def test_query_plans_use_covering_indexes(self):
        """验证查询执行计划使用新索引，消除全表扫描与临时 B-Tree 排序"""
        with db.db_conn() as conn:
            cur = conn.cursor()

            # 1. 验证按频道日期排序使用 idx_tg_media_chat_date，且没有 USE TEMP B-TREE
            media_plan = cur.execute(
                "EXPLAIN QUERY PLAN SELECT file_unique_id FROM tg_media WHERE chat_id = ? ORDER BY message_date DESC",
                (1001,),
            ).fetchall()
            media_plan_str = " ".join(str(r[3]) for r in media_plan)
            self.assertIn("idx_tg_media_chat_date", media_plan_str)
            self.assertNotIn("TEMP B-TREE", media_plan_str)

            # 2. 验证 downloads 表按 user_id 检索使用索引，消除 SCAN
            dl_plan = cur.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM downloads WHERE user_id = ?",
                (1,),
            ).fetchall()
            dl_plan_str = " ".join(str(r[3]) for r in dl_plan)
            self.assertIn("idx_downloads_user_id", dl_plan_str)
            self.assertNotIn("SCAN downloads", dl_plan_str)

    def test_single_sql_get_tg_media_stats(self):
        """验证合并为单条 SQL 的 get_tg_media_stats 统计准确无误"""
        # 1. 空表统计
        stats_empty = db.get_tg_media_stats()
        self.assertEqual(stats_empty, {
            'total_count': 0,
            'total_size': 0,
            'videos': 0,
            'images': 0,
            'audios': 0,
            'documents': 0,
        })

        # 2. 插入多种类型媒体数据（跨 2 个 chat_id）
        msg1, med1 = _make_mock_media(1001, 1, "v1.mp4", "uid_v1", file_size=1000, mime_type="video/mp4")
        msg2, med2 = _make_mock_media(1001, 2, "p1.png", "uid_p1", file_size=200, mime_type="image/png")
        msg3, med3 = _make_mock_media(1001, 3, "a1.mp3", "uid_a1", file_size=500, mime_type="audio/mpeg")
        msg4, med4 = _make_mock_media(1001, 4, "d1.pdf", "uid_d1", file_size=300, mime_type="application/pdf")
        msg5, med5 = _make_mock_media(1002, 10, "v2.mkv", "uid_v2", file_size=2000, mime_type="video/x-matroska")

        for m, med in [(msg1, med1), (msg2, med2), (msg3, med3), (msg4, med4), (msg5, med5)]:
            db.save_tg_media(m, med)

        # 3. 统计全站
        stats_all = db.get_tg_media_stats()
        self.assertEqual(stats_all['total_count'], 5)
        self.assertEqual(stats_all['total_size'], 4000)
        self.assertEqual(stats_all['videos'], 2)
        self.assertEqual(stats_all['images'], 1)
        self.assertEqual(stats_all['audios'], 1)
        self.assertEqual(stats_all['documents'], 1)

        # 4. 统计 chat_id = 1001
        stats_1001 = db.get_tg_media_stats(chat_id=1001)
        self.assertEqual(stats_1001['total_count'], 4)
        self.assertEqual(stats_1001['total_size'], 2000)
        self.assertEqual(stats_1001['videos'], 1)
        self.assertEqual(stats_1001['images'], 1)
        self.assertEqual(stats_1001['audios'], 1)
        self.assertEqual(stats_1001['documents'], 1)

        # 5. 统计 chat_id = 1002
        stats_1002 = db.get_tg_media_stats(chat_id=1002)
        self.assertEqual(stats_1002['total_count'], 1)
        self.assertEqual(stats_1002['total_size'], 2000)
        self.assertEqual(stats_1002['videos'], 1)
        self.assertEqual(stats_1002['images'], 0)

    def test_browse_tg_media_group_pushdown(self):
        """验证 browse_tg_media 在 media_group_id 下推 SQL 分页与排序的准确性"""
        group_id = "album_999"
        # 录入 5 个属于同一媒体组的元素
        from datetime import datetime, timezone
        dates = [
            datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 2, 10, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 3, 10, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 4, 10, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 5, 10, 0, 0, tzinfo=timezone.utc),
        ]
        files = [
            ("photo_c.jpg", "uid_c", 300),
            ("photo_a.jpg", "uid_a", 100),
            ("photo_e.jpg", "uid_e", 500),
            ("photo_b.jpg", "uid_b", 200),
            ("photo_d.jpg", "uid_d", 400),
        ]
        for i, (fn, uid, sz) in enumerate(files):
            msg, med = _make_mock_media(
                chat_id=2001,
                message_id=100 + i,
                file_name=fn,
                file_unique_id=uid,
                file_size=sz,
                mime_type="image/jpeg",
                media_group_id=group_id,
                msg_date=dates[i],
            )
            db.save_tg_media(msg, med)

        # 1. 默认按 message_date 倒序，分页 page=1, page_size=2
        res1 = db.browse_tg_media(page=1, page_size=2, media_group_id=group_id)
        self.assertEqual(res1['total'], 5)
        self.assertEqual(len(res1['items']), 2)
        self.assertEqual(res1['items'][0]['file_unique_id'], "uid_d")  # 2026-01-05
        self.assertEqual(res1['items'][1]['file_unique_id'], "uid_b")  # 2026-01-04
        self.assertEqual(res1['items'][0]['entry_type'], 'file')

        # 2. 第二页 page=2, page_size=2
        res2 = db.browse_tg_media(page=2, page_size=2, media_group_id=group_id)
        self.assertEqual(len(res2['items']), 2)
        self.assertEqual(res2['items'][0]['file_unique_id'], "uid_e")  # 2026-01-03
        self.assertEqual(res2['items'][1]['file_unique_id'], "uid_a")  # 2026-01-02

        # 3. 按 file_size 正序 (sort_desc=False)
        res_size = db.browse_tg_media(
            page=1,
            page_size=5,
            media_group_id=group_id,
            sort_by='file_size',
            sort_desc=False,
        )
        sizes = [item['file_size'] for item in res_size['items']]
        self.assertEqual(sizes, [100, 200, 300, 400, 500])

        # 4. 按 file_name 升序
        res_name = db.browse_tg_media(
            page=1,
            page_size=5,
            media_group_id=group_id,
            sort_by='file_name',
            sort_desc=False,
        )
        names = [item['file_name'] for item in res_name['items']]
        self.assertEqual(names, ["photo_a.jpg", "photo_b.jpg", "photo_c.jpg", "photo_d.jpg", "photo_e.jpg"])


if __name__ == '__main__':
    unittest.main()
