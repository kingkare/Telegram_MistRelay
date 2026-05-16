# This file is a part of TG-FileStreamBot
# Coding : Jyothis Jayanth [@EverythingSuckz]

"""
任务跟踪模块
跟踪下载任务的完成状态（包括上传和清理）
"""

import logging
import asyncio

logger = logging.getLogger(__name__)

# 任务完成跟踪：跟踪每个下载任务的完成状态（包括上传和清理）
# 格式: {gid: {'status': 'downloading'|'completed'|'uploaded'|'cleaned'|'failed', 'completed_at': timestamp}}
task_completion_tracker = {}
task_completion_lock = asyncio.Lock() if asyncio else None


async def wait_for_tasks_completion(task_gids: list):
    """
    等待所有下载任务完成（包括上传和清理）
    
    Args:
        task_gids: 下载任务GID列表
    """
    global task_completion_lock  # 必须在函数开头声明global
    
    # 延迟导入避免循环依赖
    from .utils import aria2_client
    
    if not task_gids:
        return
    
    logger.info(f"等待 {len(task_gids)} 个下载任务完成（包括上传和清理）...")
    
    # 确保锁已初始化
    if task_completion_lock is None:
        try:
            task_completion_lock = asyncio.Lock()
        except RuntimeError:
            logger.warning("无法创建任务完成锁，跳过等待")
            return
    
    completed_gids = set()
    check_interval = 5  # 每5秒检查一次
    max_wait_time = 3600 * 24  # 最大等待24小时（防止无限等待）
    wait_start = asyncio.get_event_loop().time()
    last_log_time = 0
    try:
        from configer import get_config_value
        wait_for_cleanup = bool(get_config_value('UP_TELEGRAM', True))
    except Exception:
        wait_for_cleanup = True
    
    while len(completed_gids) < len(task_gids):
        # 检查是否超时
        elapsed_time = asyncio.get_event_loop().time() - wait_start
        if elapsed_time > max_wait_time:
            logger.warning(f"等待任务完成超时（{max_wait_time}秒），已等待: {elapsed_time:.1f}秒")
            break
        
        # 定期记录等待状态（每30秒记录一次）
        if elapsed_time - last_log_time >= 30:
            remaining_count = len(task_gids) - len(completed_gids)
            logger.info(f"等待任务完成中... 已完成: {len(completed_gids)}/{len(task_gids)}，剩余: {remaining_count}")
            last_log_time = elapsed_time
        
        # 检查每个任务的状态
        for gid in task_gids:
            if gid in completed_gids:
                continue
            
            try:
                # 检查任务完成状态
                async with task_completion_lock:
                    task_status = task_completion_tracker.get(gid, {})
                    status = task_status.get('status', 'downloading')
                    
                    # 开启 TG 上传时，全流程完成必须等到上传后本地文件清理完成。
                    # 未开启上传时，下载完成即可释放队列。
                    if status == 'failed' or status == 'cleaned' or (not wait_for_cleanup and status == 'completed'):
                        completed_gids.add(gid)
                        continue
                
                # 检查aria2任务状态
                if aria2_client:
                    try:
                        aria2_status = await aria2_client.tell_status(gid)
                        aria2_task_status = aria2_status.get('status', '')
                        
                        # 如果aria2任务已完成，检查上传和清理状态
                        if aria2_task_status == 'complete':
                            # 检查任务完成跟踪器中的状态
                            async with task_completion_lock:
                                task_status = task_completion_tracker.get(gid, {})
                                status = task_status.get('status', 'completed')
                                
                                # 清理成功或上传失败都是队列等待的终态
                                if status == 'failed':
                                    completed_gids.add(gid)
                                elif status == 'cleaned':
                                    completed_gids.add(gid)
                                # 如果状态是uploaded（已上传），等待上传处理器完成本地清理（状态变为cleaned）
                                elif status == 'uploaded':
                                    pass
                                # 如果状态是completed（仅下载完成），检查是否启用了 Telegram 上传
                                elif status == 'completed' and not wait_for_cleanup:
                                    completed_gids.add(gid)
                        elif aria2_task_status in ['error', 'removed']:
                            # 任务失败或被移除，标记为完成（不再等待）
                            completed_gids.add(gid)
                            logger.warning(f"任务 {gid} 状态为 {aria2_task_status}，不再等待")
                    except Exception as e:
                        # 如果无法获取状态，可能是任务不存在或已删除
                        logger.debug(f"无法获取任务 {gid} 状态: {e}")
                        # 检查任务完成跟踪器
                        async with task_completion_lock:
                            task_status = task_completion_tracker.get(gid, {})
                            if task_status.get('status') in ('cleaned', 'failed'):
                                completed_gids.add(gid)
            except Exception as e:
                logger.debug(f"检查任务 {gid} 完成状态时出错: {e}")
        
        # 如果还有未完成的任务，等待一段时间后重试
        if len(completed_gids) < len(task_gids):
            await asyncio.sleep(check_interval)
    
    completed_count = len(completed_gids)
    logger.info(f"任务完成等待结束：{completed_count}/{len(task_gids)} 个任务已完成")
    
    # 清理已完成的任务跟踪记录（保留最近1小时内的记录）
    if task_completion_lock:
        try:
            async with task_completion_lock:
                current_time = asyncio.get_event_loop().time()
                gids_to_remove = []
                for gid, status_info in task_completion_tracker.items():
                    completed_at = status_info.get('completed_at', 0)
                    if completed_at > 0 and current_time - completed_at > 3600:  # 1小时前完成的
                        gids_to_remove.append(gid)
                for gid in gids_to_remove:
                    del task_completion_tracker[gid]
        except Exception as e:
            logger.debug(f"清理任务跟踪记录时出错: {e}")
