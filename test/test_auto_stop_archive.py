"""录满最大时长自动停止时，录音要和手动停止一样存档、写缓存（2026-11-24 回归）。

以前自动停止走的是 abort，音频被丢弃，转录出来的字虽然打了出去，
audio_archive/audio/ 里没有 wav，cache.json 里也没有条目。
所有音频、键盘、界面依赖都用替身，不碰真麦克风和真热键。
"""

import importlib.util
import io
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def _load(module_name, relative_path, replacements):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, replacements):
        spec.loader.exec_module(module)
    return module


def _logger_module():
    logger_module = types.ModuleType("src.utils.logger")
    logger_module.logger = Mock()
    logger_module.flush_logs = Mock()
    return logger_module


def _input_state_module():
    return _load("src.keyboard.inputState", "src/keyboard/inputState.py", {})


def _load_listener(input_state_module):
    pynput = types.ModuleType("pynput")
    pynput_keyboard = types.ModuleType("pynput.keyboard")
    pynput_keyboard.Controller = Mock
    pynput_keyboard.Key = Mock()
    pynput_keyboard.Listener = type("Listener", (), {"_create_event_tap": lambda self: None})
    pynput.keyboard = pynput_keyboard
    package = types.ModuleType("src.keyboard")
    package.__path__ = [str(ROOT / "src/keyboard")]
    replacements = {
        "pynput": pynput,
        "pynput.keyboard": pynput_keyboard,
        "pyperclip": types.ModuleType("pyperclip"),
        "src.utils.logger": _logger_module(),
        "src.keyboard": package,
        "src.keyboard.inputState": input_state_module,
    }
    return _load("src.keyboard.listener", "src/keyboard/listener.py", replacements)


def _load_main(input_state_module, listener_module):
    def stub(name, **attrs):
        module = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        return module

    replacements = {
        "dotenv": stub("dotenv", load_dotenv=lambda *a, **k: None),
        "src.audio.recorder": stub("src.audio.recorder", AudioRecorder=Mock),
        "src.audio.archive": stub("src.audio.archive", AudioArchiveManager=Mock),
        "src.keyboard.listener": listener_module,
        "src.keyboard.inputState": input_state_module,
        "src.transcription.whisper": stub("src.transcription.whisper", WhisperProcessor=Mock),
        "src.utils.logger": _logger_module(),
        "src.transcription.local_whisper": stub("src.transcription.local_whisper", LocalWhisperProcessor=Mock),
        "src.transcription.doubao_streaming": stub("src.transcription.doubao_streaming", DoubaoStreamingProcessor=Mock),
        "src.ui.status_bar": stub("src.ui.status_bar", StatusBarController=Mock),
        "src.ui.floating_preview": stub("src.ui.floating_preview", FloatingPreviewWindow=Mock),
    }
    return _load("whisper_main_under_test", "main.py", replacements)


