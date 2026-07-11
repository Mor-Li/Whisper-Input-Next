# 热键突然失灵的自愈机制（v3.3.1）

## 症状

两种表现完全一样（按 Ctrl+F 无反应、按键透传给前台 app——终端里能看到 `^F`、程序零日志），但根因和恢复方式不同：

| 失效模式 | 触发原因 | 恢复方式（修复前） |
|---------|---------|------------------|
| event tap 被系统禁用 | 键盘回调响应超时，macOS 发 `kCGEventTapDisabledByTimeout` 并禁掉 tap；pynput 1.7.7 只在启动时启用一次 tap，从不重新启用 | **只能重启进程** |
| Secure Input 被占用 | 其它进程开启安全键盘输入（终端的"安全键盘输入"选项、sudo 密码、浏览器密码框、锁屏残留），期间所有 event tap 收不到键盘事件 | 对方释放后自动恢复（看起来像"自己好了"） |

第一种的典型触发场景：**录音收尾的瞬间**（音频流 flush、豆包 WebSocket 收尾、粘贴文本都在抢 GIL）恰好快速连按热键，一串事件在回调里排队，任何一个超时整个 tap 就被禁——表现为"结束时按快了就卡死，从此没反应"。

## 修复（三层）

1. **就地自愈**（`listener.py` `_darwin_intercept`）：macOS 禁用 tap 前会给回调发一个通知事件；在 intercept 里接住它，立即 `CGEventTapEnable(tap, True)`，毫秒级复活。tap 引用由 `_TapCapturingListener`（覆盖 `_create_event_tap`）捕获——pynput 原生把 tap 存在局部变量里拿不到。
2. **watchdog 兜底**（`listener.py` `_start_tap_watchdog`）：后台线程每 5 秒检查 `CGEventTapIsEnabled`，被禁就复活（覆盖通知丢失、或没启用组合键拦截的 listen-only 场景）；同时监控 `kCGSSessionSecureInputPID`，Secure Input 被占/释放时在日志里点名进程——以后再失灵，看日志即知原因。
3. **日志异步化**（`logger.py`）：logger 改走 `QueueHandler`/`QueueListener`。此前 `logger.info` 直接写 stdout，`python main.py | tee` 的管道一卡（终端冻结、流控）就阻塞键盘回调，正是回调超时的一大来源。现在回调线程里的日志只入队（纯内存），写终端/文件由独立线程完成。

## 验证

模拟测试（手动 `CGEventTapEnable(tap, False)`）：

- 挂着 intercept 时：禁用后毫秒级被就地复活（日志 `⚠️ 键盘事件 tap 被系统禁用（回调超时），已自动重新启用`）；
- 摘掉 intercept 时：5 秒内被 watchdog 复活（日志 `⚠️ 键盘事件 tap 处于禁用状态，watchdog 已重新启用`）。

## 排查速查

热键失灵时先看日志：

- 有 `tap 被系统禁用` → 回调超时，已自动恢复，无需操作；
- 有 `进程 xxx 开启了 Secure Input` → 去关掉对应来源（iTerm2/Terminal 菜单里的 Secure Keyboard Entry / 安全键盘输入；锁屏残留就重新锁屏解锁一次）；
- 手动查占用：`ioreg -l -w 0 | grep -o '"kCGSSessionSecureInputPID"=[0-9]*'`
