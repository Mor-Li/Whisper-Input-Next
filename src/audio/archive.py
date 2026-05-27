import os
import json
import shutil
from datetime import datetime
from typing import Optional

from ..utils.logger import logger


class AudioArchiveManager:
    def __init__(self, archive_dir: str = "audio_archive"):
        self.archive_dir = archive_dir
        self.audio_dir = os.path.join(self.archive_dir, "audio")
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
        for entry in os.listdir(self.archive_dir):
            if entry in {"cache.json", "audio", "transcribe"}:
                continue

            source_path = os.path.join(self.archive_dir, entry)
            if os.path.isfile(source_path):
                target_path = self._build_unique_path(self.audio_dir, entry)
                shutil.move(source_path, target_path)
                logger.info(f"迁移归档文件到子目录: {target_path}")
            elif os.path.isdir(source_path):
                target_path = os.path.join(self.audio_dir, entry)
                if os.path.exists(target_path):
                    for child_entry in os.listdir(source_path):
                        child_source = os.path.join(source_path, child_entry)
                        if os.path.isfile(child_source):
                            child_target = self._build_unique_path(target_path, child_entry)
                            shutil.move(child_source, child_target)
                        elif os.path.isdir(child_source):
                            nested_target = os.path.join(target_path, child_entry)
                            if os.path.exists(nested_target):
                                continue
                            shutil.move(child_source, nested_target)
                    if not os.listdir(source_path):
                        os.rmdir(source_path)
                else:
                    shutil.move(source_path, target_path)
                logger.info(f"迁移归档目录到子目录: {target_path}")

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
        cache_path = os.path.join(self.archive_dir, "cache.json")
        if not os.path.exists(cache_path):
            return {}

        try:
            with open(cache_path, "r", encoding="utf-8") as cache_file:
                return json.load(cache_file)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"加载转录缓存失败: {exc}")
            return {}

    def save_transcription_cache(self, cache_data: dict) -> None:
        self.ensure_directory()
        cache_path = os.path.join(self.archive_dir, "cache.json")
        try:
            with open(cache_path, "w", encoding="utf-8") as cache_file:
                json.dump(cache_data, cache_file, ensure_ascii=False, indent=2)
            logger.info(f"转录缓存已保存: {cache_path}")
        except Exception as exc:  # noqa: BLE001
            logger.error(f"保存转录缓存失败: {exc}")

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
        cache = self.load_transcription_cache()
        cache[audio_filename] = {
            "transcription": transcription_result,
            "service": service,
            "model": model,
            "mode": mode,
            "timestamp": datetime.now().isoformat(),
        }
        self.save_transcription_cache(cache)
