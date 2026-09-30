import pyrogram_patch
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
from pyrogram import Client, filters, errors
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
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


async def ensure_peer_cached(client, chat_id: int | str):
    """确保 Pyrogram 客户端已解析目标频道的 access_hash。若未解析，通过公开 username 预热。"""
    if client is None or not chat_id:
        return
    try:
        numeric_chat_id = int(chat_id)
    except (ValueError, TypeError):
        numeric_chat_id = chat_id

    try:
        if hasattr(client, "resolve_peer"):
            await client.resolve_peer(numeric_chat_id)
            return
    except Exception:
        pass

    try:
        import db
        uname = db.get_channel_username_by_chat_id(numeric_chat_id)
        if uname and hasattr(client, "get_chat"):
            clean_uname = uname.lstrip("@")
            if not clean_uname.startswith("channel_"):
                await client.get_chat(f"@{clean_uname}")
                logger.info(f"成功通过 @{clean_uname} 预热 Pyrogram Peer 缓存: {numeric_chat_id}")
                return
        if hasattr(client, "get_chat"):
            await client.get_chat(numeric_chat_id)
    except Exception as e:
        logger.debug(f"预热 Pyrogram Peer 缓存失败 ({numeric_chat_id}): {e}")


def _extract_user_id(message: Message) -> int | None:
    from_user = getattr(message, "from_user", None)
    if from_user and getattr(from_user, "id", None):
        return from_user.id
    chat = getattr(message, "chat", None)
    if chat and str(getattr(chat, "type", "")).endswith("PRIVATE"):
        return getattr(chat, "id", None)
    return None


def is_allowed_user(message: Message) -> bool:
    """Authorize immutable numeric Telegram user IDs from config or registered tenants."""
    uid = _extract_user_id(message)
    if not uid:
        return False
    user_id = str(uid)
    if Var.ALLOWED_USERS and user_id in Var.ALLOWED_USERS:
        return True
    try:
        from configer import get_config_value
        admin_id = get_config_value("ADMIN_ID")
        if admin_id and int(uid) == int(admin_id):
            return True
    except Exception:
        pass
    try:
        import db
        db_u = db.get_user_by_tg_id(uid)
        if db_u:
            if db_u.get("role") == "admin" or db_u.get("bin_channel_id"):
                return True
    except Exception:
        pass
    return False


