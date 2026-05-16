"""
Aria2客户端工具函数
"""
import logging
import os


logger = logging.getLogger(__name__)

def format_progress_bar(percentage_str):
    """
    根据百分比生成进度条
    返回: 进度条字符串（使用 Unicode 字符）
    """
    try:
        # 提取百分比数字
        percentage = float(percentage_str.replace('%', ''))
        # 限制在 0-100 之间
        percentage = max(0, min(100, percentage))
        
        # 进度条长度（20个字符）
        bar_length = 20
        filled_length = int(bar_length * percentage / 100)
        
        # 使用不同的字符表示进度
        filled_char = '█'
        empty_char = '░'
        
        bar = filled_char * filled_length + empty_char * (bar_length - filled_length)
        return bar
    except Exception:
        return '░' * 20


def verify_file_size(file_path, expected_size, tolerance=1024):
    """
    校验文件大小是否与期望值匹配
    
    Args:
        file_path: 文件路径
        expected_size: 期望的文件大小(字节)
        tolerance: 允许的误差范围(字节),默认1KB
    
    Returns:
        bool: 大小是否匹配
    """
    try:
        if not os.path.exists(file_path):
            logger.info(f"[校验] 文件不存在: {file_path}")
            return False
        
        actual_size = os.path.getsize(file_path)
        size_diff = abs(actual_size - expected_size)
        
        if size_diff <= tolerance:
            return True
        else:
            from util import byte2_readable
            logger.info(f"[校验] 文件大小不匹配:")
            logger.info(f"  文件: {os.path.basename(file_path)}")
            logger.info(f"  期望: {byte2_readable(expected_size)}")
            logger.info(f"  实际: {byte2_readable(actual_size)}")
            logger.info(f"  差异: {byte2_readable(size_diff)}")
            return False
    except Exception as e:
        logger.error(f"[校验] 校验文件大小时出错: {e}", exc_info=True)
        return False


def calculate_file_md5(file_path, chunk_size=8192):
    """
    计算文件的MD5哈希值
    
    Args:
        file_path: 文件路径
        chunk_size: 读取块大小(字节),默认8KB
    
    Returns:
        str: MD5哈希值(小写十六进制),失败返回None
    """
    import hashlib
    
    try:
        if not os.path.exists(file_path):
            logger.info(f"[MD5] 文件不存在: {file_path}")
            return None
        
        md5_hash = hashlib.md5()
        
        with open(file_path, 'rb') as f:
            # 分块读取文件,避免大文件占用过多内存
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                md5_hash.update(chunk)
        
        result = md5_hash.hexdigest()
        logger.info(f"[MD5] 计算完成: {os.path.basename(file_path)} = {result}")
        return result
        
    except Exception as e:
        logger.exception(f"[MD5] 计算MD5失败: {e}")
        return None
