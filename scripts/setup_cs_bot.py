import sys
import os
import re
import asyncio
import logging
import secrets
from typing import Tuple, Optional

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyrogram_patch
from pyrogram import Client, enums
import db
from botfather_creator import create_single_bot, wait_for_botfather_reply

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("setup_cs_bot")

DEFAULT_API_BASE = os.environ.get("AI_CS_API_BASE", "https://api.openai.com/v1")
DEFAULT_API_KEY = os.environ.get("AI_CS_API_KEY", "")
DEFAULT_MODEL = os.environ.get("AI_CS_MODEL", "gpt-4o-mini")
TARGET_CHAT = "MistRelay"

async def disable_bot_privacy(client: Client, bot_username: str):
    """通过 BotFather 关闭群隐私模式以接收群内全量消息"""
    try:
        logger.info(f"正在尝试向 @BotFather 关闭 @{bot_username} 的群消息隐私限制...")
        await client.send_message("BotFather", "/cancel")
        await asyncio.sleep(0.5)
        sent = await client.send_message("BotFather", "/setprivacy")
        reply = await wait_for_botfather_reply(client, sent.id, timeout=8.0)
        
        # 发送目标 bot 用户名
        sent2 = await client.send_message("BotFather", f"@{bot_username.lstrip('@')}")
        reply2 = await wait_for_botfather_reply(client, sent2.id, timeout=8.0)
        
        reply2_text = (reply2.text or "").lower()
        if "disable" in reply2_text:
            sent3 = await client.send_message("BotFather", "Disable")
            reply3 = await wait_for_botfather_reply(client, sent3.id, timeout=8.0)
            logger.info(f"@BotFather 隐私设置结果: {reply3.text}")
        elif "current status is: disabled" in reply2_text:
            logger.info(f"@{bot_username} 隐私模式已经是 DISABLED")
        else:
            logger.info(f"隐私设置回复: {reply2.text}")
    except Exception as e:
        logger.warning(f"自动设置隐私模式出现非致命异常 (可手动设置或通过管理员身份自动绕过): {e}")

async def invite_bot_to_group(client: Client, bot_username: str, group_chat: str):
    """使用协议号将 Bot 邀请进目标交流群"""
    try:
        # 协议号先确保加入目标群
        try:
            chat = await client.join_chat(group_chat)
            logger.info(f"协议号已加入群组: {chat.title} ({chat.id})")
        except Exception as e:
            logger.info(f"协议号 join_chat 结果 (可能已在群内): {e}")
            chat = await client.get_chat(group_chat)

        # 尝试邀请客服 Bot 入群
        try:
            await client.add_chat_members(chat.id, [bot_username])
            logger.info(f"成功将 @{bot_username} 邀请加入群组 {chat.title}!")
            return True, chat.id, chat.title
        except Exception as e:
            logger.warning(f"邀请 Bot 入群时提示: {e} (若群设置了禁止普通成员拉人，可直接使用提权链接加入)")
            return False, chat.id, getattr(chat, 'title', group_chat)
    except Exception as e:
        logger.error(f"处理群组邀请出现异常: {e}")
        return False, None, group_chat

