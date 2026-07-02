# 录音快捷键光标位移修复（Ctrl+F / Ctrl+I 事件拦截）

## 背景

- 本项目用 `Ctrl+F`（默认转录）/ `Ctrl+I`（默认本地 Whisper）作为"按一下开始、再按一下停止"的录音开关。
- 但在 macOS 上，`Ctrl+F` / `Ctrl+I` 本身是系统级的 emacs 风格文本键位：
  - `Ctrl+F` = 光标右移一个字符（forward-char）
  - `Ctrl+I` = 插入 Tab
- 结果：每次按快捷键切换录音时，前台应用（终端、输入框、Cursor/VSCode 等）都会**额外把光标往右挪一格**。用户明明把光标定位在句子中间，一按录音光标就偏了，导致**无法精确地把转录结果插入到文本中间**，做精细编辑时很难受。
- 用户不想更换已经用习惯的快捷键，因此需要在**保留 `Ctrl+F` 的前提下**消除这个副作用。

## 根因

监听器此前只是被动监听按键、没有做任何拦截：

```python
with Listener(on_press=self.on_press, on_release=self.on_release) as listener:
    listener.join()
```

按键事件在触发我们的录音逻辑的同时，**仍然被透传给了前台应用**，于是应用按自己的键位把 `Ctrl+F` 当成"光标右移"执行了一次。

## 解决方案

利用 macOS 官方的 **Quartz Event Tap** 机制（pynput 通过 `pyobjc-framework-Quartz` 暴露）在事件送达前台应用**之前**拦截并吞掉这两个组合键。

### 1. 事件拦截（吞掉组合键）

给 `Listener` 传入 `darwin_intercept` 回调。pynput 的内部顺序是：**先触发 `on_press` / `on_release`（我们的录音开关照常工作），再调用 `darwin_intercept` 决定该事件是否放行**。

- 命中"录音键 + 修饰键"（默认 `f`/`i` + `Ctrl`）→ 返回 `None`，事件被丢弃，前台应用永远收不到，光标不动。
- 其它所有按键 → 原样 `return event` 放行。

```python
def _darwin_intercept(self, event_type, event):
    vk = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
    if vk in self._suppress_vks:
        flags = CGEventGetFlags(event)
        if flags & self._suppress_modifier_mask:
            return None  # 吞掉，不透传给前台 app
    return event
```

### 2. 拦截目标跟随 `.env` 配置动态计算（通用，不写死）

拦截的虚拟键码来自 `Controller._mapping`（unicode 字符 → 虚拟键码，随键盘布局），修饰键掩码来自一张 `Key → CGEventFlagMask` 映射表。因此：

- `TRANSCRIPTIONS_BUTTON` 改成任意键（`b`、`j`、`f1`…）、`TRANSLATIONS_BUTTON` 改成任意修饰键（`ctrl`/`cmd`/`alt`/`shift`），拦截会**自动切换到对应键码与修饰键**，用户无需改代码。
- 实测：`f+ctrl → [3,34]/Control`、`b+ctrl → [11,34]/Control`、`j+cmd → [34,38]/Command`、`f1+alt → [34,122]/Alt`（其中 `34` 是本地 Whisper 模式固定的 `i` 键）。

### 3. 把录音启停挪到后台线程，避免事件 tap 被超时禁用

一旦提供 `darwin_intercept`，事件 tap 会从"只监听"变成"可修改/可拦截"的 active 模式，此时 **macOS 要求回调必须快速返回**——否则会触发看门狗（`kCGEventTapDisabledByTimeout`）自动禁用该 tap，表现为"快捷键突然没反应、录音不触发"。

因此把状态切换（会同步触发启动/停止录音等较重的逻辑）从键盘事件回调线程挪到后台线程，保证回调秒回：

```python
def _set_state_async(self, new_state):
    threading.Thread(
        target=lambda: setattr(self, "state", new_state),
        name="state-change",
        daemon=True,
    ).start()
```

## 为什么系统允许一个程序吞掉键盘事件？

这不是"绕过系统"，而是苹果提供的受监管钩子，有三重保护：

1. **辅助功能权限（Accessibility / TCC）**：创建可修改/拦截事件的 active tap 必须由用户在「系统设置 → 隐私与安全性 → 辅助功能」手动授权，逐 app、可见、可撤销。
2. **超时看门狗**：回调太慢会被系统自动禁用 tap，键盘立即恢复正常——你无法靠它把系统卡死（这也正是方案第 3 点要规避的）。
3. **安全输入的天花板**：密码框、锁屏等 `EnableSecureEventInput` 场景会完全绕过所有 event tap，无法被拦截。

## 影响范围与取舍

- 仅在 macOS（`sys.platform == "darwin"`）启用；其它平台行为不变。
- app 运行期间，配置的录音组合键在**全系统**都会被吞掉（不再有原生的"光标右移 / Tab"行为）——因为这两个组合键已被专门用作录音开关，这正是期望行为。
- 启动日志会打印：`✅ 已启用组合键事件拦截 (vk=[...])`。

## 涉及文件

- `src/keyboard/listener.py`
  - 新增 `_build_hotkey_suppression()`：根据配置计算要拦截的键码集合与修饰键掩码。
  - 新增 `_darwin_intercept()`：命中组合键返回 `None` 吞掉，其余放行。
  - 新增 `_set_state_async()`：状态切换挪到后台线程，避免 tap 超时被禁用。
  - `start_listening()`：macOS 下给 `Listener` 传入 `darwin_intercept`。
