# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

"""
媒体处理模块
处理媒体组和单个媒体文件，保存到 TG 网盘并生成直链
支持无痕复制（Copy）与智能第三方引流清洗归属改写
"""

import re
import time
import logging
import asyncio
from collections import defaultdict
from urllib.parse import quote_plus
from pyrogram import filters, errors
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums.parse_mode import ParseMode

from configer import get_config_value
from WebStreamer.vars import Var
from WebStreamer.bot import StreamBot, logger
from WebStreamer.utils import get_hash, get_name
from WebStreamer.utils.rebrand_cleaner import clean_and_rebrand_caption, clean_drive_filename
from db import save_tg_media

# 媒体组缓存：用于收集同一媒体组的所有消息
media_group_cache = defaultdict(list)
media_group_tasks = {}
MAX_PENDING_MEDIA_GROUPS = 100
MAX_MEDIA_GROUP_ITEMS = 20


def is_allowed_user(message: Message) -> bool:
    """Authorize only immutable numeric Telegram user IDs, failing closed."""
    if not Var.ALLOWED_USERS or not getattr(message, "from_user", None):
        return False
    user_id = str(message.from_user.id)
    return user_id in Var.ALLOWED_USERS


async def process_media_group(messages: list, queue_reply_msg=None):
    """
    处理媒体组：一次性转发/无痕发布所有媒体文件到频道，保持消息完整性
    
    Args:
        messages: 媒体组消息列表
        queue_reply_msg: 排队通知消息（如果存在，将在处理完成后更新或删除）
    """
    if not messages:
        return
    
    first_msg = messages[0]
    
    # 保留排队通知消息，用于处理完成后更新。
    if queue_reply_msg and Var.SEND_STREAM_LINK:
        try:
            await queue_reply_msg.delete()
        except Exception as e:
            logger.debug(f"删除排队通知失败: {e}")
    
    # 权限检查
    if not is_allowed_user(first_msg):
        return
    
    # BIN_CHANNEL检查
    if not Var.BIN_CHANNEL:
        logger.warning(f"BIN_CHANNEL未配置，无法为 {first_msg.from_user.first_name} 生成直链")
        return
    
    try:
        rebrand_enabled = bool(get_config_value("FORWARD_REBRAND_ENABLED", True))
        clean_filenames = bool(get_config_value("FORWARD_CLEAN_FILENAMES", True))
        target_channel = get_config_value("FORWARD_TARGET_CHANNEL", "")
        signature = get_config_value("FORWARD_CHANNEL_SIGNATURE", "")
        custom_rules = get_config_value("FORWARD_CUSTOM_REPLACE_RULES", "")

        chat_id = messages[0].chat.id
        message_ids = [msg.id for msg in messages]
        forwarded_messages = []

        # 1. 尝试无痕复制入库（抹除“转发自”标识并应用配文清洗）
        if rebrand_enabled:
            try:
                captions = [
                    clean_and_rebrand_caption(
                        msg.caption,
                        target_channel=target_channel,
                        signature=signature,
                        custom_rules=custom_rules,
                    ) if (msg.caption or (i == 0 and signature)) else (msg.caption or "")
                    for i, msg in enumerate(messages)
                ]
                copied_msgs = await StreamBot.copy_media_group(
                    chat_id=Var.BIN_CHANNEL,
                    from_chat_id=chat_id,
                    message_id=messages[0].id,
                    captions=captions,
                )
                if isinstance(copied_msgs, list):
                    for i, log_msg in enumerate(copied_msgs):
                        if i < len(messages):
                            forwarded_messages.append((messages[i], log_msg))
                elif copied_msgs:
                    forwarded_messages.append((messages[0], copied_msgs))
            except Exception as copy_grp_err:
                logger.warning(f"copy_media_group 无痕发布失败: {copy_grp_err}，尝试逐条 copy_message")
                try:
                    for msg in messages:
                        c_caption = clean_and_rebrand_caption(
                            msg.caption,
                            target_channel=target_channel,
                            signature=signature,
                            custom_rules=custom_rules,
                        ) if msg.caption else msg.caption
                        c_msg = await StreamBot.copy_message(
                            chat_id=Var.BIN_CHANNEL,
                            from_chat_id=chat_id,
                            message_id=msg.id,
                            caption=c_caption,
                        )
                        forwarded_messages.append((msg, c_msg))
                except Exception as copy_each_err:
                    logger.warning(f"逐条 copy_message 也失败: {copy_each_err}，回退到 forward")
                    forwarded_messages = []

        # 2. 若未启用无痕洗白或复制异常，安全回退到原转发
        if not forwarded_messages:
            try:
                forwarded_msgs = await StreamBot.forward_messages(
                    chat_id=Var.BIN_CHANNEL,
                    from_chat_id=chat_id,
                    message_ids=message_ids
                )
                if isinstance(forwarded_msgs, list):
                    for i, log_msg in enumerate(forwarded_msgs):
                        if i < len(messages):
                            forwarded_messages.append((messages[i], log_msg))
                else:
                    forwarded_messages.append((messages[0], forwarded_msgs))
            except Exception as e:
                logger.error(f"转发媒体组失败: {e}", exc_info=True)
                for msg in messages:
                    try:
                        log_msg = await msg.forward(chat_id=Var.BIN_CHANNEL)
                        forwarded_messages.append((msg, log_msg))
                    except Exception as e2:
                        logger.error(f"转发单条消息失败: {e2}", exc_info=True)
        
        if not forwarded_messages:
            return
        
        # 为每个媒体文件生成直链，并把已保存到频道的消息写入 tg_media
        stream_links = []

        for original_msg, log_msg in forwarded_messages:
            try:
                raw_file_name = get_name(original_msg)
                cleaned_file_name = clean_drive_filename(
                    raw_file_name,
                    clean_enabled=clean_filenames,
                    custom_rules=custom_rules,
                ) if clean_filenames else raw_file_name

                raw_caption = getattr(original_msg, "caption", None)
                cleaned_caption = clean_and_rebrand_caption(
                    raw_caption,
                    target_channel=target_channel,
                    signature=signature,
                    custom_rules=custom_rules,
                ) if rebrand_enabled and raw_caption else getattr(log_msg, "caption", None)

                file_hash = get_hash(log_msg, Var.HASH_LENGTH)
                stream_link = f"{Var.URL}{log_msg.id}/{quote_plus(cleaned_file_name)}?hash={file_hash}"
                short_link = f"{Var.URL}{file_hash}{log_msg.id}"
                file_name = cleaned_file_name
                log_media = getattr(log_msg, log_msg.media.value, None) if getattr(log_msg, "media", None) else None
                file_unique_id = None

                if log_media:
                    try:
                        file_unique_id = save_tg_media(
                            log_msg,
                            log_media,
                            custom_file_name=cleaned_file_name if clean_filenames else None,
                            custom_caption=cleaned_caption if rebrand_enabled else None,
                        )
                        try:
                            from thumbnail_worker import get_thumbnail_worker
                            get_thumbnail_worker().enqueue(log_msg.id)
                        except Exception:
                            pass
                    except Exception as db_e:
                        logger.error(f"记录频道媒体到数据库失败: {db_e}", exc_info=True)

                link_entry = {
                    'name': file_name,
                    'full_link': stream_link,
                    'short_link': short_link,
                    'original_msg': original_msg,
                    'log_msg': log_msg,
                    'log_media': log_media,
                    'file_unique_id': file_unique_id,
                }
                stream_links.append(link_entry)
                logger.info(f"媒体已保存到TG网盘并生成直链： {stream_link} for {first_msg.from_user.first_name}")
                    
            except Exception as e:
                logger.error(f"生成直链失败: {e}", exc_info=True)
        
        # 构建回复消息
        if len(stream_links) == 1:
            link_info = stream_links[0]
            reply_text = (
                f"☁️ <b>已保存到 TG 网盘</b>\n\n"
                f"📁 <b>文件:</b> <code>{link_info['name']}</code>\n\n"
                f"🌐 <b>完整链接:</b>\n<code>{link_info['full_link']}</code>\n\n"
                f"🔗 <b>短链接:</b>\n<code>{link_info['short_link']}</code>"
            )
            main_link = link_info['full_link']
        else:
            saved_count = sum(1 for item in stream_links if item.get('file_unique_id'))
            reply_text = (
                f"☁️ <b>媒体组已保存到 TG 网盘</b>\n\n"
                f"📊 <b>统计信息:</b>\n"
                f"  • 总文件数: {len(stream_links)}\n"
                f"  • 已入库: {saved_count}\n"
            )
            reply_text += "\n📋 <b>文件列表:</b>\n\n"
            
            for i, link_info in enumerate(stream_links, 1):
                reply_text += (
                    f"☁️ <b>{i}. {link_info['name']}</b>\n"
                    f"   <code>{link_info['full_link']}</code>\n"
                    f"   <i>TG 网盘</i>\n\n"
                )
            main_link = stream_links[0]['full_link'] if stream_links else None
        
        task_gids = []
        
        # 回复用户（只回复第一条消息）- 如果启用了发送直链信息
        reply_msg = None
        if Var.SEND_STREAM_LINK:
            try:
                buttons = []
                if main_link:
                    buttons.append([InlineKeyboardButton("🔗 打开直链", url=main_link)])
                
                reply_msg = await first_msg.reply_text(
                    text=reply_text,
                    quote=True,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
                )
            except errors.ButtonUrlInvalid:
                reply_msg = await first_msg.reply_text(
                    text=reply_text,
                    quote=True,
                    parse_mode=ParseMode.HTML,
                )
        else:
            if queue_reply_msg:
                try:
                    processing_text = (
                        "✅ <b>已收到您的消息</b>\n\n"
                        "☁️ 媒体组已保存到 TG 网盘\n"
                        f"📊 共 {len(stream_links)} 个文件\n"
                        "✅ 处理完成"
                    )
                    await queue_reply_msg.edit_text(
                        text=processing_text,
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.debug(f"更新队列通知消息失败: {e}")
            
            logger.info(f"已处理媒体组（不发送直链信息）：共 {len(stream_links)} 个文件，已保存到TG网盘")
        
        return task_gids
    except Exception as e:
        logger.error(f"处理媒体组失败: {e}", exc_info=True)
        try:
            error_reply = (
                f'❌ <b>处理失败</b>\n\n'
                f'⚠️ 处理媒体组时出错，请稍后重试'
            )
            await first_msg.reply(error_reply, quote=True, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return []


async def process_single_media(m: Message, queue_reply_msg=None):
    """
    处理单个媒体文件
    
    Args:
        m: 消息对象
        queue_reply_msg: 排队通知消息（如果存在，将在处理完成后更新或删除）
    """
    if not Var.ENABLE_STREAM:
        return
    
    if queue_reply_msg and Var.SEND_STREAM_LINK:
        try:
            await queue_reply_msg.delete()
        except Exception as e:
            logger.debug(f"删除排队通知失败: {e}")
    
    # 权限检查
    if not is_allowed_user(m):
        permission_msg = (
            f'🚫 <b>权限不足</b>\n\n'
            f'⚠️ 你没有权限使用这个机器人'
        )
        return await m.reply(permission_msg, quote=True, parse_mode=ParseMode.HTML)
    
    # BIN_CHANNEL检查
    if not Var.BIN_CHANNEL:
        logger.warning(f"BIN_CHANNEL未配置，无法为 {m.from_user.first_name} 生成直链")
        return await m.reply("直链功能未配置，请在配置文件中设置 BIN_CHANNEL", quote=True)
    
    try:
        rebrand_enabled = bool(get_config_value("FORWARD_REBRAND_ENABLED", True))
        clean_filenames = bool(get_config_value("FORWARD_CLEAN_FILENAMES", True))
        target_channel = get_config_value("FORWARD_TARGET_CHANNEL", "")
        signature = get_config_value("FORWARD_CHANNEL_SIGNATURE", "")
        custom_rules = get_config_value("FORWARD_CUSTOM_REPLACE_RULES", "")

        raw_caption = getattr(m, "caption", None)
        cleaned_caption = clean_and_rebrand_caption(
            raw_caption,
            target_channel=target_channel,
            signature=signature,
            custom_rules=custom_rules,
        ) if rebrand_enabled else raw_caption

        raw_file_name = get_name(m)
        cleaned_file_name = clean_drive_filename(
            raw_file_name,
            clean_enabled=clean_filenames,
            custom_rules=custom_rules,
        ) if clean_filenames else raw_file_name

        log_msg = None
        if rebrand_enabled:
            try:
                log_msg = await StreamBot.copy_message(
                    chat_id=Var.BIN_CHANNEL,
                    from_chat_id=m.chat.id,
                    message_id=m.id,
                    caption=cleaned_caption,
                )
            except Exception as copy_err:
                logger.warning(f"copy_message 无痕发布失败: {copy_err}，回退到 forward")
                log_msg = await m.forward(chat_id=Var.BIN_CHANNEL)
        else:
            log_msg = await m.forward(chat_id=Var.BIN_CHANNEL)

        log_media = getattr(log_msg, log_msg.media.value, None) if getattr(log_msg, "media", None) else None
        saved_file_unique_id = None
        if log_media:
            try:
                saved_file_unique_id = save_tg_media(
                    log_msg,
                    log_media,
                    custom_file_name=cleaned_file_name if clean_filenames else None,
                    custom_caption=cleaned_caption if rebrand_enabled else None,
                )
                try:
                    from thumbnail_worker import get_thumbnail_worker
                    get_thumbnail_worker().enqueue(log_msg.id)
                except Exception:
                    pass
            except Exception as db_e:
                logger.error(f"记录频道媒体到数据库失败: {db_e}", exc_info=True)

        file_hash = get_hash(log_msg, Var.HASH_LENGTH)
        stream_link = f"{Var.URL}{log_msg.id}/{quote_plus(cleaned_file_name)}?hash={file_hash}"
        short_link = f"{Var.URL}{file_hash}{log_msg.id}"
        
        logger.info(f"媒体已保存到TG网盘并生成直链： {stream_link} for {m.from_user.first_name}")
        
        # 返回直链给用户（如果启用了发送直链信息）
        if Var.SEND_STREAM_LINK:
            reply_text = (
                f"☁️ <b>已保存到 TG 网盘</b>\n\n"
                f"📁 <b>文件:</b> <code>{cleaned_file_name}</code>\n\n"
                f"🌐 <b>完整链接:</b>\n<code>{stream_link}</code>\n\n"
                f"🔗 <b>短链接:</b>\n<code>{short_link}</code>"
            )
            
            try:
                await m.reply_text(
                    text=reply_text,
                    quote=True,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🔗 打开直链", url=stream_link)]]
                    ),
                )
            except errors.ButtonUrlInvalid:
                await m.reply_text(
                    text=reply_text,
                    quote=True,
                    parse_mode=ParseMode.HTML,
                )
        else:
            if queue_reply_msg:
                try:
                    processing_text = (
                        "✅ <b>已收到您的消息</b>\n\n"
                        "☁️ 文件已保存到 TG 网盘\n"
                        "✅ 处理完成"
                    )
                    await queue_reply_msg.edit_text(
                        text=processing_text,
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.debug(f"更新队列通知消息失败: {e}")
            
            logger.info(f"已处理文件（不发送直链信息）：{cleaned_file_name}，已保存到TG网盘")
        
        return []
    except Exception as e:
        logger.error(f"生成直链失败: {e}", exc_info=True)
        await m.reply("生成直链时出错，请稍后重试", quote=True)
        return []


@StreamBot.on_message(
    filters.private
    & (
        filters.document
        | filters.video
        | filters.audio
        | filters.animation
        | filters.voice
        | filters.video_note
        | filters.photo
        | filters.sticker
    ),
    group=4,
)
async def media_receive_handler(_, m: Message):
    """
    处理Telegram媒体文件，生成直链（作为下载的前置功能）
    支持单个媒体文件和媒体组（保持消息完整性）
    """
    if not Var.ENABLE_STREAM:
        return

    # Authorize before touching group caches, queue state, or notification tasks.
    if not is_allowed_user(m):
        logger.warning(
            "拒绝未授权 Telegram 媒体入队 user_id=%s",
            getattr(getattr(m, "from_user", None), "id", None),
        )
        return

    from .queue_manager import enqueue_message_task
    
    # 检查是否是媒体组
    if m.media_group_id:
        group_id = f"{m.chat.id}_{m.media_group_id}"
        if group_id not in media_group_cache and len(media_group_cache) >= MAX_PENDING_MEDIA_GROUPS:
            await m.reply("消息队列繁忙，请稍后重试", quote=True)
            return
        if len(media_group_cache[group_id]) >= MAX_MEDIA_GROUP_ITEMS:
            logger.warning("拒绝超大 Telegram 媒体组 group_id=%s", group_id)
            return
        media_group_cache[group_id].append(m)
        
        if group_id in media_group_tasks:
            media_group_tasks[group_id].cancel()
        
        async def delayed_process():
            await asyncio.sleep(0.5)
            if group_id in media_group_cache:
                messages = media_group_cache.pop(group_id)
                messages.sort(key=lambda x: x.id)
                if group_id in media_group_tasks:
                    del media_group_tasks[group_id]
                if not enqueue_message_task(process_media_group, messages):
                    await messages[0].reply("消息队列已满，请稍后重试", quote=True)
        
        task = asyncio.create_task(delayed_process())
        media_group_tasks[group_id] = task
    else:
        if not enqueue_message_task(process_single_media, m):
            await m.reply("消息队列已满，请稍后重试", quote=True)


@StreamBot.on_message(
    filters.private
    & filters.text
    & ~filters.command(["start", "help", "menu", "status"]),
    group=5,
)
async def channel_link_receive_handler(_, m: Message):
    """
    处理用户私聊发送的私密/受限频道帖子链接或连号区间，调度采集流水线并实时编辑汇报进度
    """
    if not Var.ENABLE_STREAM:
        return

    text = (m.text or "").strip()
    if not text or not re.search(r"(?:https?://)?(?:t\.me|telegram\.me)/", text, re.IGNORECASE):
        return

    if not is_allowed_user(m):
        logger.warning(
            "拒绝未授权用户发送频道采集链接 user_id=%s",
            getattr(getattr(m, "from_user", None), "id", None),
        )
        return

    if not Var.BIN_CHANNEL:
        await m.reply("❌ BIN_CHANNEL 未配置，无法保存媒体到 TG 网盘", quote=True)
        return

    from private_channel_harvester import parse_telegram_post_links, HarvesterTaskManager

    targets, _ = parse_telegram_post_links(text)
    if not targets:
        return

    manager = HarvesterTaskManager.get_instance()
    status = manager.get_status()
    if status.get("status") == "running":
        await m.reply(
            "⚠️ 当前已有频道采集任务正在后台执行中，请稍候再试或在 Web 控制端查看实时进度。",
            quote=True,
        )
        return

    total_msgs = sum(len(t.msg_ids) for t in targets)
    status_msg = await m.reply_text(
        f"📡 <b>收到频道采集请求</b>\n\n"
        f"📊 目标: {len(targets)} 个频道，共 {total_msgs} 条消息\n"
        f"🔍 正在建立连接并准备转存...",
        quote=True,
        parse_mode=ParseMode.HTML,
    )

    last_edit_time = 0.0

    async def tg_progress_callback(curr_status: dict):
        nonlocal last_edit_time
        now = time.time()
        st = curr_status.get("status")
        if now - last_edit_time < 2.0 and st not in ("completed", "failed", "cancelled"):
            return
        last_edit_time = now

        if st == "running":
            mode_desc = "⚡ 秒传" if curr_status.get("current_mode") == "fast_copy" else "🔓 受限重传"
            speed_str = f" ({curr_status['speed_text']})" if curr_status.get("speed_text") else ""
            txt = (
                f"🔄 <b>私密/受限频道采集进行中...</b>\n\n"
                f"📊 进度: {curr_status.get('current_index', 0)}/{curr_status.get('total_messages', 0)}\n"
                f"🚀 模式: {mode_desc}{speed_str}\n"
                f"📁 当前: <code>{curr_status.get('current_file', '准备中...')}</code>\n"
                f"✅ 成功: {curr_status.get('success_count', 0)}  "
                f"⚠️ 跳过: {curr_status.get('skipped_count', 0)}  "
                f"❌ 失败: {curr_status.get('failed_count', 0)}"
            )
            try:
                await status_msg.edit_text(txt, parse_mode=ParseMode.HTML)
            except Exception:
                pass
        elif st == "completed":
            results = curr_status.get("results", [])
            txt = (
                f"🎉 <b>频道采集完成！</b>\n\n"
                f"📊 <b>统计信息:</b>\n"
                f"  • 总计分析: {curr_status.get('total_messages', 0)} 条\n"
                f"  • 成功入库: {curr_status.get('success_count', 0)} 个文件\n"
                f"  • 跳过/失败: {curr_status.get('skipped_count', 0) + curr_status.get('failed_count', 0)}\n"
            )
            if Var.SEND_STREAM_LINK and results:
                txt += "\n📋 <b>直链列表 (部分展示):</b>\n\n"
                for i, item in enumerate(results[:5], 1):
                    txt += f"{i}. <code>{item.get('name')}</code>\n🔗 {item.get('full_link')}\n\n"
                if len(results) > 5:
                    txt += f"<i>... 以及另外 {len(results) - 5} 个文件已全部入库 TG 网盘</i>"
            try:
                await status_msg.edit_text(txt, parse_mode=ParseMode.HTML)
            except Exception:
                pass
        elif st == "cancelled":
            try:
                await status_msg.edit_text("🛑 采集任务已被中止", parse_mode=ParseMode.HTML)
            except Exception:
                pass
        elif st == "failed":
            err = curr_status.get("error") or "未知错误"
            try:
                await status_msg.edit_text(f"❌ 采集失败: <code>{err}</code>", parse_mode=ParseMode.HTML)
            except Exception:
                pass

    res = await manager.start_task(
        links_text=text,
        rebrand_enabled=True,
        progress_callback=tg_progress_callback,
    )
    if not res.get("success"):
        try:
            await status_msg.edit_text(
                f"❌ 启动采集失败: {res.get('error')}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