async def main():
    print("=" * 60)
    print("开始执行: MistRelay 专属客服 Bot 自动创建与拉群流程")
    print("=" * 60)

    # 1. 查找可用协议号
    accounts = db.list_protocol_accounts()
    active_acc = None
    for acc in accounts:
        if acc.get("status") == "active" and acc.get("session_data"):
            # 优先选择已经有完整 session 的账号
            active_acc = acc
            break

    if not active_acc:
        logger.error("未找到可用的 Telegram 协议号，请先在协议号管理中导入或激活协议号。")
        sys.exit(1)

    logger.info(f"选用协议号: ID={active_acc['id']}, Phone={active_acc['phone']}")

    # 2. 启动协议号客户端
    client = Client(
        name=f"setup_cs_runner_{active_acc['id']}",
        session_string=active_acc["session_data"],
        api_id=active_acc["api_id"],
        api_hash=active_acc["api_hash"],
        in_memory=True
    )

    await client.start()
    try:
        # 3. 检查是否已经配置过客服 Bot
        existing_token = db.get_config("AI_CS_BOT_TOKEN")
        existing_username = db.get_config("AI_CS_BOT_USERNAME")
        
        bot_username = None
        bot_token = None

        if existing_token and existing_username:
            logger.info(f"检测到系统已存在客服 Bot 配置: @{existing_username}")
            choice = os.environ.get("RECREATE_BOT", "0")
            if choice != "1":
                bot_username = existing_username
                bot_token = existing_token
                logger.info("复用现有客服 Bot 配置。若需强制重新铸造，请设置环境变量 RECREATE_BOT=1")

        if not bot_token:
            logger.info("正在与 @BotFather 交互铸造新客服 Bot...")
            bot_username, bot_token = await create_single_bot(
                client=client,
                display_name="MistRelay 智能客服",
                username_prefix="mistrelay_cs",
                max_cooldown_wait=60
            )
            logger.info(f"客服 Bot 铸造成功! 用户名: @{bot_username}, Token: {bot_token[:10]}******")

        # 4. 调整 Bot 隐私设置
        await disable_bot_privacy(client, bot_username)

        # 5. 邀请加入群组
        joined, chat_id, chat_title = await invite_bot_to_group(client, bot_username, TARGET_CHAT)

        # 6. 保存配置至数据库
        db.set_config("AI_CS_BOT_TOKEN", bot_token, value_type="string", category="ai_cs", description="AI 客服机器人 Token")
        db.set_config("AI_CS_BOT_USERNAME", bot_username, value_type="string", category="ai_cs", description="AI 客服机器人用户名")
        db.set_config("AI_CS_API_BASE", DEFAULT_API_BASE, value_type="string", category="ai_cs", description="AI 客服 LLM Base URL")
        db.set_config("AI_CS_API_KEY", DEFAULT_API_KEY, value_type="string", category="ai_cs", description="AI 客服 LLM API Key")
        db.set_config("AI_CS_MODEL", DEFAULT_MODEL, value_type="string", category="ai_cs", description="AI 客服使用的模型名称")
        db.set_config("AI_CS_TARGET_CHAT", TARGET_CHAT, value_type="string", category="ai_cs", description="AI 客服监听的目标群组用户名或ID")
        db.set_config("AI_CS_ENABLED", True, value_type="bool", category="ai_cs", description="是否启用 AI 客服功能")
        logger.info("客服 Bot 核心配置已成功写入数据库 config_settings 表。")

        # 7. 生成管理员一键提权链接
        admin_rights = "change_info+post_messages+edit_messages+delete_messages+restrict_members+invite_users+pin_messages+manage_topics+promote_members"
        admin_link = f"https://t.me/{bot_username}?startgroup=botstart&admin={admin_rights}"

        print("\n" + "=" * 60)
        print("🎉 MistRelay 专属客服 Bot 创建与配置完成！")
        print("=" * 60)
        print(f"🤖 机器人名称: MistRelay 智能客服")
        print(f"👤 机器人账号: @{bot_username}")
        print(f"🔑 机器人 Token: {bot_token}")
        print(f"💬 目标交流群: https://t.me/{TARGET_CHAT} (ID: {chat_id})")
        print(f"📥 群组加入状态: {'已成功由协议号拉入群' if joined else '待通过管理员链接一键加入'}")
        print("-" * 60)
        print("👑 【群主一键设为管理员链接】:")
        print(admin_link)
        print("说明：请群主 (Telegram ID: 5335111945) 点击上述链接，选择群组并确认授权，即可将 Bot 设为管理员。")
        print("=" * 60 + "\n")

    finally:
        await client.stop()

if __name__ == "__main__":
    asyncio.run(main())
