"""转录缓存数据安全的回归测试。

对应 2026-04-03 那次事故：cache.json 被写坏后，程序把它当空缓存重写，丢了约 2900 条历史。
除第 4 项外全部在临时目录里跑，不碰真实数据；第 4 项只读真实 cache.json 的副本。

  1. 写入中途被 SIGKILL —— cache.json 仍是完好的旧版本
  2. cache.json 内容损坏 —— 不被清空，损坏文件改名保留（有/无备份、读不动三种情况）
  3. audio_archive/ 里的旁置文件（备份、笔记等）—— 跑一次转录后原地不动
  4. 真实 cache.json 走一遍完整读写 —— 一条不少

跑法：python test/test_archive_cache_safety.py
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_CACHE = os.path.join(REPO, "audio_archive", "cache.json")

sys.path.insert(0, REPO)
from src.audio.archive import AudioArchiveManager, TranscriptionCacheError  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'✅' if ok else '❌'} {name}" + (f"  —— {detail}" if detail else ""))


def make_cache(n, tag="old"):
    return {
        f"recording_2026{i:04d}.wav": {
            "transcription": f"{tag} 第 {i} 条转录内容，" + "填充" * 20,
            "service": "doubao",
            "model": "bigmodel",
            "mode": "transcriptions",
            "timestamp": f"2026-04-03T04:{i % 60:02d}:00",
        }
        for i in range(n)
    }


# ---------------------------------------------------------------- 1. 写入中断
# 子进程：正常写入 500 条，但 json.dump 遍历到第 300 条时给自己发 SIGKILL。
# 这时文件缓冲区已经把前面的内容刷到磁盘，剩下的永远写不出来 —— 完整复现事故。
KILL_CHILD = r'''
import json, os, signal, sys
sys.path.insert(0, {worktree!r})
from src.audio.archive import AudioArchiveManager

class KillingDict(dict):
    """json 的纯 Python 编码器（indent 非 None 时启用）会调用 items()，在这里自爆。"""
    def items(self):
        for i, kv in enumerate(super().items()):
            if i == 300:
                sys.stdout.flush()
                os.kill(os.getpid(), signal.SIGKILL)
            yield kv

data = KillingDict(json.load(open({payload!r})))
mgr = AudioArchiveManager({archive!r})
mgr.save_transcription_cache(data)
print("NOT_KILLED")
'''


def test_kill_during_write():
    print("\n[1] 写入中途被 SIGKILL")
    with tempfile.TemporaryDirectory() as tmp:
        archive = os.path.join(tmp, "audio_archive")
        mgr = AudioArchiveManager(archive)

        old = make_cache(500, "old")
        mgr.save_transcription_cache(old)
        before = open(mgr.cache_path, "rb").read()

        payload = os.path.join(tmp, "payload.json")
        json.dump(make_cache(500, "new"), open(payload, "w"), ensure_ascii=False)

        proc = subprocess.run(
            [sys.executable, "-c", KILL_CHILD.format(
                worktree=REPO, payload=payload, archive=archive)],
            capture_output=True, text=True, timeout=60,
        )
        check("子进程确实被 SIGKILL 杀死（不是正常退出）",
              proc.returncode == -signal.SIGKILL and "NOT_KILLED" not in proc.stdout,
              f"returncode={proc.returncode}")

        after = open(mgr.cache_path, "rb").read()
        try:
            parsed = json.loads(after)
            parse_ok, n = True, len(parsed)
        except json.JSONDecodeError as exc:
            parse_ok, n = False, str(exc)

        check("cache.json 仍能正常解析", parse_ok, f"{n} 条" if parse_ok else str(n))
        check("cache.json 内容与写入前逐字节一致（是完好旧版，不是半截文件）",
              after == before, f"{len(before)} → {len(after)} 字节")

        tmps = [f for f in os.listdir(archive) if f.endswith(".tmp")]
        if tmps:
            half = open(os.path.join(archive, tmps[0]), "rb").read()
            truncated = False
            try:
                json.loads(half)
            except json.JSONDecodeError:
                truncated = True
            check("半截数据被隔离在临时文件里（证明写入确实被打断了）",
                  truncated, f"{tmps[0]} 共 {len(half)} 字节，无法解析")
        else:
            check("半截数据被隔离在临时文件里（证明写入确实被打断了）",
                  False, "没有留下 .tmp，可能没真正打断到写入阶段")

        # 反证：同样的打断打到旧实现上，cache.json 会被写成半截
        legacy = os.path.join(tmp, "legacy.json")
        shutil.copy(mgr.cache_path, legacy)
        with open(legacy, "w", encoding="utf-8") as f:  # 旧代码：直接覆写目标文件
            try:
                json.dump(make_cache(500, "new"), f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        os.truncate(legacy, 40000)  # 模拟缓冲区没刷完就没了
        legacy_broken = False
        try:
            json.load(open(legacy))
        except json.JSONDecodeError:
            legacy_broken = True
        check("对照：旧的直接覆写方式在同样场景下会留下坏 JSON", legacy_broken)


# ---------------------------------------------------------------- 2. 内容损坏
def test_corrupt_cache_with_backup():
    print("\n[2a] cache.json 损坏 + 有上一代备份")
    with tempfile.TemporaryDirectory() as tmp:
        archive = os.path.join(tmp, "audio_archive")
        mgr = AudioArchiveManager(archive)

        mgr.save_transcription_cache(make_cache(300))
        mgr.save_transcription_cache(make_cache(301))  # 第二次保存后才有 .bak
        check("保存两次后生成了 cache.json.bak", os.path.exists(mgr.backup_path))

        good = open(mgr.cache_path, "rb").read()
        os.truncate(mgr.cache_path, len(good) // 2)  # 复现事故：JSON 被截断
        broken = open(mgr.cache_path, "rb").read()

        mgr.save_transcription_result("/x/新录音.wav", "刚说完的话",
                                      service="doubao", model="bigmodel")

        corrupt_files = [f for f in os.listdir(archive) if ".corrupt-" in f]
        check("损坏文件被改名保留（cache.json.corrupt-*）", len(corrupt_files) == 1,
              corrupt_files[0] if corrupt_files else "没找到")
        if corrupt_files:
            kept = open(os.path.join(archive, corrupt_files[0]), "rb").read()
            check("保留下来的就是那份损坏数据，一字节没动", kept == broken,
                  f"{len(kept)} 字节")

        now = json.load(open(mgr.cache_path))
        check("cache.json 没被清空，历史记录从备份恢复", len(now) >= 300,
              f"恢复出 {len(now)} 条")
        check("新的这条转录也写进去了", "新录音.wav" in now)


def test_corrupt_cache_without_backup():
    print("\n[2b] cache.json 损坏 + 没有任何备份（最坏情况）")
    with tempfile.TemporaryDirectory() as tmp:
        archive = os.path.join(tmp, "audio_archive")
        mgr = AudioArchiveManager(archive)
        mgr.save_transcription_cache(make_cache(300))
        os.remove(mgr.backup_path) if os.path.exists(mgr.backup_path) else None

        good = open(mgr.cache_path, "rb").read()
        os.truncate(mgr.cache_path, len(good) // 2)
        broken = open(mgr.cache_path, "rb").read()

        mgr.save_transcription_result("/x/新录音.wav", "刚说完的话",
                                      service="doubao", model="bigmodel")

        corrupt_files = [f for f in os.listdir(archive) if ".corrupt-" in f]
        check("没有备份时，损坏数据同样被改名保留下来", len(corrupt_files) == 1,
              corrupt_files[0] if corrupt_files else "没找到")
        if corrupt_files:
            kept = open(os.path.join(archive, corrupt_files[0]), "rb").read()
            check("原始损坏字节完整可用于事后人工抢救", kept == broken,
                  f"{len(kept)} 字节，仍含 {kept.decode('utf-8','ignore').count('transcription')} 处 transcription")


def test_unreadable_cache_aborts_save():
    print("\n[2c] cache.json 读不动（权限问题）—— 必须中止保存，不许改名不许覆盖")
    with tempfile.TemporaryDirectory() as tmp:
        archive = os.path.join(tmp, "audio_archive")
        mgr = AudioArchiveManager(archive)
        mgr.save_transcription_cache(make_cache(300))
        before = open(mgr.cache_path, "rb").read()

        os.chmod(mgr.cache_path, 0o000)
        try:
            raised = False
            try:
                mgr.load_transcription_cache()
            except TranscriptionCacheError:
                raised = True
            check("load 抛出 TranscriptionCacheError（而不是返回空字典）", raised)

            mgr.save_transcription_result("/x/新录音.wav", "刚说完的话",
                                          service="doubao", model="bigmodel")
        finally:
            os.chmod(mgr.cache_path, 0o644)

        check("cache.json 原封不动", open(mgr.cache_path, "rb").read() == before)
        check("没有误把好文件当成损坏文件改名",
              [f for f in os.listdir(archive) if ".corrupt-" in f] == [])


# ---------------------------------------------------------------- 3. 旁边的文件
def test_sidecar_files_not_swallowed():
    print("\n[3] audio_archive/ 里的其它文件不能被搬走")
    with tempfile.TemporaryDirectory() as tmp:
        archive = os.path.join(tmp, "audio_archive")
        os.makedirs(archive)

        sidecars = ["test.backup", "cache.json.backup-20260730-before-log-recovery",
                    "my_notes.md", "cache.json.corrupt-20260403-040522", "手动备份.json"]
        for name in sidecars:
            open(os.path.join(archive, name), "w").write("重要数据")
        os.makedirs(os.path.join(archive, "我的备份目录"))
        open(os.path.join(archive, "我的备份目录/x.txt"), "w").write("重要数据")
        open(os.path.join(archive, "legacy_recording.wav"), "wb").write(b"RIFF....")

        mgr = AudioArchiveManager(archive)
        mgr.save_transcription_result("/x/新录音.wav", "刚说完的话",
                                      service="doubao", model="bigmodel")

        for name in sidecars:
            check(f"{name} 原地未动", os.path.exists(os.path.join(archive, name)))
        check("我的备份目录/ 原地未动",
              os.path.exists(os.path.join(archive, "我的备份目录/x.txt")))
        check("audio/ 子目录没有多出任何非音频文件",
              [f for f in os.listdir(mgr.audio_dir)
               if not f.lower().endswith(".wav")] == [])
        check("真正的历史录音 legacy_recording.wav 仍会被正常迁移进 audio/",
              os.path.exists(os.path.join(mgr.audio_dir, "legacy_recording.wav"))
              and not os.path.exists(os.path.join(archive, "legacy_recording.wav")))


# ---------------------------------------------------------------- 4. 真实数据
def test_real_cache_intact():
    print("\n[4] 真实 cache.json 走一遍完整读写（在副本上跑，不碰原文件）")
    if not os.path.exists(REAL_CACHE):
        print("  ⏭  本机没有 audio_archive/cache.json，跳过")
        return

    # 应用在跑时条数会随实时录音增长，所以只断言「不少于抢救后的 11,919 条」
    real = json.load(open(REAL_CACHE))
    recovered = [k for k, v in real.items() if v.get("recovered_from_log")]
    check("原始 cache.json 可正常解析", True, f"{len(real)} 条")
    check("总条数不少于抢救后的 11,919 条", len(real) >= 11919,
          f"实际 {len(real)}（多出的是运行中新录的）")
    check("recovered_from_log 标记 1,011 条", len(recovered) == 1011,
          f"实际 {len(recovered)}")

    with tempfile.TemporaryDirectory() as tmp:
        archive = os.path.join(tmp, "audio_archive")
        os.makedirs(os.path.join(archive, "audio"))
        shutil.copy(REAL_CACHE, os.path.join(archive, "cache.json"))

        mgr = AudioArchiveManager(archive)
        mgr.save_transcription_result("/x/recording_20260731_000000.wav", "新的一条",
                                      service="doubao", model="bigmodel")

        after = json.load(open(mgr.cache_path))
        check("跑完一次真实转录写入后，只多了 1 条", len(after) == len(real) + 1,
              f"{len(real)} → {len(after)}")
        check(f"{len(real):,} 条老记录逐条内容完全一致",
              all(after.get(k) == v for k, v in real.items()))
        check("1,011 条 recovered_from_log 标记全部保留",
              len([k for k, v in after.items() if v.get("recovered_from_log")]) == 1011)


def test_concurrent_writes():
    print("\n[5] 两个线程同时写缓存 —— 不许丢记录，不许写坏")
    import threading

    with tempfile.TemporaryDirectory() as tmp:
        archive = os.path.join(tmp, "audio_archive")
        mgr = AudioArchiveManager(archive)
        mgr.save_transcription_cache(make_cache(200))

        barrier = threading.Barrier(20)

        def writer(i):
            barrier.wait()  # 让 20 个线程尽量同时冲进读-改-写
            mgr.save_transcription_result(f"/x/并发_{i}.wav", f"第 {i} 个线程说的话",
                                          service="doubao", model="bigmodel")

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final = json.load(open(mgr.cache_path))
        check("cache.json 仍是合法 JSON", True, f"{len(final)} 条")
        check("200 条原有记录一条没丢", all(f"recording_2026{i:04d}.wav" in final
                                              for i in range(200)))
        missing = [i for i in range(20) if f"并发_{i}.wav" not in final]
        check("20 个线程写的记录一条不少（读-改-写被正确串行化）", not missing,
              f"缺失 {missing}" if missing else "20/20")


for fn in (test_kill_during_write, test_concurrent_writes, test_corrupt_cache_with_backup,
           test_corrupt_cache_without_backup, test_unreadable_cache_aborts_save,
           test_sidecar_files_not_swallowed, test_real_cache_intact):
    fn()

print(f"\n{'='*60}\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
for name in FAIL:
    print(f"  ❌ {name}")
sys.exit(1 if FAIL else 0)
