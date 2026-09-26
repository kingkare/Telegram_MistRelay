# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

"""
媒体处理模块
处理媒体组和单个媒体文件，保存到 TG 网盘并生成直链
"""

import logging
import asyncio
from collections import defaultdict
from urllib.parse import quote_plus
from pyrogram import filters, errors
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums.parse_mode import ParseMode

from WebStreamer.vars import Var
from WebStreamer.bot import StreamBot, logger
from WebStreamer.utils import get_hash, get_name
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
    处理媒体组：一次性转发所有媒体文件到频道，保持消息完整性
    
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
        # 一次性转发整个媒体组到频道（保持消息完整性）
        # 使用 forward_messages 一次性转发所有消息，保持媒体组完整性
        try:
            # 获取所有消息的 ID
            message_ids = [msg.id for msg in messages]
            chat_id = messages[0].chat.id
            
            # 一次性转发整个媒体组
            forwarded_msgs = await StreamBot.forward_messages(
                chat_id=Var.BIN_CHANNEL,
                from_chat_id=chat_id,
                message_ids=message_ids
            )
            
            # 构建 (原始消息, 转发消息) 的配对列表
            forwarded_messages = []
            if isinstance(forwarded_msgs, list):
                # 如果返回的是列表（多条消息）
                for i, log_msg in enumerate(forwarded_msgs):
                    if i < len(messages):
                        forwarded_messages.append((messages[i], log_msg))
            else:
                # 如果返回的是单个消息对象（理论上不应该发生）
                forwarded_messages.append((messages[0], forwarded_msgs))
                
        except Exception as e:
            logger.error(f"转发媒体组失败: {e}", exc_info=True)
            # 如果一次性转发失败，回退到逐条转发
            forwarded_messages = []
            for msg in messages:
                try:
                    log_msg = await msg.forward(chat_id=Var.BIN_CHANNEL)
                    forwarded_messages.append((msg, log_msg))
                except Exception as e2:
                    logger.error(f"转发单条消息失败: {e2}", exc_info=True)
        
        if not forwarded_messages:
            return
        
        # 为每个媒体文件生成直链，并把已转发到频道的消息写入 tg_media
        stream_links = []

        for original_msg, log_msg in forwarded_messages:
            try:
                file_hash = get_hash(log_msg, Var.HASH_LENGTH)
                stream_link = f"{Var.URL}{log_msg.id}/{quote_plus(get_name(original_msg))}?hash={file_hash}"
                short_link = f"{Var.URL}{file_hash}{log_msg.id}"
                file_name = get_name(original_msg)
                log_media = getattr(log_msg, log_msg.media.value, None) if getattr(log_msg, "media", None) else None
                file_unique_id = None

                if log_media:
                    try:
                        file_unique_id = save_tg_media(log_msg, log_media)
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
            # 单个文件
            link_info = stream_links[0]
            reply_text = (
                f"☁️ <b>已保存到 TG 网盘</b>\n\n"
                f"📁 <b>文件:</b> <code>{link_info['name']}</code>\n\n"
                f"🌐 <b>完整链接:</b>\n<code>{link_info['full_link']}</code>\n\n"
                f"🔗 <b>短链接:</b>\n<code>{link_info['short_link']}</code>"
            )
            main_link = link_info['full_link']
        else:
            # 多个文件（媒体组）
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
            # 如果不发送直链信息，更新队列通知消息为处理中状态
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
            
            # 记录日志
            logger.info(f"已处理媒体组（不发送直链信息）：共 {len(stream_links)} 个文件，已保存到TG网盘")
        
        # TG 网盘媒体不再创建 aria2 下载任务。
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
        return []  # 返回空列表


