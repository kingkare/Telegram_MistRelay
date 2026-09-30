import pyrogram_patch
"""
缩略图生成器

负责:
1. 生成图片缩略图(使用 Pillow)
2. 生成视频缩略图(使用 ffmpeg)
3. 多级缓存管理(内存LRU + 磁盘持久化)
4. 使用WebP格式(更小体积,更好质量)
"""

import os
import hashlib
import subprocess
import logging
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime, timedelta
from functools import lru_cache
from PIL import Image

logger = logging.getLogger(__name__)


class ThumbnailGenerator:
    """缩略图生成器"""
    
    # 支持的图片格式
    IMAGE_EXTENSIONS = {
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', 
        '.webp', '.tiff', '.ico', '.svg'
    }
    
    # 支持的视频格式
    VIDEO_EXTENSIONS = {
        '.mp4', '.avi', '.mkv', '.mov', '.wmv', 
        '.flv', '.webm', '.m4v', '.mpg', '.mpeg'
    }
    
    def __init__(
        self, 
        cache_dir: str = "/app/cache/thumbnails",
        thumbnail_size: Tuple[int, int] = (400, 400),
        cache_max_age_days: int = 7,
        memory_cache_size: int = 100
    ):
        """
        初始化缩略图生成器
        
        Args:
            cache_dir: 缓存目录
            thumbnail_size: 缩略图尺寸(宽, 高)
            cache_max_age_days: 缓存有效期(天)
            memory_cache_size: 内存缓存大小(LRU)
        """
        resolved_dir = Path(cache_dir)
        if cache_dir == "/app/cache/thumbnails":
            local_cache = Path(__file__).resolve().parent / "cache" / "thumbnails"
            if local_cache != resolved_dir and local_cache.exists() and any(local_cache.rglob("*.webp")):
                if not resolved_dir.exists() or not any(resolved_dir.rglob("*.webp")):
                    resolved_dir = local_cache
        self.cache_dir = resolved_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 内存缓存(存储缓存路径)
        from functools import lru_cache
        self._get_cached_path = lru_cache(maxsize=memory_cache_size)(self._get_cached_path_impl)
        self.thumbnail_size = thumbnail_size
        self.cache_max_age_days = cache_max_age_days
        
        logger.info(f"缩略图生成器初始化完成,缓存目录: {self.cache_dir}, 尺寸: {thumbnail_size}")
    
    def _get_cache_key(self, remote_name: str, file_path: str) -> str:
        """生成缓存key"""
        # 使用 remote + 文件路径的 hash 作为缓存key
        content = f"{remote_name}:{file_path}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _get_cache_path(self, remote_name: str, file_path: str) -> Path:
        """获取缓存文件路径"""
        cache_key = self._get_cache_key(remote_name, file_path)
        # 按 remote 分组存储
        remote_cache_dir = self.cache_dir / remote_name
        remote_cache_dir.mkdir(parents=True, exist_ok=True)
        return remote_cache_dir / f"{cache_key}.webp"  # 使用WebP格式
    
    def _get_cached_path_impl(self, remote_name: str, file_path: str) -> Optional[Path]:
        """内存缓存的实际实现(被LRU装饰)"""
        cache_path = self._get_cache_path(remote_name, file_path)
        if cache_path.exists() and self._is_cache_valid(cache_path):
            return cache_path
        return None
    
    def _is_cache_valid(self, cache_path: Path) -> bool:
        """检查缓存是否有效(未过期且大小有效)"""
        if not cache_path.exists():
            return False

        try:
            if cache_path.stat().st_size <= 64:
                try:
                    cache_path.unlink()
                except Exception:
                    pass
                return False

            cache_time = datetime.fromtimestamp(cache_path.stat().st_mtime)
            expiry_time = datetime.now() - timedelta(days=self.cache_max_age_days)

            if cache_time < expiry_time:
                logger.info(f"缓存已过期: {cache_path}")
                try:
                    cache_path.unlink()
                except Exception:
                    pass
                return False
        except Exception:
            return False

        return True

    def is_cached(self, remote_name: str, file_path: str) -> bool:
        """检查缩略图是否已缓存且有效"""
        cache_path = self._get_cache_path(remote_name, file_path)
        return self._is_cache_valid(cache_path)

    def _is_image_content(self, path: Path) -> bool:
        """检测文件是否包含有效图片头（例如从 TG 下载的视频内嵌 JPEG 封面）"""
        try:
            if not path.exists() or path.stat().st_size < 12:
                return False
            with path.open("rb") as f:
                header = f.read(12)
            if header.startswith(b"\xff\xd8\xff"):
                return True
            if header.startswith(b"\x89PNG\r\n\x1a\n"):
                return True
            if header.startswith((b"GIF87a", b"GIF89a")):
                return True
            if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
                return True
            if header.startswith(b"BM"):
                return True
        except Exception:
            pass
        return False
    
    def get_cached_thumbnail(self, remote_name: str, file_path: str) -> Optional[Path]:
        """获取缓存的缩略图路径"""
        if self.is_cached(remote_name, file_path):
            return self._get_cache_path(remote_name, file_path)
        return None
    
    def _is_image(self, file_path: str) -> bool:
        """判断是否为图片文件"""
        ext = Path(file_path).suffix.lower()
        return ext in self.IMAGE_EXTENSIONS
    
    def _is_video(self, file_path: str) -> bool:
        """判断是否为视频文件"""
        ext = Path(file_path).suffix.lower()
        return ext in self.VIDEO_EXTENSIONS
    
    def generate_image_thumbnail(self, source_path: Path, output_path: Path) -> bool:
        """
        生成图片缩略图
        
        Args:
            source_path: 原始图片路径
            output_path: 输出缩略图路径
            
        Returns:
            是否成功
        """
        try:
            logger.info(f"生成图片缩略图: {source_path.name}")
            
            with Image.open(source_path) as img:
                # 转换为 RGB 模式(处理 PNG 透明度等问题)
                if img.mode in ('RGBA', 'LA', 'P'):
                    # 创建白色背景
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # 生成缩略图(保持宽高比)
                img.thumbnail(self.thumbnail_size, Image.Resampling.LANCZOS)
                
                # 保存为 WebP (更小体积,更好质量)
                img.save(output_path, 'WEBP', quality=85, method=4)
            
            logger.info(f"图片缩略图生成成功: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"生成图片缩略图失败: {e}", exc_info=True)
            return False
    
    def generate_video_thumbnail(self, source_path: Path, output_path: Path) -> bool:
        """
        生成视频缩略图
        
        Args:
            source_path: 原始视频路径
            output_path: 输出缩略图路径
            
        Returns:
            是否成功
        """
        try:
            logger.info(f"生成视频缩略图: {source_path.name}")
            
            # 使用 ffmpeg 提取第1秒的帧并转换为WebP
            cmd = [
                'ffmpeg',
                '-ss', '00:00:01',  # 跳到第1秒
                '-i', str(source_path),
                '-vframes', '1',    # 只提取1帧
                '-vf', f'scale={self.thumbnail_size[0]}:-1',  # 缩放,保持宽高比
                '-c:v', 'libwebp',  # 使用WebP编码器
                '-quality', '85',    # WebP质量
                '-y',               # 覆盖已存在的文件
                str(output_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.warning(f"本地样本视频帧提取未命中 ({source_path.name}): {result.stderr[-200:] if result.stderr else ''}")
                return False
            
            if not output_path.exists() or output_path.stat().st_size == 0:
                logger.warning("视频缩略图生成失败: 输出文件不存在或为空")
                return False
            
            logger.info(f"视频缩略图生成成功: {output_path}")
            return True
            
        except subprocess.TimeoutExpired:
            logger.error(f"生成视频缩略图超时: {source_path}")
            return False
        except Exception as e:
            logger.error(f"生成视频缩略图失败: {e}", exc_info=True)
            return False

    def generate_video_thumbnail_from_url(self, stream_url: str, output_path: Path, timeout: int = 25) -> bool:
        """
        通过支持 HTTP Range 的本地流直链提取视频缩略图，
        完美解决 MP4 moov 索引位于文件尾部导致前 12MB 样本无法解析的问题。
        """
        try:
            logger.info(f"通过 HTTP Range 流提取视频缩略图: {output_path.name}")
            cmd = [
                'ffmpeg',
                '-ss', '00:00:01',
                '-i', stream_url,
                '-vframes', '1',
                '-vf', f'scale={self.thumbnail_size[0]}:-1',
                '-c:v', 'libwebp',
                '-quality', '85',
                '-y',
                str(output_path),
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 64:
                logger.info(f"HTTP Range 视频缩略图生成成功: {output_path}")
                return True
            logger.error(f"HTTP Range ffmpeg 执行失败: {result.stderr[-300:] if result.stderr else ''}")
            return False
        except subprocess.TimeoutExpired:
            logger.error("HTTP Range 生成视频缩略图超时")
            return False
        except Exception as e:
            logger.error(f"HTTP Range 生成视频缩略图失败: {e}", exc_info=True)
            return False

    def generate_thumbnail(
        self, 
        remote_name: str,
        file_path: str,
        source_local_path: Path,
        stream_url: Optional[str] = None,
    ) -> Optional[Path]:
        """
        生成缩略图(自动判断文件类型)
        
        Args:
            remote_name: remote 名称
            file_path: 云盘文件路径
            source_local_path: 文件在 VFS 挂载点的本地路径
            stream_url: 可选的本地 HTTP Range 流地址(当 MP4 moov 在文件尾部时回退使用)
            
        Returns:
            缩略图路径,或 None(失败)
        """
        # 检查内存缓存+磁盘缓存
        cached = self._get_cached_path(remote_name, file_path)
        if cached:
            logger.info(f"缓存命中: {file_path}")
            return cached
        
        # 获取输出路径
        output_path = self._get_cache_path(remote_name, file_path)
        
        # 根据文件类型生成缩略图
        success = False
        has_local = source_local_path is not None and source_local_path.exists() and source_local_path.stat().st_size > 0
        if has_local and (
            self._is_image_content(source_local_path)
            or self._is_image(str(source_local_path))
            or self._is_image(file_path)
        ):
            success = self.generate_image_thumbnail(source_local_path, output_path)
        elif self._is_video(file_path):
            if has_local:
                success = self.generate_video_thumbnail(source_local_path, output_path)
            if not success and stream_url:
                success = self.generate_video_thumbnail_from_url(stream_url, output_path)
        else:
            if not has_local:
                logger.error(f"源文件不存在: {source_local_path}")
            else:
                logger.warning(f"不支持的文件类型: {file_path}")
            return None
        
        if success and output_path.exists() and output_path.stat().st_size > 64:
            return output_path
        
        return None
    
    def clear_old_cache(self):
        """清理过期缓存"""
        logger.info("开始清理过期缓存...")
        expiry_time = datetime.now() - timedelta(days=self.cache_max_age_days)
        cleared_count = 0
        
        for cache_file in self.cache_dir.rglob("*.webp"):
            cache_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
            if cache_time < expiry_time:
                cache_file.unlink()
                cleared_count += 1
        
        logger.info(f"清理完成,删除了 {cleared_count} 个过期缓存")
    
    def get_cache_stats(self) -> dict:
        """获取缓存统计信息"""
        total_files = 0
        total_size = 0
        
        for cache_file in self.cache_dir.rglob("*.webp"):
            total_files += 1
            total_size += cache_file.stat().st_size
        
        return {
            "total_files": total_files,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "cache_dir": str(self.cache_dir)
        }


# 全局单例
_thumbnail_generator: Optional[ThumbnailGenerator] = None


def get_thumbnail_generator() -> ThumbnailGenerator:
    """获取全局缩略图生成器实例"""
    global _thumbnail_generator
    if _thumbnail_generator is None:
        _thumbnail_generator = ThumbnailGenerator()
    return _thumbnail_generator

def remove_cached_telegram_thumbnail(
    message_id: int,
    file_name: Optional[str] = None,
    chat_id: Optional[int] = None,
) -> bool:
    """
    移除指定 Telegram 媒体的 WebP 缩略图缓存并清理内存 LRU
    """
    try:
        generator = get_thumbnail_generator()
        default_bin = None
        try:
            from WebStreamer.vars import Var
            default_bin = getattr(Var, 'BIN_CHANNEL', None)
        except Exception:
            pass

        fname = file_name or ''
        keys_to_check = []
        if chat_id is not None and str(chat_id) != str(default_bin):
            keys_to_check.append(f'{chat_id}_{message_id}_{fname}')
        keys_to_check.append(f'{message_id}_{fname}')

        removed = False
        for k in keys_to_check:
            try:
                cache_path = generator._get_cache_path('telegram', k)
                if cache_path.exists():
                    cache_path.unlink(missing_ok=True)
                    removed = True
            except Exception:
                pass

        if hasattr(generator, '_get_cached_path'):
            try:
                generator._get_cached_path.cache_clear()
            except Exception:
                pass
        return removed
    except Exception as e:
        logger.debug(f'移除 Telegram 缩略图缓存异常: {e}')
        return False