class AutoStopArchiveTests(unittest.TestCase):
    def setUp(self):
        self.InputState = _input_state_module().InputState
        input_state_module = types.ModuleType("src.keyboard.inputState")
        input_state_module.InputState = self.InputState
        self.listener = _load_listener(input_state_module)
        self.main = _load_main(input_state_module, self.listener)

    def make_assistant(self, *, ctrl_f="doubao"):
        """搭一个只有停止录音所需部件的 VoiceAssistant，热键状态机用真的。"""
        assistant = self.main.VoiceAssistant.__new__(self.main.VoiceAssistant)
        assistant.audio_recorder = Mock()
        assistant.audio_recorder.recording = True
        assistant.audio_recorder.stop_streaming_recording.return_value = io.BytesIO(b"RIFF-doubao")
        assistant.audio_recorder.stop_recording.return_value = io.BytesIO(b"RIFF-batch")
        assistant.audio_archive = Mock()
        assistant.audio_archive.save_audio_bytes.return_value = "/tmp/recording.wav"
        assistant.floating_preview = Mock()
        assistant.local_processor = Mock()
        assistant.max_auto_retries = 0
        assistant._streaming_thread = None
        assistant._current_streaming_archive_path = None
        assistant._queue_job = Mock()
        ctrl_f_stop = (assistant.stop_doubao_streaming if ctrl_f == "doubao"
                       else assistant.stop_openai_recording)
        keyboard = self.listener.KeyboardManager.__new__(self.listener.KeyboardManager)
        keyboard._state = self.InputState.IDLE
        keyboard.is_recording = False
        keyboard.last_key_time = 0
        keyboard.on_record_start = Mock()
        keyboard.on_local_start = Mock()
        keyboard.on_record_stop = ctrl_f_stop
        keyboard.on_local_stop = assistant.stop_local_recording
        assistant._current_state = self.InputState.IDLE
        # 和真程序一样，键盘状态变了就同步给主程序
        keyboard.on_state_change = lambda state: setattr(assistant, "_current_state", state)
        assistant.keyboard_manager = keyboard
        return assistant, keyboard

    def start(self, keyboard, state):
        keyboard.is_recording = True
        keyboard.state = state

    def test_doubao_auto_stop_archives_audio(self):
        assistant, keyboard = self.make_assistant(ctrl_f="doubao")
        self.start(keyboard, self.InputState.RECORDING)

        assistant._handle_auto_stop()

        assistant.audio_recorder.stop_streaming_recording.assert_called_once_with()
        assistant.audio_archive.save_audio_bytes.assert_called_once_with(b"RIFF-doubao")
        self.assertEqual(assistant._current_streaming_archive_path, "/tmp/recording.wav")
        self.assertFalse(keyboard.is_recording)

    def test_auto_stop_path_matches_manual_stop(self):
        manual, manual_keyboard = self.make_assistant(ctrl_f="doubao")
        self.start(manual_keyboard, self.InputState.RECORDING)
        manual_keyboard.is_recording = False
        manual_keyboard.state = self.InputState.PROCESSING  # 第二次按热键做的事

        auto, auto_keyboard = self.make_assistant(ctrl_f="doubao")
        self.start(auto_keyboard, self.InputState.RECORDING)
        auto._handle_auto_stop()

        self.assertEqual(manual.audio_recorder.mock_calls, auto.audio_recorder.mock_calls)
        self.assertEqual(manual.audio_archive.mock_calls, auto.audio_archive.mock_calls)
        self.assertEqual(manual_keyboard.state, auto_keyboard.state)

    def test_batch_auto_stop_archives_and_queues_transcription(self):
        assistant, keyboard = self.make_assistant(ctrl_f="openai")
        self.start(keyboard, self.InputState.RECORDING)

        assistant._handle_auto_stop()

        assistant.audio_archive.save_audio_bytes.assert_called_once_with(b"RIFF-batch")
        assistant._queue_job.assert_called_once()
        self.assertEqual(assistant._queue_job.call_args.kwargs["archive_path"], "/tmp/recording.wav")

    def test_local_auto_stop_archives_and_queues_transcription(self):
        assistant, keyboard = self.make_assistant()
        self.start(keyboard, self.InputState.RECORDING_LOCAL)

        assistant._handle_auto_stop()

        assistant.audio_archive.save_audio_bytes.assert_called_once_with(b"RIFF-batch")
        assistant._queue_job.assert_called_once_with(b"RIFF-batch", "local", archive_path="/tmp/recording.wav")

    def test_auto_stop_never_aborts(self):
        for ctrl_f, state in (("doubao", self.InputState.RECORDING),
                              ("openai", self.InputState.RECORDING),
                              ("doubao", self.InputState.RECORDING_LOCAL)):
            assistant, keyboard = self.make_assistant(ctrl_f=ctrl_f)
            self.start(keyboard, state)
            assistant._handle_auto_stop()
            for call in assistant.audio_recorder.method_calls:
                self.assertNotIn("abort", call.kwargs, f"{ctrl_f}/{state.name}: {call}")
            assistant.audio_recorder.reset_streaming_state.assert_not_called()

    def test_auto_stop_during_manual_stop_leaves_recorder_alone(self):
        assistant, keyboard = self.make_assistant()
        keyboard._state = self.InputState.PROCESSING  # 按键线程正在存档

        assistant._handle_auto_stop()

        assistant.audio_recorder.reset_streaming_state.assert_not_called()
        assistant.audio_recorder.stop_streaming_recording.assert_not_called()

    def test_device_disconnect_uses_same_path(self):
        assistant, keyboard = self.make_assistant(ctrl_f="doubao")
        self.start(keyboard, self.InputState.RECORDING)

        assistant._handle_device_disconnect()

        assistant.audio_archive.save_audio_bytes.assert_called_once_with(b"RIFF-doubao")
        self.assertFalse(keyboard.is_recording)


class MaxRecordDurationConfigTests(unittest.TestCase):
    def setUp(self):
        replacements = {
            "sounddevice": types.ModuleType("sounddevice"),
            "soundfile": types.ModuleType("soundfile"),
            "numpy": types.ModuleType("numpy"),
            "src.utils.logger": _logger_module(),
        }
        self.module = _load("src.audio._auto_stop_test", "src/audio/recorder.py", replacements)
        self.Recorder = self.module.AudioRecorder

    def read(self, value):
        env = {} if value is None else {"MAX_RECORD_MINUTES": value}
        with patch.dict(os.environ, env, clear=False):
            if value is None:
                os.environ.pop("MAX_RECORD_MINUTES", None)
            return self.Recorder._read_max_record_duration()

    def test_default_is_thirty_minutes(self):
        self.assertEqual(self.read(None), 30 * 60)

    def test_env_overrides(self):
        self.assertEqual(self.read("45"), 45 * 60)
        self.assertEqual(self.read("0.5"), 30)

    def test_invalid_values_fall_back_to_default(self):
        for bad in ("abc", "0", "-5"):
            self.assertEqual(self.read(bad), 30 * 60, bad)

    def test_auto_stop_without_callback_keeps_audio(self):
        recorder = self.Recorder.__new__(self.Recorder)
        recorder.max_record_duration = 600.0
        recorder.auto_stop_callback = None
        recorder.stop_recording = Mock()
        recorder._send_notification = Mock()

        recorder._auto_stop_recording()

        recorder.stop_recording.assert_called_once_with()
        recorder._send_notification.assert_called_once()


if __name__ == "__main__":
    unittest.main()
