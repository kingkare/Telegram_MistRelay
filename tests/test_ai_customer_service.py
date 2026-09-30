import os
import tempfile
import db
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
from aiohttp import web
import ai_customer_service

class TestAICustomerService(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self._tmp.name
        db.init_db()
        self.bot = ai_customer_service.AICustomerServiceBot()

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        if hasattr(self, "_tmp") and os.path.exists(self._tmp.name):
            try:
                os.remove(self._tmp.name)
            except OSError:
                pass

    def test_split_text(self):
        short_text = "Hello world"
        chunks = self.bot._split_text(short_text, max_len=50)
        self.assertEqual(chunks, ["Hello world"])

        lines = [f"Line {i} content text" for i in range(20)]
        long_text = "\n".join(lines)
        chunks = self.bot._split_text(long_text, max_len=60)
        self.assertTrue(len(chunks) > 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 60)

    def test_history_sliding_window(self):
        chat_id = 999
        for i in range(25):
            self.bot._append_history(chat_id, "user", f"query {i}")
            self.bot._append_history(chat_id, "assistant", f"answer {i}")

        hist = self.bot._get_history(chat_id)
        self.assertLessEqual(len(hist), 20)
        self.assertEqual(hist[-1]["content"], "answer 24")

    def test_clear_history(self):
        self.bot._append_history(111, "user", "hi")
        self.bot._append_history(222, "user", "hello")
        self.assertEqual(len(self.bot._history), 2)
        self.bot.clear_history()
        self.assertEqual(len(self.bot._history), 0)

    def test_group_message_trigger_mention(self):
        bot_uname = "mistrelay_cs_3153b7_bot"
        bot_uid = 8961962822

        # 1. 普通聊天，没有 @ 也没有引用回复 -> 应完全静音忽略
        triggered, query = ai_customer_service.check_group_message_trigger(
            raw_text="大家好，今天推流速度怎么样？",
            bot_username=bot_uname,
            bot_user_id=bot_uid,
            mode="mention_or_reply"
        )
        self.assertFalse(triggered)

        # 2. @ 机器人并提问 -> 应当触发，并清洗掉 @ 标签
        triggered, query = ai_customer_service.check_group_message_trigger(
            raw_text=f"@{bot_uname} 请问怎么生成视频直链？",
            bot_username=bot_uname,
            bot_user_id=bot_uid,
            mode="mention_or_reply"
        )
        self.assertTrue(triggered)
        self.assertEqual(query, "请问怎么生成视频直链？")

        # 3. 回复机器人的消息 -> 应当触发
        triggered, query = ai_customer_service.check_group_message_trigger(
            raw_text="那如果卡顿怎么办？",
            bot_username=bot_uname,
            bot_user_id=bot_uid,
            reply_to_user_id=bot_uid,
            mode="mention_or_reply"
        )
        self.assertTrue(triggered)
        self.assertEqual(query, "那如果卡顿怎么办？")

        # 4. 回复其他普通群员的消息（非Bot）且未 @Bot -> 应完全静音
        triggered, query = ai_customer_service.check_group_message_trigger(
            raw_text="我也觉得不错",
            bot_username=bot_uname,
            bot_user_id=bot_uid,
            reply_to_user_id=12345678,
            mode="mention_or_reply"
        )
        self.assertFalse(triggered)

    def test_call_llm_mock(self):
        async def run_test():
            bot = ai_customer_service.AICustomerServiceBot()
            mock_session = MagicMock()
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={
                "choices": [{
                    "message": {"content": "这是 MistRelay 智能客服测试回复"}
                }]
            })

            mock_post_cm = MagicMock()
            mock_post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_post_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.post.return_value = mock_post_cm
            mock_session.closed = False
            bot._http_session = mock_session

            res = await bot._call_llm(12345, "测试提问")
            self.assertEqual(res, "这是 MistRelay 智能客服测试回复")

            hist = bot._get_history(12345)
            self.assertEqual(len(hist), 2)
            self.assertEqual(hist[0]["role"], "user")
            self.assertEqual(hist[1]["role"], "assistant")

        asyncio.run(run_test())

    def test_call_llm_direct_mock(self):
        async def run_test():
            bot = ai_customer_service.AICustomerServiceBot()
            mock_session = MagicMock()
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={
                "choices": [{
                    "message": {"content": "沙箱测试直接回复成功"}
                }]
            })

            mock_post_cm = MagicMock()
            mock_post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_post_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.post.return_value = mock_post_cm
            mock_session.closed = False
            bot._http_session = mock_session

            ok, reply, latency = await bot.call_llm_direct("测试沙箱提问")
            self.assertTrue(ok)
            self.assertEqual(reply, "沙箱测试直接回复成功")
            self.assertGreaterEqual(latency, 0)

        asyncio.run(run_test())

    def test_get_status_overview(self):
        async def run_test():
            bot = ai_customer_service.AICustomerServiceBot()
            overview = await bot.get_status_overview()
            self.assertIn("running", overview)
            self.assertIn("config", overview)
            self.assertIn("target_chat", overview)
            self.assertIn("stats", overview)
            self.assertIn("admin_link", overview)

        asyncio.run(run_test())


    def test_route_handlers_unauthorized(self):
        async def run_test():
            from WebStreamer.server.stream_routes import (
                telegram_customer_service_status_handler,
                telegram_customer_service_config_handler,
                telegram_customer_service_actions_handler,
                telegram_customer_service_test_chat_handler,
                telegram_customer_service_auto_mint_handler,
            )
            req_unauth = type('Req', (), {'get': lambda self, k: None})()
            for handler in [
                telegram_customer_service_status_handler,
                telegram_customer_service_config_handler,
                telegram_customer_service_actions_handler,
                telegram_customer_service_test_chat_handler,
                telegram_customer_service_auto_mint_handler,
            ]:
                resp = await handler(req_unauth)
                self.assertEqual(resp.status, 403)

        asyncio.run(run_test())

    def test_route_handlers_admin_status_and_actions(self):
        async def run_test():
            from WebStreamer.server.stream_routes import (
                telegram_customer_service_status_handler,
                telegram_customer_service_config_handler,
                telegram_customer_service_actions_handler,
            )
            admin_user = {'uid': 1, 'role': 'admin', 'username': 'admin'}
            req_admin = type('Req', (), {'get': lambda self, k: admin_user if k == 'user' else None})()
            resp = await telegram_customer_service_status_handler(req_admin)
            self.assertEqual(resp.status, 200)

            async def json_body(self):
                return {'private_enabled': False, 'temperature': 0.7}
            req_cfg = type('Req', (), {
                'get': lambda self, k: admin_user if k == 'user' else None,
                'json': json_body
            })()
            resp_cfg = await telegram_customer_service_config_handler(req_cfg)
            self.assertEqual(resp_cfg.status, 200)

            async def json_act(self):
                return {'action': 'clear_history'}
            req_act = type('Req', (), {
                'get': lambda self, k: admin_user if k == 'user' else None,
                'json': json_act
            })()
            resp_act = await telegram_customer_service_actions_handler(req_act)
            self.assertEqual(resp_act.status, 200)

        asyncio.run(run_test())



    def test_system_knowledge_context(self):
        ctx = ai_customer_service.get_system_knowledge_context()
        self.assertIn('official_website', ctx)
        self.assertIn('main_stream_bot', ctx)
        self.assertIn('cs_bot', ctx)
        self.assertIn('official_group', ctx)
        self.assertIn('official_channel', ctx)
        self.assertIn('admin_contact', ctx)
        self.assertTrue(ctx['official_website'].startswith('http'))
        self.assertTrue(ctx['main_stream_bot'].startswith('@'))

    def test_resolve_system_prompt_dynamic_replacement(self):
        ctx = ai_customer_service.get_system_knowledge_context()
        raw = '访问官网 {official_website}，或者联系 {main_stream_bot}。'
        resolved = ai_customer_service.resolve_system_prompt(raw)
        self.assertIn(ctx['official_website'], resolved)
        self.assertIn(ctx['main_stream_bot'], resolved)
        self.assertNotIn('{official_website}', resolved)

    def test_resolve_system_prompt_anchor_injection(self):
        ctx = ai_customer_service.get_system_knowledge_context()
        custom = '你是一个客服助手，仅此而已。'
        resolved = ai_customer_service.resolve_system_prompt(custom)
        self.assertIn('你是一个客服助手，仅此而已。', resolved)
        self.assertIn(ctx['official_website'], resolved)
        self.assertIn(ctx['main_stream_bot'], resolved)

    def test_convert_markdown_to_telegram_html(self):
        sample = (
            "### **功能概览**\n"
            "欢迎使用 MistRelay 服务！\n\n"
            "---"
            "\n"
            "- 支持流媒体分流\n"
            "* 极速直链下载\n"
            "1. 发送文件给机器人\n"
            "2. 获取专属播放链接\n\n"
            "> 注意：请保管好密钥\n\n"
            "使用指令 `docker compose up -d` 启动\n\n"
            "```bash\ncurl -I https://mistrelay.jiuyue520.com\n```\n\n"
            "访问 [官方主页](https://mistrelay.jiuyue520.com) 了解详情"
        )
        out = ai_customer_service.convert_markdown_to_telegram_html(sample)
        self.assertIn("📌 <b>功能概览</b>", out)
        self.assertIn("┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄", out)
        self.assertIn("▫️ 支持流媒体分流", out)
        self.assertIn("▫️ 极速直链下载", out)
        self.assertIn("<b>1.</b> 发送文件给机器人", out)
        self.assertIn("<b>2.</b> 获取专属播放链接", out)
        self.assertIn("<blockquote>注意：请保管好密钥</blockquote>", out)
        self.assertIn("<code>docker compose up -d</code>", out)
        self.assertIn("<pre><code>curl -I https://mistrelay.jiuyue520.com</code></pre>", out)
        self.assertIn('<a href="https://mistrelay.jiuyue520.com">官方主页</a>', out)
        # 确保无残留占位符或未处理的 markdown 乱码
        self.assertNotIn("§§", out)
        self.assertNotIn("INLINE_CODE", out)
        self.assertNotIn("CODE_BLOCK", out)

    def test_build_cs_reply_markup(self):
        ctx = {
            "official_website": "https://mistrelay.jiuyue520.com",
            "main_stream_bot": "@jiuyuetanzhen_bot",
            "official_group": "https://t.me/MistRelay",
            "official_channel": "https://t.me/jiuyue1314520",
            "admin_contact": "@baisi_luoli"
        }
        markup = ai_customer_service.build_cs_reply_markup(ctx)
        self.assertEqual(len(markup.inline_keyboard), 3)
        row0 = markup.inline_keyboard[0]
        self.assertEqual(row0[0].text, "🌐 访问官网")
        self.assertEqual(row0[0].url, "https://mistrelay.jiuyue520.com")
        self.assertEqual(row0[1].text, "⚡ 直链提取Bot")
        self.assertEqual(row0[1].url, "https://t.me/jiuyuetanzhen_bot")

        row1 = markup.inline_keyboard[1]
        self.assertEqual(row1[0].text, "💬 官方交流群")
        self.assertEqual(row1[0].url, "https://t.me/MistRelay")
        self.assertEqual(row1[1].text, "📢 官方更新频道")
        self.assertEqual(row1[1].url, "https://t.me/jiuyuetanzhen_bot" if "jiuyue1314520" not in row1[1].url else "https://t.me/jiuyue1314520")

        row2 = markup.inline_keyboard[2]
        self.assertEqual(row2[0].text, "👨‍💻 联系管理员")
        self.assertEqual(row2[0].url, "https://t.me/baisi_luoli")

    def test_format_telegram_cs_reply(self):
        raw = "这里是普通回答文本。\n- 功能A\n- 功能B"
        text, markup = ai_customer_service.format_telegram_cs_reply(raw)
        self.assertTrue(text.startswith("🌸 <b>MistRelay AI 智能解答</b>"))
        self.assertTrue(text.endswith("💡 <i>MistRelay 专属 AI 客服 · 长按引用或 @机器人 可继续追问</i>"))
        self.assertIn("▫️ 功能A", text)
        self.assertIn("▫️ 功能B", text)
        self.assertIsNotNone(markup)
        self.assertGreaterEqual(len(markup.inline_keyboard), 2)



