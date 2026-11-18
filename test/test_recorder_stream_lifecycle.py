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

    # ---- CoreAudio 卡死检测：卡死后要上报，让主程序重启进程 ----

    def prepare_for_capture(self, timeout=0.2):
        """补齐 __new__ 跳过的属性，让 _start_capture 能跑。"""
        self.module.AudioRecorder.STREAM_OP_TIMEOUT = timeout
        recorder = self.recorder
        recorder.recording = False
        recorder.stream = None
        # 用被测模块自己的 queue：patch.dict 退出时会移除加载期间新导入的模块，
        # 测试里再 import 会得到另一份 queue，它的 Empty 和被测代码捕获的不是同一个类
        recorder.audio_queue = self.module.queue.Queue()
        recorder._recorded_chunks = []
        recorder.record_start_time = None
        recorder.max_record_duration = 600.0
        recorder.auto_stop_timer = None
        recorder._recording_lock = threading.RLock()
        recorder._device_error_detected = False
        recorder._last_used_device = "MacBook Pro Microphone"
        recorder.current_device = None
        recorder.sample_rate = 48000
        recorder.wedged_reason = None
        recorder.wedged_callback = Mock()
        recorder._send_notification = Mock()
        return recorder

    def test_stop_hang_beyond_timeout_reports_wedged(self):
        recorder = self.prepare_for_capture()
        stream = self.stream(block_stop=True)
        recorder._close_stream_async(stream)
        self.assertTrue(stream.stop_entered.wait(1))
        deadline = threading.Event()
        for _ in range(50):
            if recorder.wedged_callback.called:
                break
            deadline.wait(0.02)
        recorder.wedged_callback.assert_called_once()
        self.assertIn("stream.stop()", recorder.wedged_reason)

    def test_open_hang_raises_and_reports_wedged(self):
        recorder = self.prepare_for_capture()
        release_open = threading.Event()
        self.addCleanup(release_open.set)

        def hanging_input_stream(**kwargs):
            release_open.wait(3)
            raise RuntimeError("released")

        self.sd.InputStream = hanging_input_stream
        error = recorder.start_streaming_recording()
        self.assertIsNotNone(error)
        self.assertIn("开启音频流", error)
        self.assertFalse(recorder.recording)
        self.assertIsNone(recorder.stream)
        recorder.wedged_callback.assert_called_once()

    def test_start_refuses_immediately_after_wedged(self):
        recorder = self.prepare_for_capture()
        recorder.wedged_reason = "stream.stop() 5s 未返回"
        self.sd.InputStream = Mock(side_effect=AssertionError("must not open"))
        error = recorder.start_streaming_recording()
        self.assertIn("等待进程自动重启", error)
        self.assertFalse(recorder.recording)
        with self.assertRaises(self.module.AudioSystemWedged):
            recorder.start_recording()

    def test_successful_open_sets_stream_and_recording(self):
        recorder = self.prepare_for_capture()
        opened = Mock()
        self.sd.InputStream = Mock(return_value=opened)
        self.assertIsNone(recorder.start_streaming_recording())
        opened.start.assert_called_once_with()
        self.assertIs(recorder.stream, opened)
        self.assertTrue(recorder.recording)
        recorder.auto_stop_timer.cancel()
        recorder.wedged_callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
