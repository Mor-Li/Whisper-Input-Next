import os
import json
import shutil
import threading
from datetime import datetime
from typing import Optional

from ..utils.logger import logger


CACHE_FILENAME = "cache.json"
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".webm", ".pcm"}


class TranscriptionCacheError(RuntimeError):
    """缓存读不出来且无法恢复。调用方必须放弃写入，否则会用空缓存覆盖历史记录。"""


class AudioArchiveManager:
    def __init__(self, archive_dir: str = "audio_archive"):
        self.archive_dir = archive_dir
        self.audio_dir = os.path.join(self.archive_dir, "audio")
        self.cache_path = os.path.join(self.archive_dir, CACHE_FILENAME)
        self.backup_path = f"{self.cache_path}.bak"
        # 队列 worker 和流式回调分属两个线程，读-改-写缓存必须串行，否则会丢记录
        self._cache_lock = threading.Lock()
        self.ensure_directory()

    def ensure_directory(self) -> None:
        if not os.path.exists(self.archive_dir):
            os.makedirs(self.archive_dir)
            logger.info(f"创建音频存档目录: {self.archive_dir}")
        if not os.path.exists(self.audio_dir):
            os.makedirs(self.audio_dir)
            logger.info(f"创建音频文件目录: {self.audio_dir}")
        self._migrate_legacy_archive_entries()

    def _build_unique_path(self, directory: str, filename: str) -> str:
        name, ext = os.path.splitext(filename)
        candidate = os.path.join(directory, filename)
        suffix = 1

        while os.path.exists(candidate):
            candidate = os.path.join(directory, f"{name}_{suffix}{ext}")
            suffix += 1

        return candidate

    def _migrate_legacy_archive_entries(self) -> None:
        """把老版本直接堆在 audio_archive/ 根目录的录音挪进 audio/ 子目录。

        只搬音频文件：缓存及其备份、以及用户自己放进来的任何东西都不能被搬走。
        """
        for entry in os.listdir(self.archive_dir):
            source_path = os.path.join(self.archive_dir, entry)
            if not os.path.isfile(source_path):
                continue
            if os.path.splitext(entry)[1].lower() not in AUDIO_EXTENSIONS:
                continue

            target_path = self._build_unique_path(self.audio_dir, entry)
            shutil.move(source_path, target_path)
            logger.info(f"迁移历史录音到子目录: {target_path}")

    def save_audio_bytes(self, audio_bytes: bytes, prefix: str = "recording") -> Optional[str]:
        if not audio_bytes:
            return None

        self.ensure_directory()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{prefix}_{timestamp}"
        archive_path = os.path.join(self.audio_dir, f"{base_name}.wav")
        suffix = 1

        while os.path.exists(archive_path):
            archive_path = os.path.join(self.audio_dir, f"{base_name}_{suffix}.wav")
            suffix += 1

        try:
            with open(archive_path, "wb") as archive_file:
                archive_file.write(audio_bytes)
            logger.info(f"音频文件已保存到存档: {archive_path}")
            return archive_path
        except Exception as exc:  # noqa: BLE001
            logger.error(f"保存音频文件到存档失败: {exc}")
            return None

    def load_transcription_cache(self) -> dict:
        """读取缓存。读不成功时绝不静默返回空字典，否则下一次保存会清空全部历史。"""
        if not os.path.exists(self.cache_path):
            return {}

        try:
            with open(self.cache_path, "r", encoding="utf-8") as cache_file:
                cache_data = json.load(cache_file)
        except OSError as exc:
            # 文件本身可能是好的，只是这次读不动（权限、IO 错误）：不改名，也不返回空
            logger.error(f"读取转录缓存失败: {exc}")
            raise TranscriptionCacheError(f"读取转录缓存失败: {exc}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return self._handle_corrupt_cache(str(exc))

        if not isinstance(cache_data, dict):
            return self._handle_corrupt_cache(
                f"顶层结构应为 dict，实际是 {type(cache_data).__name__}"
            )

        return cache_data

    def _handle_corrupt_cache(self, reason: str) -> dict:
        """缓存内容坏了：先改名留证，再尝试用上一代备份顶上。"""
        logger.error(f"转录缓存已损坏: {reason}")

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        quarantine_path = self._build_unique_path(
            self.archive_dir, f"{CACHE_FILENAME}.corrupt-{timestamp}"
        )
        try:
            os.replace(self.cache_path, quarantine_path)
        except OSError as exc:
            # 连改名都失败，就更不能往下写了，直接让本次保存中止
            raise TranscriptionCacheError(f"保留损坏的转录缓存失败: {exc}") from exc
        logger.error(f"损坏的转录缓存已改名保留: {quarantine_path}")

        backup_data = self._load_backup_cache()
        if backup_data is not None:
            logger.warning(f"已从备份恢复转录缓存: {len(backup_data)} 条记录")
            return backup_data

        logger.error(
            f"没有可用备份，本次从空缓存重新开始；历史记录仍完整保存在 {quarantine_path}"
        )
        return {}

    def _load_backup_cache(self) -> Optional[dict]:
        if not os.path.exists(self.backup_path):
            return None

        try:
            with open(self.backup_path, "r", encoding="utf-8") as backup_file:
                backup_data = json.load(backup_file)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.error(f"备份缓存也无法读取: {exc}")
            return None

        if not isinstance(backup_data, dict):
            logger.error("备份缓存格式异常，放弃恢复")
            return None

        return backup_data

    def _snapshot_current_cache(self) -> None:
        """给当前 cache.json 留一份上一代快照。

        用硬链接而不是复制：5MB 的文件也只是新建一个目录项，不搬数据。
        随后 os.replace 把 cache.json 指向新内容，.bak 仍指着旧内容那个 inode。
        """
        if not os.path.exists(self.cache_path):
            return

        link_path = f"{self.backup_path}.new"
        try:
            if os.path.exists(link_path):
                os.remove(link_path)
            os.link(self.cache_path, link_path)
            os.replace(link_path, self.backup_path)
        except OSError as exc:
            logger.warning(f"生成缓存备份失败（不影响本次保存）: {exc}")

    def save_transcription_cache(self, cache_data: dict) -> None:
        """原子写入：先写临时文件并落盘，再整体替换，中途被杀不会留下半截文件。"""
        self.ensure_directory()
        # 临时文件名带进程号：万一同时开了两个实例，也不会互相踩对方写到一半的临时文件
        tmp_path = f"{self.cache_path}.{os.getpid()}.tmp"

        try:
            with open(tmp_path, "w", encoding="utf-8") as cache_file:
                json.dump(cache_data, cache_file, ensure_ascii=False, indent=2)
                cache_file.flush()
                os.fsync(cache_file.fileno())

            self._snapshot_current_cache()
            os.replace(tmp_path, self.cache_path)
            logger.info(f"转录缓存已保存: {self.cache_path} ({len(cache_data)} 条)")
        except Exception as exc:  # noqa: BLE001
            logger.error(f"保存转录缓存失败: {exc}")
            self._discard_tmp_cache(tmp_path)

    def _discard_tmp_cache(self, tmp_path: str) -> None:
        if not os.path.exists(tmp_path):
            return
        try:
            os.remove(tmp_path)
        except OSError as exc:
            logger.warning(f"清理临时缓存文件失败: {exc}")

    def save_transcription_result(
        self,
        archive_path: Optional[str],
        transcription_result: str,
        *,
        service: str,
        model: str,
        mode: str = "transcriptions",
    ) -> None:
        if not archive_path or not transcription_result:
            return

        audio_filename = os.path.basename(archive_path)
        with self._cache_lock:
            try:
                cache = self.load_transcription_cache()
            except TranscriptionCacheError as exc:
                logger.error(f"跳过本次缓存写入，避免覆盖历史记录: {exc}")
                return

            cache[audio_filename] = {
                "transcription": transcription_result,
                "service": service,
                "model": model,
                "mode": mode,
                "timestamp": datetime.now().isoformat(),
            }
            self.save_transcription_cache(cache)
