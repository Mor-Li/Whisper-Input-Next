#!/usr/bin/env python3
"""
Audio transcription with speaker diarization using Doubao file-recognition API
(火山引擎大模型录音文件识别, resource volc.bigasr.auc). Unlike the streaming
scripts, this submits the whole file in one job and returns per-utterance
speaker labels — use it when the user wants 说话人分离.

Usage:
  python test/transcribe_audio_doubao_speaker.py <audio_file> [options]

Options:
  -o, --output PATH       Output transcript path
                          (default: <audio_dir>/<stem>_豆包录音文件识别_说话人分离.txt)
  --raw-json PATH         Raw API response path
                          (default: <audio_dir>/<stem>_豆包录音文件识别_speaker_raw.json)
  --poll-interval N       Seconds between query polls (default: 15)
  --timeout N             Max seconds to wait for the job (default: 2400)

Output format (matches Part5/Part8 交涉对话 archives):
  [MM:SS-MM:SS] 说话人N：合并后的同说话人连续文本

Notes:
  - Any ffmpeg-decodable input works (.m4a/.mp3/.wav/.qta/.mov/...); the script
    transcodes to 16kHz mono 48kbps mp3 (first audio stream only) before upload,
    so multi-track containers and large files are fine. Tested: 46min qta → OK.
  - Audio is uploaded as base64 in the request body. The job id (request_id) is
    written to a sidecar file next to the output before polling and removed on
    success, so an interrupted run can still be recovered manually via query.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]

SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
STATUS_OK = "20000000"
STATUS_PROCESSING = ("20000001", "20000002")


def load_environment() -> None:
    """Load .env first, then fill missing Doubao vars from ~/.zshrc."""
    load_dotenv(ROOT_DIR / ".env")

    missing = [
        key
        for key in ("DOUBAO_APP_KEY", "DOUBAO_ACCESS_KEY")
        if not os.getenv(key)
    ]
    if not missing:
        return

    command = (
        "source ~/.zshrc >/dev/null 2>&1; "
        "printf '%s\\n' "
        "\"DOUBAO_APP_KEY=$DOUBAO_APP_KEY\" "
        "\"DOUBAO_ACCESS_KEY=$DOUBAO_ACCESS_KEY\""
    )
    result = subprocess.run(
        ["zsh", "-c", command],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        if key in missing and value:
            os.environ[key] = value


def transcode_to_mp3(audio_path: Path) -> Path:
    """Transcode to 16kHz mono 48kbps mp3 (first audio stream) for upload."""
    tmp = Path(tempfile.mkstemp(prefix="doubao_speaker_", suffix=".mp3")[1])
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(audio_path),
            "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-b:a", "48k",
            str(tmp),
        ],
        check=True,
    )
    return tmp


def post(url: str, headers: dict, body: dict, timeout: int = 120):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    for key, value in headers.items():
        req.add_header(key, value)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return dict(resp.headers), resp.read()


def format_ts(ms) -> str:
    seconds = int(ms) // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def merge_segments(utterances: list) -> list:
    """Merge consecutive utterances of the same speaker into one segment."""
    segments = []
    for utt in utterances:
        speaker = utt.get("additions", {}).get("speaker", "?")
        if segments and segments[-1]["speaker"] == speaker:
            segments[-1]["text"] += utt["text"]
            segments[-1]["end"] = utt["end_time"]
        else:
            segments.append(
                {
                    "speaker": speaker,
                    "start": utt["start_time"],
                    "end": utt["end_time"],
                    "text": utt["text"],
                }
            )
    return segments


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transcribe audio with speaker diarization via Doubao file recognition"
    )
    parser.add_argument("audio_path", help="Path to audio file")
    parser.add_argument("-o", "--output", help="Output transcript path")
    parser.add_argument("--raw-json", help="Raw API response path")
    parser.add_argument("--poll-interval", type=int, default=15)
    parser.add_argument("--timeout", type=int, default=2400)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audio_path = Path(args.audio_path).expanduser().resolve()
    if not audio_path.exists():
        sys.exit(f"audio not found: {audio_path}")

    stem = audio_path.stem
    out_txt = Path(args.output) if args.output else audio_path.parent / f"{stem}_豆包录音文件识别_说话人分离.txt"
    out_raw = Path(args.raw_json) if args.raw_json else audio_path.parent / f"{stem}_豆包录音文件识别_speaker_raw.json"
    sidecar = out_txt.parent / f".{stem}_speaker_submit.json"

    load_environment()
    app_key = os.getenv("DOUBAO_APP_KEY")
    access_key = os.getenv("DOUBAO_ACCESS_KEY")
    if not app_key or not access_key:
        sys.exit("DOUBAO_APP_KEY and DOUBAO_ACCESS_KEY are not configured")

    mp3_path = transcode_to_mp3(audio_path)
    try:
        audio_b64 = base64.b64encode(mp3_path.read_bytes()).decode()
    finally:
        mp3_path.unlink(missing_ok=True)

    request_id = str(uuid.uuid4())
    headers = {
        "X-Api-App-Key": app_key,
        "X-Api-Access-Key": access_key,
        "X-Api-Resource-Id": "volc.bigasr.auc",
        "X-Api-Request-Id": request_id,
        "X-Api-Sequence": "-1",
    }
    print(f"[submit] request_id={request_id} payload={len(audio_b64) / 1e6:.1f}MB", flush=True)

    body = {
        "user": {"uid": "whisper-input-next"},
        "audio": {"format": "mp3", "data": audio_b64},
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "show_utterances": True,
            "enable_speaker_info": True,
        },
    }
    resp_headers, resp_body = post(SUBMIT_URL, headers, body)
    code = resp_headers.get("X-Api-Status-Code", "")
    if code != STATUS_OK:
        print(resp_body[:2000].decode(errors="replace"), file=sys.stderr)
        sys.exit(f"submit failed: status={code} msg={resp_headers.get('X-Api-Message', '')}")

    # 留单号：轮询被打断时可凭 request_id 手动 query 领结果，不用重新提交付费
    sidecar.write_text(json.dumps({"request_id": request_id, "audio": str(audio_path)}))

    deadline = time.time() + args.timeout
    while True:
        if time.time() > deadline:
            sys.exit(f"timeout after {args.timeout}s; recover via request_id in {sidecar}")
        time.sleep(args.poll_interval)
        try:
            resp_headers, resp_body = post(QUERY_URL, headers, {})
        except Exception as exc:  # noqa: BLE001 - transient network errors, keep polling
            print(f"[query] error: {exc}", flush=True)
            continue
        code = resp_headers.get("X-Api-Status-Code", "")
        if code == STATUS_OK:
            break
        if code not in STATUS_PROCESSING:
            print(resp_body[:2000].decode(errors="replace"), file=sys.stderr)
            sys.exit(f"query failed: status={code} msg={resp_headers.get('X-Api-Message', '')}")
        print(f"[query] status={code} (processing)", flush=True)

    result = json.loads(resp_body)
    out_raw.write_text(json.dumps(result, ensure_ascii=False, indent=2))

    utterances = result.get("result", {}).get("utterances", [])
    if not utterances:
        sys.exit(f"no utterances in result; see raw json: {out_raw}")

    segments = merge_segments(utterances)
    with out_txt.open("w") as handle:
        for seg in segments:
            handle.write(
                f"[{format_ts(seg['start'])}-{format_ts(seg['end'])}] 说话人{seg['speaker']}：{seg['text']}\n\n"
            )
    sidecar.unlink(missing_ok=True)

    speakers = sorted({seg["speaker"] for seg in segments})
    print(f"[save] {out_raw}", flush=True)
    print(f"[save] {out_txt} ({len(segments)} segments, speakers: {', '.join(speakers)})", flush=True)


if __name__ == "__main__":
    main()