class TestAICustomerServiceRuntimeAndSecurity(unittest.TestCase):
    def setUp(self):
        # 1. 严格使用独立临时 SQLite 数据库沙箱，遵循 AGENTS.md 规范
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self._tmp.name
        db.init_db()

    def tearDown(self):
        # 2. 严格恢复 DB_PATH 并清理临时数据库
        db.DB_PATH = self.orig_db_path
        if hasattr(self, "_tmp") and os.path.exists(self._tmp.name):
            try:
                os.remove(self._tmp.name)
            except OSError:
                pass

    def test_desensitized_runtime_status(self):
        # 创建边缘节点（含真实公网 IP 与敏感鉴权信息）
        node1 = db.create_edge_node(tenant_id=1, node_name="node-tokyo-01", ip="203.0.113.195")
        db.update_edge_node(node1["id"], status="active")
        node2 = db.create_edge_node(tenant_id=1, node_name="node-frankfurt-02", ip="198.51.100.22")
        db.update_edge_node(node2["id"], status="offline")

        st = ai_customer_service.get_desensitized_runtime_status(force_refresh=True)

        # 验证宏观聚合指标准确性
        self.assertEqual(st["edge_nodes"]["total"], 2)
        self.assertEqual(st["edge_nodes"]["online"], 1)
        self.assertEqual(st["edge_nodes"]["health_rate_pct"], 50.0)
        self.assertEqual(st["overall_status"], "健康在线")
        self.assertIn("streaming_engine", st)
        self.assertIn("aria2_engine", st)
        self.assertIn("specs", st)

        # 严格安全审计：断言脱敏数据中绝对不含任何 IP、Secret 或底层服务器标识
        st_repr = str(st)
        self.assertNotIn("203.0.113.195", st_repr)
        self.assertNotIn("198.51.100.22", st_repr)
        self.assertNotIn("node-tokyo-01", st_repr)
        self.assertNotIn("ssh_password", st_repr)
        self.assertNotIn("auth_secret", st_repr)

        # 格式化文本审计
        prompt_text = ai_customer_service.format_runtime_status_for_prompt(st)
        self.assertNotIn("203.0.113.195", prompt_text)
        self.assertIn("1/2", prompt_text)
        self.assertIn("总体服务状态", prompt_text)

    def test_outbound_redaction_guardrail(self):
        # 1. 模拟拦截 Telegram Bot Token
        leak_token = "当前服务使用的机器人 Token 是 1234567890:ABCdefGhIjkLmNoPqRsTuVwXyZ123456789 请妥善保管"
        safe1 = ai_customer_service.sanitize_outbound_response(leak_token)
        self.assertNotIn("1234567890:ABCdefGhIjkLmNoPqRsTuVwXyZ123456789", safe1)
        self.assertIn("[SECURED_TOKEN]", safe1)

        # 2. 模拟拦截公网 IPv4
        leak_ip = "后端节点 IP 是 23.94.9.54，端口为 8090"
        safe2 = ai_customer_service.sanitize_outbound_response(leak_ip)
        self.assertNotIn("23.94.9.54", safe2)
        self.assertIn("[SECURED_IP]", safe2)

        # 3. 保护合法 127.0.0.1 与版本号
        normal = "本地测试地址为 127.0.0.1:8080，当前系统版本为 3.8.1"
        safe3 = ai_customer_service.sanitize_outbound_response(normal)
        self.assertIn("127.0.0.1", safe3)
        self.assertIn("3.8.1", safe3)

        # 4. 私钥拦截
        leak_key = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0fakekey...==\n-----END RSA PRIVATE KEY-----"
        safe4 = ai_customer_service.sanitize_outbound_response(leak_key)
        self.assertIn("[SECURED_KEY]", safe4)

    def test_system_prompt_knowledge_injection(self):
        ctx = ai_customer_service.get_system_knowledge_context()
        self.assertIn("runtime_status_summary", ctx)
        self.assertIn("总体服务状态", ctx["runtime_status_summary"])

        resolved = ai_customer_service.resolve_system_prompt()
        self.assertIn("【MistRelay 系统实时服务状态（安全只读指标）】", resolved)
        self.assertIn("PotPlayer", resolved)
        self.assertIn("VLC", resolved)
        self.assertIn("Infuse", resolved)
        self.assertIn("IINA", resolved)
        self.assertIn("Prompt Injection", resolved)

    def test_format_telegram_cs_reply_sanitization(self):
        raw = "请记录密钥 9876543210:AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQq12345 以及后端 IP 45.76.12.34"
        text, markup = ai_customer_service.format_telegram_cs_reply(raw)
        self.assertNotIn("9876543210:AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQq12345", text)
        self.assertNotIn("45.76.12.34", text)
        self.assertIn("[SECURED_TOKEN]", text)
        self.assertIn("[SECURED_IP]", text)


if __name__ == '__main__':
    unittest.main()
