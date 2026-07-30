# 转录缓存的数据安全（cache.json）

`audio_archive/cache.json` 存着每条录音的转写结果，是这个工具唯一的历史资产——音频还能重新转，缓存丢了就是真丢了。这份文档记录 2026-04-03 那次数据丢失的成因、现在的防线，以及万一再出事怎么抢救。

## 事故：2026-04-03 04:05，约 2900 条历史被清空

日志里只留下两行 `加载转录缓存失败: Expecting ',' delimiter: line 23337 column 339`，紧接着 cache.json 的第一条记录时间戳变成 `2026-04-03T04:05:22`——整份历史在同一秒内被一条新记录顶掉了。

根因是三个缺陷串成一条链，缺一环都不会丢数据：

| 环节 | 旧行为 | 后果 |
|------|--------|------|
| 写 | `open(w)` 直接覆写 5MB 的 cache.json | 写到一半进程被杀，磁盘上留下截断的坏 JSON |
| 读 | 解析失败 `except` → `return {}` | 「读不出来」被当成「本来就是空的」 |
| 存 | 拿这个空字典加一条新记录写回去 | 2900 条历史被一条新记录覆盖 |

第三个独立缺陷（同期修复）：`_migrate_legacy_archive_entries` 用黑名单迁移，把 `audio_archive/` 下任何不在白名单里的文件和目录无条件搬进 `audio/`。它吞掉过用户手动放的备份文件，也吞掉过**正在写入的** `transcribe/` 工作目录，把一次长音频转录任务的产物从中间劈成两半。

## 现在的四道防线（`src/audio/archive.py`）

1. **原子写**（`save_transcription_cache`）：写 `cache.json.<pid>.tmp` → `flush()` + `os.fsync()` → `os.replace()`。`os.replace` 在操作系统层面是原子的，所以 cache.json 要么是完整的旧版本，要么是完整的新版本，不存在中间态。被 `kill -9` 打断也只会留下一个 `.tmp` 垃圾文件，正式文件毫发无损。

2. **上一代备份**（`_snapshot_current_cache`）：替换前用**硬链接**把旧内容留成 `cache.json.bak`。硬链接只是多建一个目录项，不复制 5MB 数据，所以每次保存的开销可以忽略；替换后 cache.json 指向新 inode，`.bak` 仍指着旧 inode。

3. **读失败绝不返回空字典**（`load_transcription_cache`）——按失败性质分两类处理，这是整个修复的核心：

   | 失败类型 | 判断依据 | 处理 |
   |---------|---------|------|
   | 内容坏了 | `json.JSONDecodeError` / 顶层不是 dict | 改名成 `cache.json.corrupt-<时间戳>` 留证，再尝试用 `.bak` 恢复；恢复不了就从空的重新开始（原始数据仍在 `.corrupt` 文件里） |
   | 文件读不动 | `OSError`（权限、IO 错误，文件本身可能是好的） | 抛 `TranscriptionCacheError`，**既不改名也不覆盖**，本次保存直接中止 |

   代价是极端情况下丢一条新记录（文字照常输入到光标处，日志里也有），换 12000 条历史的安全。

4. **并发保护**：队列 worker（`main.py` 的 `_handle_job_result`）和流式回调（`emit_streaming_text`）分属两个线程，读-改-写用 `threading.Lock` 串行化；临时文件名带 pid，万一同时开了两个实例也不会互相踩对方写到一半的临时文件。

配套的 `_migrate_legacy_archive_entries` 改成白名单：**只搬音频扩展名的文件，目录一律不动**。黑名单永远列不全「不该搬的东西」，白名单才安全。

## 验证

```bash
python test/test_archive_cache_safety.py
```

32 项断言，其中两项是真刀真枪的：

- **写到一半被 SIGKILL**：子进程在 `json.dump` 遍历到第 300 条时给自己发 `SIGKILL`，然后断言 cache.json 逐字节等于写入前的完好旧版。同一个打断打在旧写法上会留下坏 JSON（测试里有这个对照组）。
- **20 线程并发写**：用 `threading.Barrier` 让 20 个线程同时冲进读-改-写，断言原有记录一条不丢、新记录一条不少。

## 排查速查

**看到 `audio_archive/cache.json.corrupt-<时间戳>`**——这不是故障，是缓存被写坏后系统替你留下的原件，历史记录都在里面。检查一下正式文件是否已从 `.bak` 恢复：

```bash
python -c "import json;print(len(json.load(open('audio_archive/cache.json'))))"
```

条数正常就没事，`.corrupt` 文件确认无用后可以删。条数异常少，就从 `.corrupt` 文件里人工抢救（它是纯文本，末尾截断，前面的记录都完好）。

**看到 `cache.json.<数字>.tmp` 残留**——说明某次保存被强制中断了。正式文件是安全的，这个文件可以直接删。

**日志里出现 `跳过本次缓存写入，避免覆盖历史记录`**——文件读不动（多半是权限），历史是安全的，但新记录没进缓存。修好权限即可：

```bash
chmod 644 audio_archive/cache.json
```

## 万一还是丢了：从运行日志抢救

2026-04-03 丢的那批里有 1011 条是从日志重建的（缓存里带 `recovered_from_log: true` 标记）。原理是日志里这两行紧挨着出现，配对即可重建一条记录：

```
INFO - 音频文件已保存到存档: audio_archive/audio/recording_20260730_194326.wav
INFO - [最终输入:final] 把这些新的学问都记录到 Docs 里面。
```

前一行给出缓存的 key（音频文件名），后一行给出转写文本。按时间顺序扫 `logs/*.log`，遇到「保存到存档」记下文件名，遇到紧随其后的「最终输入」就配成一条记录，再和现有 cache.json 合并（**只补不覆盖**，已有的 key 一律跳过）。

局限：只能救回日志覆盖到的时间段，且非流式路径（`✅ 转录成功`）的文本不一定在日志里，所以抢救率不会是 100%。事故前的原始备份留在 `logs/cache.json.backup-20260730-before-log-recovery`。

## 改这块代码时

核心不变量只有一条：**任何路径都不许把「读不出来」变成一个空字典交给上层去覆盖。**

看着啰嗦的那几层都是拿丢数据换来的，别当冗余代码精简掉。动完跑一遍 `test/test_archive_cache_safety.py`。
