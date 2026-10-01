"""关流与设备刷新的并发回归测试；所有音频依赖均为替身。"""

import importlib.util
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch


class FakeStream:
    def __init__(self, *, block_stop=False, block_close=False, close_error=False):
        self.stop_entered = threading.Event()
        self.close_entered = threading.Event()
        self.release_stop = threading.Event()
        self.release_close = threading.Event()
        self.close_error = close_error
        if not block_stop:
            self.release_stop.set()
        if not block_close:
            self.release_close.set()

    def stop(self):
        self.stop_entered.set()
        if not self.release_stop.wait(3):
            raise RuntimeError("test did not release stop")

    def close(self):
        self.close_entered.set()
        if not self.release_close.wait(3):
            raise RuntimeError("test did not release close")
        if self.close_error:
            raise RuntimeError("simulated close failure")


class ObservedLock:
    """让测试知道另一个线程已经尝试获取锁，避免靠 sleep 猜测调度。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.contended = threading.Event()

    def __enter__(self):
        if not self.lock.acquire(blocking=False):
            self.contended.set()
            self.lock.acquire()
        return self

    def __exit__(self, *args):
        self.lock.release()


class RecorderStreamLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.sd = types.ModuleType("sounddevice")
        self.sd._terminate = Mock()
        self.sd._initialize = Mock()
        self.sd.query_devices = Mock(return_value=[{
            "name": "MacBook Pro Microphone", "max_input_channels": 1,
            "default_samplerate": 48000,
        }])
        logger_module = types.ModuleType("src.utils.logger")
        logger_module.logger = Mock()
        replacements = {
            "sounddevice": self.sd,
            "soundfile": types.ModuleType("soundfile"),
            "numpy": types.ModuleType("numpy"),
            "src.utils.logger": logger_module,
        }
        source = Path(__file__).resolve().parents[1] / "src/audio/recorder.py"
        spec = importlib.util.spec_from_file_location("src.audio._lifecycle_test", source)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, replacements):
            spec.loader.exec_module(self.module)
        self.logger = logger_module.logger
        self.recorder = self.module.AudioRecorder.__new__(self.module.AudioRecorder)
        self.streams = []
        self.threads = []
        self.before_thread_start = None
        owner = self

        class TrackedThread(threading.Thread):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                owner.threads.append(self)

            def start(self):
                if owner.before_thread_start:
                    owner.before_thread_start(self)
                super().start()

        # 仅替换被测模块使用的 Thread；测试自己的协调线程保持不变。
        self.module.threading = types.SimpleNamespace(
            **{name: getattr(threading, name) for name in dir(threading)
               if name != "Thread"}, Thread=TrackedThread,
        )
        self.addCleanup(self.release_and_join)

    def release_and_join(self):
        for stream in self.streams:
            stream.release_stop.set()
            stream.release_close.set()
        # 外层线程可能在清理开始后才创建内层线程。
        for thread in self.threads:
            if thread.ident is not None:
                thread.join(3)
                self.assertFalse(thread.is_alive(), "test left a closer running")

    def stream(self, **kwargs):
        stream = FakeStream(**kwargs)
        self.streams.append(stream)
        return stream

    def refresh(self):
        index, device = self.recorder._get_best_input_device()
        self.assertEqual(index, 0)
        self.assertEqual(device["name"], "MacBook Pro Microphone")

    def assert_refresh_skipped(self):
        self.refresh()
        self.sd._terminate.assert_not_called()
        self.sd._initialize.assert_not_called()

    def test_stop_wait_is_protected_before_five_second_timeout(self):
        stream = self.stream(block_stop=True)
        self.recorder._close_stream_async(stream)
        self.assertTrue(stream.stop_entered.wait(1))
        self.assert_refresh_skipped()
        self.assertFalse(stream.close_entered.is_set())

    def test_close_wait_remains_protected_after_stop_returns(self):
        stream = self.stream(block_close=True)
        self.recorder._close_stream_async(stream)
        self.assertTrue(stream.close_entered.wait(1))
        self.assert_refresh_skipped()

    def test_successful_close_restores_refresh(self):
        stream = self.stream(block_close=True)
        self.recorder._close_stream_async(stream)
        self.assertTrue(stream.close_entered.wait(1))
        self.assert_refresh_skipped()
        stream.release_close.set()
        self.release_and_join()
        self.refresh()
        self.sd._terminate.assert_called_once_with()
        self.sd._initialize.assert_called_once_with()

    def test_all_closures_must_finish_before_refresh_resumes(self):
        first = self.stream(block_close=True)
        second = self.stream(block_close=True)
        self.recorder._close_stream_async(first)
        self.recorder._close_stream_async(second)
        self.assertTrue(first.close_entered.wait(1))
        self.assertTrue(second.close_entered.wait(1))
        first.release_close.set()
        # 首个线程必须已退出；第二个仍然停在 close 中。
        closers = [t for t in self.threads if t.name == "pa-close"]
        closers[0].join(1)
        self.assertFalse(closers[0].is_alive())
        self.assert_refresh_skipped()
        second.release_close.set()
        self.release_and_join()
        self.refresh()
        self.sd._terminate.assert_called_once_with()

    def test_close_failure_keeps_refresh_disabled_and_logs_warning(self):
        stream = self.stream(close_error=True)
        self.recorder._close_stream_async(stream)
        self.release_and_join()
        self.assertTrue(stream.close_entered.is_set())
        self.assert_refresh_skipped()
        self.assertTrue(self.logger.warning.called)

    def test_closure_is_registered_before_worker_is_dispatched(self):
        stream = self.stream()
        checked = []

        def before_start(thread):
            if thread.name == "pa-close":
                self.assert_refresh_skipped()
                checked.append(True)

        self.before_thread_start = before_start
        self.recorder._close_stream_async(stream)
        self.assertEqual(checked, [True])

    def test_refresh_and_closure_registration_are_serialized(self):
        lock = ObservedLock()
        self.module.AudioRecorder._stream_lifecycle_lock = lock
        terminate_entered = threading.Event()
        release_refresh = threading.Event()
        refreshed = threading.Event()
        stream = self.stream(block_stop=True)

        def terminate():
            terminate_entered.set()
            if not release_refresh.wait(3):
                raise RuntimeError("test did not release refresh")

        def refresh_worker():
            self.recorder._get_best_input_device()
            refreshed.set()

        self.sd._terminate.side_effect = terminate
        refresher = threading.Thread(target=refresh_worker, daemon=True)
        dispatcher = threading.Thread(
            target=self.recorder._close_stream_async, args=(stream,), daemon=True,
        )
        try:
            refresher.start()
            self.assertTrue(terminate_entered.wait(1))
            dispatcher.start()
            self.assertTrue(lock.contended.wait(1), "registration bypassed refresh lock")
            self.assertFalse(stream.stop_entered.is_set())
        finally:
            release_refresh.set()
            refresher.join(3)
            if dispatcher.ident is not None:
                dispatcher.join(3)
        self.assertTrue(refreshed.is_set())
        self.assertFalse(refresher.is_alive())
        self.assertFalse(dispatcher.is_alive())
        self.assertTrue(stream.stop_entered.wait(1))
        self.sd._terminate.reset_mock()
        self.sd._initialize.reset_mock()
        self.assert_refresh_skipped()


if __name__ == "__main__":
    unittest.main()