async def process_single_media(m: Message, queue_reply_msg=None):
    """
    处理单个媒体文件
    
    Args:
        m: 消息对象
        queue_reply_msg: 排队通知消息（如果存在，将在处理完成后更新或删除）
    """
    if not Var.ENABLE_STREAM:
        return
    
    # 如果有排队通知，且启用了发送直链信息，则删除它（因为我们要发送实际的处理结果）
    # 如果没有启用发送直链信息，保留队列通知消息，以便后续更新为完成状态
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
        # 转发到日志频道并生成直链
        log_msg = await m.forward(chat_id=Var.BIN_CHANNEL)
        log_media = getattr(log_msg, log_msg.media.value, None) if getattr(log_msg, "media", None) else None
        saved_file_unique_id = None
        if log_media:
            try:
                saved_file_unique_id = save_tg_media(log_msg, log_media)
                try:
                    from thumbnail_worker import get_thumbnail_worker
                    get_thumbnail_worker().enqueue(log_msg.id)
                except Exception:
                    pass
            except Exception as db_e:
                logger.error(f"记录频道媒体到数据库失败: {db_e}", exc_info=True)
        file_hash = get_hash(log_msg, Var.HASH_LENGTH)
        stream_link = f"{Var.URL}{log_msg.id}/{quote_plus(get_name(m))}?hash={file_hash}"
        short_link = f"{Var.URL}{file_hash}{log_msg.id}"
        
        logger.info(f"媒体已保存到TG网盘并生成直链： {stream_link} for {m.from_user.first_name}")
        
        # 返回直链给用户（如果启用了发送直链信息）
        if Var.SEND_STREAM_LINK:
            file_name = ""
            if m.document:
                file_name = m.document.file_name or "未知文件"
            elif m.video:
                file_name = m.video.file_name or "视频文件"
            elif m.audio:
                file_name = m.audio.file_name or "音频文件"
            elif m.photo:
                file_name = "图片文件"
            elif m.animation:
                file_name = m.animation.file_name or "动画文件"
            else:
                file_name = "媒体文件"
            
            reply_text = (
                f"☁️ <b>已保存到 TG 网盘</b>\n\n"
                f"📁 <b>文件:</b> <code>{file_name}</code>\n\n"
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
            # 如果不发送直链信息，更新队列通知消息为处理中状态
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
            
            logger.info(f"已处理文件（不发送直链信息）：{get_name(m)}，已保存到TG网盘")
        
        # TG 网盘媒体不再创建 aria2 下载任务。
        return []
    except Exception as e:
        logger.error(f"生成直链失败: {e}", exc_info=True)
        await m.reply("生成直链时出错，请稍后重试", quote=True)
        return []  # 返回空列表


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

    # 延迟导入避免循环依赖
    from .queue_manager import enqueue_message_task
    
    # 检查是否是媒体组
    if m.media_group_id:
        # 媒体组：收集所有消息，延迟处理
        group_id = f"{m.chat.id}_{m.media_group_id}"
        if group_id not in media_group_cache and len(media_group_cache) >= MAX_PENDING_MEDIA_GROUPS:
            await m.reply("消息队列繁忙，请稍后重试", quote=True)
            return
        if len(media_group_cache[group_id]) >= MAX_MEDIA_GROUP_ITEMS:
            logger.warning("拒绝超大 Telegram 媒体组 group_id=%s", group_id)
            return
        media_group_cache[group_id].append(m)
        
        # 取消之前的任务（如果有）
        if group_id in media_group_tasks:
            media_group_tasks[group_id].cancel()
        
        # 创建新任务：等待500ms后处理（给其他消息时间到达）
        async def delayed_process():
            await asyncio.sleep(0.5)  # 等待500ms
            if group_id in media_group_cache:
                messages = media_group_cache.pop(group_id)
                # 按照消息 ID 排序，确保顺序正确
                messages.sort(key=lambda x: x.id)
                if group_id in media_group_tasks:
                    del media_group_tasks[group_id]
                # 将媒体组处理任务加入队列，而不是直接执行
                # 注意：排队通知会在enqueue_message_task中自动发送
                if not enqueue_message_task(process_media_group, messages):
                    await messages[0].reply("消息队列已满，请稍后重试", quote=True)
        
        task = asyncio.create_task(delayed_process())
        media_group_tasks[group_id] = task
    else:
        # 单个媒体文件：加入队列处理，而不是立即处理
        if not enqueue_message_task(process_single_media, m):
            await m.reply("消息队列已满，请稍后重试", quote=True)