def get_target_bin_channel_for_message(message: Message):
    """获取消息对应的目标存储频道（普通租户严格使用专属频道，仅管理员/系统授权用户允许回退全局 BIN_CHANNEL）"""
    uid = _extract_user_id(message)
    if uid:
        try:
            import db
            db_u = db.get_user_by_tg_id(uid)
            if db_u:
                if db_u.get("bin_channel_id"):
                    return db_u["bin_channel_id"]
                if db_u.get("role") == "admin":
                    return Var.BIN_CHANNEL
                return None
        except Exception:
            pass

        try:
            from configer import get_config_value
            admin_id = get_config_value("ADMIN_ID")
            if admin_id and int(uid) == int(admin_id):
                return Var.BIN_CHANNEL
        except Exception:
            pass
        if Var.ALLOWED_USERS and str(uid) in Var.ALLOWED_USERS:
            return Var.BIN_CHANNEL
    return None


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
        try:
            reply_fn = getattr(first_msg, "reply_text", None) or getattr(first_msg, "reply", None)
            if reply_fn:
                await reply_fn(
                    "👋 <b>欢迎使用 MistRelay 极速云盘</b>\n\n"
                    "您当前尚未开通专属云盘空间，媒体组无法自动入库。\n"
                    "👉 请发送 /register 获取 6 位注册验证码，前往网页端一键开通专属存储频道！",
                    quote=True,
                    parse_mode=ParseMode.HTML,
                    reply_markup=ReplyKeyboardRemove(),
                )
        except Exception:
            pass
        return
    
    user_display = (
        getattr(getattr(first_msg, "from_user", None), "first_name", None)
        or getattr(getattr(first_msg, "chat", None), "title", None)
        or "用户"
    )
    # 目标存储频道检查
    target_bin = get_target_bin_channel_for_message(first_msg)
    if not target_bin:
        logger.warning(f"目标存储频道未配置或租户未绑定专属频道，无法为 {user_display} 生成直链")
        try:
            await first_msg.reply(
                "⚠️ 您尚未分配或开通专属存储频道，媒体组无法转存到 TG 网盘。\n"
                "请联系管理员分配专属存储空间或使用 /register 重新绑定。",
                quote=True,
            )
        except Exception:
            pass
        return

    await ensure_peer_cached(StreamBot, target_bin)
    
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
            # 优先使用 send_media_group 直接发布内存媒体对象，避免 copy_media_group 内部 get_messages 失败
            try:
                from pyrogram.types import InputMediaPhoto, InputMediaVideo, InputMediaAudio, InputMediaDocument
                multi_media = []
                for i, msg in enumerate(messages):
                    c_caption = clean_and_rebrand_caption(
                        msg.caption,
                        target_channel=target_channel,
                        signature=signature,
                        custom_rules=custom_rules,
                    ) if (msg.caption or (i == 0 and signature)) else (msg.caption or "")

                    if msg.photo:
                        multi_media.append(InputMediaPhoto(msg.photo.file_id, caption=c_caption))
                    elif msg.video:
                        multi_media.append(InputMediaVideo(msg.video.file_id, caption=c_caption))
                    elif msg.audio:
                        multi_media.append(InputMediaAudio(msg.audio.file_id, caption=c_caption))
                    elif msg.document:
                        multi_media.append(InputMediaDocument(msg.document.file_id, caption=c_caption))

                if multi_media and len(multi_media) == len(messages):
                    copied_msgs = await StreamBot.send_media_group(
                        chat_id=target_bin,
                        media=multi_media,
                    )
                    if isinstance(copied_msgs, list):
                        for i, log_msg in enumerate(copied_msgs):
                            if i < len(messages):
                                forwarded_messages.append((messages[i], log_msg))
                    elif copied_msgs:
                        forwarded_messages.append((messages[0], copied_msgs))
            except Exception as send_grp_err:
                logger.warning(f"send_media_group 无痕发布失败: {send_grp_err}，尝试 copy_media_group")
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
                        chat_id=target_bin,
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
                    logger.warning(f"copy_media_group 无痕发布失败: {copy_grp_err}，尝试逐条 copy")
                    try:
                        for msg in messages:
                            c_caption = clean_and_rebrand_caption(
                                msg.caption,
                                target_channel=target_channel,
                                signature=signature,
                                custom_rules=custom_rules,
                            ) if msg.caption else msg.caption
                            try:
                                c_msg = await msg.copy(
                                    chat_id=target_bin,
                                    caption=c_caption,
                                )
                            except Exception:
                                c_msg = await StreamBot.copy_message(
                                    chat_id=target_bin,
                                    from_chat_id=chat_id,
                                    message_id=msg.id,
                                    caption=c_caption,
                                )
                            forwarded_messages.append((msg, c_msg))
                    except Exception as copy_each_err:
                        logger.warning(f"逐条 copy 也失败: {copy_each_err}，回退到 forward")
                        forwarded_messages = []

        # 2. 若未启用无痕洗白或复制异常，安全回退到原转发
        if not forwarded_messages:
            try:
                forwarded_msgs = await StreamBot.forward_messages(
                    chat_id=target_bin,
                    from_chat_id=chat_id,
                    message_ids=message_ids,
                )
                if isinstance(forwarded_msgs, list):
                    for i, log_msg in enumerate(forwarded_msgs):
                        if i < len(messages):
                            forwarded_messages.append((messages[i], log_msg))
                elif forwarded_msgs:
                    forwarded_messages.append((messages[0], forwarded_msgs))
            except Exception as forward_err:
                logger.warning(f"forward_messages 失败: {forward_err}，尝试逐条 forward")
                for msg in messages:
                    try:
                        log_msg = await msg.forward(chat_id=target_bin)
                        forwarded_messages.append((msg, log_msg))
                    except Exception as e:
                        logger.error(f"逐条转发消息失败: {e}", exc_info=True)

        if not forwarded_messages:
            logger.error("所有消息转发/发布均失败")
            try:
                await first_msg.reply(
                    "❌ <b>处理失败</b>\n\n无法将媒体文件保存到 TG 网盘，请稍后重试",
                    quote=True,
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            return []

        # 3. 处理转发成功的消息，保存到数据库并生成直链
        stream_links = []
        for original_msg, log_msg in forwarded_messages:
            try:
                if isinstance(log_msg, list) and log_msg:
                    log_msg = log_msg[0]
                if not log_msg:
                    continue
                log_media = getattr(log_msg, log_msg.media.value, None) if getattr(log_msg, "media", None) else None
                raw_name = get_name(original_msg)
                cleaned_file_name = clean_drive_filename(
                    raw_name,
                    clean_enabled=clean_filenames,
                    custom_rules=custom_rules,
                ) if clean_filenames else raw_name

                file_name = cleaned_file_name
                file_hash = get_hash(log_msg, Var.HASH_LENGTH)
                stream_link = f"{Var.URL}{log_msg.id}/{quote_plus(file_name)}?hash={file_hash}"
                short_link = f"{Var.URL}{file_hash}{log_msg.id}"

                file_unique_id = None
                if log_media:
                    try:
                        raw_caption = getattr(original_msg, "caption", None)
                        cleaned_caption = clean_and_rebrand_caption(
                            raw_caption,
                            target_channel=target_channel,
                            signature=signature,
                            custom_rules=custom_rules,
                        ) if rebrand_enabled else raw_caption

                        file_unique_id = save_tg_media(
                            log_msg,
                            log_media,
                            custom_file_name=cleaned_file_name if clean_filenames else None,
                            custom_caption=cleaned_caption if rebrand_enabled else None,
                        )
                        try:
                            from thumbnail_worker import get_thumbnail_worker
                            get_thumbnail_worker().enqueue(log_msg.id, file_name=cleaned_file_name, chat_id=target_bin)
                        except Exception:
                            pass
                    except Exception as db_e:
                        logger.error(f"记录频道媒体到数据库失败: {db_e}", exc_info=True)

                link_entry = {
                    "name": file_name,
                    "full_link": stream_link,
                    "short_link": short_link,
                    "original_msg": original_msg,
                    "log_msg": log_msg,
                    "log_media": log_media,
                    "file_unique_id": file_unique_id,
                }
                stream_links.append(link_entry)
                logger.info(f"媒体已保存到TG网盘并生成直链： {stream_link} for {user_display}")
                    
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
            main_link = link_info["full_link"]
        else:
            saved_count = sum(1 for item in stream_links if item.get("file_unique_id"))
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
            main_link = stream_links[0]["full_link"] if stream_links else None
        
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
            else:
                try:
                    fallback_text = (
                        "✅ <b>已收到您的消息</b>\n\n"
                        "☁️ 媒体组已保存到 TG 网盘\n"
                        f"📊 共 {len(stream_links)} 个文件\n"
                        "✅ 处理完成"
                    )
                    await first_msg.reply_text(
                        fallback_text,
                        quote=True,
                        parse_mode=ParseMode.HTML,
                    )
                except Exception as e:
                    logger.debug(f"直接回复媒体组保存通知失败: {e}")
            
            logger.info(f"已处理媒体组（不发送直链信息）：共 {len(stream_links)} 个文件，已保存到TG网盘")
        
        return task_gids
    except Exception as e:
        logger.error(f"处理媒体组失败: {e}", exc_info=True)
        try:
            error_reply = (
                f"❌ <b>处理失败</b>\n\n"
                f"⚠️ 处理媒体组时出错，请稍后重试"
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
            f"🚫 <b>权限不足</b>\n\n"
            f"⚠️ 你没有权限使用这个机器人"
        )
        return await m.reply(permission_msg, quote=True, parse_mode=ParseMode.HTML)
    
    user_display = (
        getattr(getattr(m, "from_user", None), "first_name", None)
        or getattr(getattr(m, "chat", None), "title", None)
        or "用户"
    )
    # 目标存储频道检查
    target_bin = get_target_bin_channel_for_message(m)
    if not target_bin:
        logger.warning(f"目标存储频道未配置或租户未绑定专属频道，无法为 {user_display} 生成直链")
        return await m.reply(
            "⚠️ 您尚未分配或开通专属存储频道，文件无法转存到 TG 网盘。\n"
            "请联系管理员分配专属存储空间或使用 /register 重新绑定。",
            quote=True,
        )

    await ensure_peer_cached(StreamBot, target_bin)
    
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
                try:
                    log_msg = await m.copy(
                        chat_id=target_bin,
                        caption=cleaned_caption,
                    )
                except Exception as m_copy_err:
                    logger.debug(f"m.copy 失败: {m_copy_err}，尝试 StreamBot.copy_message")
                    log_msg = await StreamBot.copy_message(
                        chat_id=target_bin,
                        from_chat_id=m.chat.id,
                        message_id=m.id,
                        caption=cleaned_caption,
                    )
            except Exception as copy_err:
                logger.warning(f"无痕发布失败: {copy_err}，回退到 forward")
                try:
                    log_msg = await StreamBot.forward_messages(
                        chat_id=target_bin,
                        from_chat_id=m.chat.id,
                        message_ids=m.id,
                    )
                except Exception:
                    log_msg = await m.forward(chat_id=target_bin)
        else:
            try:
                log_msg = await StreamBot.forward_messages(
                    chat_id=target_bin,
                    from_chat_id=m.chat.id,
                    message_ids=m.id,
                )
            except Exception:
                log_msg = await m.forward(chat_id=target_bin)

        if isinstance(log_msg, list) and log_msg:
            log_msg = log_msg[0]

        if not log_msg:
            logger.error("消息转发/发布失败: log_msg is None")
            await m.reply("无法将媒体文件保存到 TG 网盘，请稍后重试", quote=True)
            return []

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
                    get_thumbnail_worker().enqueue(log_msg.id, file_name=cleaned_file_name, chat_id=target_bin)
                except Exception:
                    pass
            except Exception as db_e:
                logger.error(f"记录频道媒体到数据库失败: {db_e}", exc_info=True)

        file_hash = get_hash(log_msg, Var.HASH_LENGTH)
        stream_link = f"{Var.URL}{log_msg.id}/{quote_plus(cleaned_file_name)}?hash={file_hash}"
        short_link = f"{Var.URL}{file_hash}{log_msg.id}"
        
        logger.info(f"媒体已保存到TG网盘并生成直链： {stream_link} for {user_display}")
        
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
            else:
                try:
                    fallback_text = (
                        "✅ <b>已收到您的消息</b>\n\n"
                        "☁️ 文件已保存到 TG 网盘\n"
                        "✅ 处理完成"
                    )
                    await m.reply_text(
                        fallback_text,
                        quote=True,
                        parse_mode=ParseMode.HTML,
                    )
                except Exception as e:
                    logger.debug(f"直接回复单文件保存通知失败: {e}")
            
            logger.info(f"已处理文件（不发送直链信息）：{cleaned_file_name}，已保存到TG网盘")
        
        return []
    except Exception as e:
        logger.error(f"生成直链失败: {e}", exc_info=True)
        await m.reply("生成直链时出错，请稍后重试", quote=True)
        return []


@Client.on_message(
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
        try:
            reply_fn = getattr(m, "reply_text", None) or getattr(m, "reply", None)
            if reply_fn:
                await reply_fn(
                    "👋 <b>欢迎使用 MistRelay 极速云盘</b>\n\n"
                    "您当前尚未开通专属云盘空间，媒体文件无法自动入库。\n"
                    "👉 请发送 /register 获取 6 位注册验证码，前往网页端一键开通专属存储频道！\n\n"
                    "💡 开通后直接向我发送或转发媒体，即可极速入库并生成直链。",
                    quote=True,
                    parse_mode=ParseMode.HTML,
                    reply_markup=ReplyKeyboardRemove(),
                )
        except Exception as e:
            logger.debug(f"向未授权用户发送提示失败: {e}")
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
            await asyncio.sleep(1.0)
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


@Client.on_message(
    filters.private
    & filters.text
    & ~filters.command(["start", "help", "menu", "status", "register"]),
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
        try:
            reply_fn = getattr(m, "reply_text", None) or getattr(m, "reply", None)
            if reply_fn:
                await reply_fn(
                    "👋 <b>欢迎使用 MistRelay 极速云盘</b>\n\n"
                    "您当前尚未开通专属云盘空间，无法执行频道采集破除任务。\n"
                    "👉 请发送 /register 获取 6 位注册验证码，前往网页端一键开通专属存储频道！",
                    quote=True,
                    parse_mode=ParseMode.HTML,
                    reply_markup=ReplyKeyboardRemove(),
                )
        except Exception as e:
            logger.debug(f"向未授权用户发送提示失败: {e}")
        return

    target_bin = get_target_bin_channel_for_message(m) or Var.BIN_CHANNEL
    if not target_bin:
        await m.reply("❌ 目标存储频道未配置，无法保存媒体到 TG 网盘", quote=True)
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


@Client.on_message(
    filters.private
    & filters.command(["register"]),
    group=1,
)
async def user_register_command_handler(_, m: Message):
    """
    处理用户私聊发送 /register 获取 6 位注册验证码并探测归属 DC 区域，同时清除旧版残留键盘
    """
    import secrets as _secrets
    import db
    from botfather_creator import detect_user_dc_id

    from_user = getattr(m, "from_user", None)
    tg_uid = getattr(from_user, "id", None) or (m.chat.id if getattr(m, "chat", None) else None)
    if not tg_uid:
        return

    tg_uname = getattr(from_user, "username", None) or getattr(getattr(m, "chat", None), "username", None)
    tg_fname = getattr(from_user, "first_name", None) or getattr(getattr(m, "chat", None), "first_name", None) or "User"

    existing_u = db.get_user_by_tg_id(tg_uid)
    if existing_u and existing_u.get("bin_channel_id"):
        chan_handle = existing_u.get("bin_channel_username") or str(existing_u.get("bin_channel_id"))
        if not str(chan_handle).startswith("@") and not str(chan_handle).startswith("-"):
            chan_handle = f"@{chan_handle}"
        await m.reply_text(
            f"✅ <b>您已注册并开通 MistRelay 专属云盘</b>\n\n"
            f"👤 <b>登录账号:</b> <code>{existing_u.get('username')}</code>\n"
            f"🌐 <b>所属区域:</b> <code>DC{existing_u.get('dc_id') or 5}</code>\n"
            f"📡 <b>专属存储频道:</b> {chan_handle}\n\n"
            f"💡 您可以直接向我转发任意媒体或发送受限频道链接，文件将 100% 物理隔离保存在您的专属频道中！\n"
            f"📖 发送 /help 可随时查看详细功能与使用指南。",
            quote=True,
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    if not bool(db.get_config("ALLOW_USER_REGISTRATION", True)):
        await m.reply_text(
            "🚫 <b>当前系统已关闭自助注册</b>\n\n"
            "如需开通专属云盘空间，请联系系统管理员在后台为您手动创建账号。",
            quote=True,
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    detected_dc = detect_user_dc_id(from_user)
    code = f"{_secrets.randbelow(900000) + 100000}"
    db.create_tg_register_code(
        code=code,
        tg_user_id=tg_uid,
        tg_username=tg_uname,
        tg_first_name=tg_fname,
        detected_dc_id=detected_dc,
        expires_minutes=10,
    )

    dc_names = {
        1: "DC1 (美国/迈阿密)",
        2: "DC2 (欧洲/阿姆斯特丹)",
        3: "DC3 (美国/迈阿密)",
        4: "DC4 (欧洲/阿姆斯特丹)",
        5: "DC5 (亚太/新加坡)",
    }
    dc_desc = dc_names.get(detected_dc, f"DC{detected_dc}")

    reply_html = (
        f"🎉 <b>MistRelay 专属云盘注册验证码</b>\n\n"
        f"🔑 <b>您的 6 位验证码:</b> <code>{code}</code>\n"
        f"⏳ <i>有效期 10 分钟，请勿泄露给他人</i>\n\n"
        f"📊 <b>Telegram 账号识别结果:</b>\n"
        f"  • <b>TG ID:</b> <code>{tg_uid}</code>\n"
        f"  • <b>匹配数据中心:</b> <code>{dc_desc}</code>\n"
        f"  • <b>昵称:</b> {tg_fname}\n\n"
        f"🚀 <b>下一步:</b>\n"
        f"请返回 MistRelay 网页端「Telegram 验证码注册」页，填入上方 6 位验证码。系统将自动调配同区 (<b>DC{detected_dc}</b>) 协议号为您创建物理隔离的专属存储频道！"
    )
    await m.reply_text(
        reply_html,
        quote=True,
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )


@Client.on_message(
    filters.private
    & filters.command(["start"]),
    group=2,
)
async def start_command_handler(client, m: Message):
    """处理 /start 或 /start register 指令并清除旧版残留键盘"""
    import db
    text = (m.text or "").strip()
    if "register" in text.lower():
        return await user_register_command_handler(client, m)

    from_user = getattr(m, "from_user", None)
    if not is_allowed_user(m):
        await m.reply_text(
            "👋 <b>欢迎使用 MistRelay 极速云盘</b>\n\n"
            "您当前尚未开通专属云盘空间。\n"
            "👉 请发送 /register 获取 6 位注册验证码，前往网页端一键开通与您 Telegram 账号同 DC 区域的专属存储频道！\n\n"
            "💡 发送 /help 可随时查看详细功能与使用指南。",
            quote=True,
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    chan_info = ""
    uid = getattr(from_user, "id", None) or (m.chat.id if getattr(m, "chat", None) else None)
    if uid:
        existing_u = db.get_user_by_tg_id(uid)
        if existing_u and existing_u.get("bin_channel_id"):
            chan_handle = existing_u.get("bin_channel_username") or str(existing_u.get("bin_channel_id"))
            if not str(chan_handle).startswith("@") and not str(chan_handle).startswith("-"):
                chan_handle = f"@{chan_handle}"
            chan_info = (
                f"\n👤 <b>登录账号:</b> <code>{existing_u.get('username')}</code>\n"
                f"🌐 <b>所属区域:</b> <code>DC{existing_u.get('dc_id') or 5}</code>\n"
                f"📡 <b>专属存储频道:</b> {chan_handle}\n"
            )

    await m.reply_text(
        f"🚀 <b>MistRelay 云盘服务已就绪</b>\n{chan_info}\n"
        "• <b>媒体入库:</b> 直接向我发送/转发视频、图片或文件，秒存入库并生成直链；\n"
        "• <b>受限破除:</b> 直接发送私密/受限频道帖子链接，全自动破除限制并归档；\n"
        "• <b>离线下载:</b> 发送磁力链接 (magnet:) 或种子文件 (.torrent) 自动离线下载；\n"
        "• <b>使用指南:</b> 发送 /help 查看完整使用说明；\n"
        "• <b>空间绑定:</b> 发送 /register 查看或绑定专属存储频道。",
        quote=True,
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )


@Client.on_message(
    filters.private
    & filters.command(["help"]),
    group=3,
)
async def help_command_handler(_, m: Message):
    """处理 /help 指令，展示现代化云盘与下载功能使用指南并清除旧版键盘"""
    help_text = (
        "📖 <b>MistRelay 极速云盘使用指南</b>\n\n"
        "<b>☁️ 1. 媒体秒存与极速直链</b>\n"
        "• 直接向本机器人发送或转发任何视频、音频、图片或文档；\n"
        "• 系统将自动无痕归档至您的专属存储频道，并生成多 Bot 聚合串流直链与在线播放地址。\n\n"
        "<b>🔓 2. 受限/私密频道资源破除采集</b>\n"
        "• 直接发送 Telegram 帖子链接（支持 <code>https://t.me/...</code> 公开或私密链接）；\n"
        "• 针对禁止转发/限制下载频道，全自动调动 55+ Bot 集群极速拉取并洗白重传。\n\n"
        "<b>📥 3. 离线下载投递</b>\n"
        "• 发送普通 HTTP/HTTPS 文件下载链接；\n"
        "• 发送磁力链接（<code>magnet:?xt=...</code>）；\n"
        "• 发送 <code>.torrent</code> 种子文件；\n"
        "• Aria2 离线下载完成后将自动秒传至您的专属存储频道。\n\n"
        "<b>👤 4. 账号与专属频道</b>\n"
        "• <code>/register</code> - 获取注册验证码或查看已绑定的同 DC 专属存储频道；\n"
        "• <code>/start</code> - 查看服务运行状态与快速入口。"
    )
    await m.reply_text(
        help_text,
        quote=True,
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )


STREAM_HANDLERS = [
    (user_register_command_handler, 1),
    (start_command_handler, 2),
    (help_command_handler, 3),
    (media_receive_handler, 4),
    (channel_link_receive_handler, 5),
]


def register_stream_handlers(client: Client) -> None:
    """确保 Stream 插件的所有消息处理器被正确注册到 client.dispatcher 中（防丢 Handler 保护）"""
    if not client or not getattr(client, "dispatcher", None):
        return
    for func, target_group in STREAM_HANDLERS:
        handlers_to_add = getattr(func, "handlers", None)
        if not handlers_to_add:
            continue
        for handler, group in handlers_to_add:
            effective_group = group if group is not None else target_group
            existing = client.dispatcher.groups.get(effective_group, [])
            already_registered = any(
                getattr(h, "callback", None) == func
                for h in existing
            )
            if not already_registered:
                client.add_handler(handler, effective_group)
                logger.info(
                    f"已为客户端 {getattr(client, 'name', 'bot')} 注册处理器 {func.__name__} (group {effective_group})"
                )
