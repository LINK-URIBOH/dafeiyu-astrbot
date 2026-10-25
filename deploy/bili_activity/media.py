"""Prepare small, timestamped media bundles on the PC running the Bili companion.

Only the compact result crosses the SSH tunnel. Downloaded streams and ffmpeg
outputs are temporary. This module never sends account credentials to ffmpeg.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image


MAX_DOWNLOAD_BYTES = 160 * 1024 * 1024
MAX_RESPONSE_BYTES = 3 * 1024 * 1024
MAX_FRAME_BYTES = 80_000
MAX_AUDIO_BYTES = 260_000
MAX_FRAMES = 8
MAX_SECONDS = 300
CDN_SUFFIXES = ("bilivideo.com", "bilivideo.cn", "bilivideo.net", "acgvideo.com")


def _cdn_url(stream):
    url = stream.get("baseUrl") or stream.get("base_url")
    if not isinstance(url, str):
        raise ValueError("stream URL missing")
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("media stream must use HTTPS")
    if not any(host == s or host.endswith("." + s) for s in CDN_SUFFIXES):
        raise ValueError("unexpected media CDN")
    return url


def _choose_stream(streams, video=False):
    candidates = [s for s in streams if isinstance(s, dict)]
    if video:
        # Prefer AVC, which the existing ffmpeg installation can decode cheaply.
        avc = [s for s in candidates if str(s.get("codecs", "")).startswith("avc")]
        candidates = avc or candidates
    if not candidates:
        return None
    return min(candidates, key=lambda s: int(s.get("bandwidth") or 2**31))


async def _ffmpeg(executable, *args, timeout=30):
    process = await asyncio.create_subprocess_exec(
        executable, "-nostdin", "-hide_banner", "-threads", "1",
        *map(str, args), stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    communicate = asyncio.create_task(process.communicate())
    try:
        _, stderr = await asyncio.wait_for(asyncio.shield(communicate), timeout)
        return process.returncode, stderr
    except BaseException:
        if process.returncode is None:
            process.kill()
        await communicate
        await process.wait()
        raise


async def _probe(executable, path):
    _, stderr = await _ffmpeg(
        executable, "-protocol_whitelist", "file,pipe", "-i", path, timeout=15,
    )
    text = stderr.decode("utf-8", "replace")
    found = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not found:
        return None
    hours, minutes, seconds = map(float, found.groups())
    length = hours * 3600 + minutes * 60 + seconds
    return length if math.isfinite(length) and length > 0 else None


def _jpeg(path):
    with Image.open(path) as original:
        picture = original.convert("RGB")
        picture.thumbnail((960, 960))
        for quality in (82, 72, 62, 52, 42):
            data = io.BytesIO()
            picture.save(data, format="JPEG", quality=quality, optimize=True)
            if data.tell() <= MAX_FRAME_BYTES:
                return data.getvalue()
    raise ValueError("frame exceeds compact transfer budget")


def _append_media(result, kind, item):
    result[kind].append(item)
    size = len(json.dumps(result, ensure_ascii=False).encode())
    if size <= MAX_RESPONSE_BYTES - 4096:
        return True
    result[kind].pop()
    return False


def _subtitle_rows(payload, start, end):
    rows = payload.get("subtitles", []) if isinstance(payload, dict) else []
    # Do not let an unexpected endpoint shape masquerade as valid subtitles.
    if not isinstance(rows, list):
        return []
    output = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            left, right = float(row["from"]), float(row["to"])
        except (KeyError, ValueError, TypeError):
            continue
        if (math.isfinite(left) and math.isfinite(right)
                and right > left and right > start and left < end
                and isinstance(row.get("content"), str)):
            output.append({"from": left, "to": right, "content": row["content"][:2000]})
        if len(output) == 500:
            break
    return output


async def prepare_video(api, bvid: str, cid: int, start: float = 0, end: float = 300):
    """Return frames, subtitles, or audio with actual times and partial failures.

    The caller must run this on the local companion, not on the 2 Mbit/s cloud
    host. ``api.identity`` must reject a cid belonging to a different video.
    Cancellation propagates after child processes and temporary files are reaped.
    """
    start, end = float(start), float(end)
    if not all(math.isfinite(v) for v in (start, end)) or start < 0 or end <= start:
        raise ValueError("invalid media range")
    identity = await api.identity(bvid, int(cid))
    duration = float(identity.get("duration") or 0)
    if not math.isfinite(duration) or duration <= 0 or start >= duration:
        raise ValueError("requested range is outside this video part")
    requested_end = end
    end = min(end, start + MAX_SECONDS, duration)
    result = {
        "identity": identity,
        "requested_range": {"start": start, "end": requested_end},
        "covered_range": {"start": start, "end": end},
        "frames": [], "audio": [], "subtitles": [], "notes": [],
        "downloaded_bytes": 0,
    }
    if end < requested_end:
        result["notes"].append("range limited to video duration and 300 seconds")
    try:
        payload = await api.read("subtitles", {"bvid": bvid, "cid": int(cid)})
        rows = _subtitle_rows(payload, start, end)
        # A subtitle explosion must not consume the compact media budget.
        total = 0
        for row in rows:
            total += len(json.dumps(row, ensure_ascii=False).encode())
            if total > 100_000:
                result["notes"].append("subtitle output truncated at 100 KB")
                break
            result["subtitles"].append(row)
    except Exception as exc:
        result["notes"].append(f"subtitles unavailable ({type(exc).__name__}); audio fallback")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        result["notes"].append("local ffmpeg unavailable; subtitles retained")
        return result
    try:
        playback = await api.request(
            "/x/player/playurl",
            params={"bvid": bvid, "cid": str(cid), "qn": "16", "fnval": "16", "fourk": "0"},
        )
        dash = playback.get("dash") or {}
        video = _choose_stream(dash.get("video") or [], video=True)
        audio = None if result["subtitles"] else _choose_stream(dash.get("audio") or [])
    except Exception as exc:
        result["notes"].append(f"playback source unavailable ({type(exc).__name__}); subtitles retained")
        return result

    with tempfile.TemporaryDirectory(prefix="dafeiyu-bili-media-") as temporary:
        folder = Path(temporary)
        paths = {}
        for kind, stream in (("video", video), ("audio", audio)):
            if stream is None:
                if kind == "video" or not result["subtitles"]:
                    result["notes"].append(f"{kind} stream unavailable")
                continue
            path = folder / (kind + ".m4s")
            try:
                remaining = MAX_DOWNLOAD_BYTES - result["downloaded_bytes"]
                if remaining <= 0:
                    raise ValueError("download budget exhausted")
                await api.download(_cdn_url(stream), path, limit=remaining)
                size = path.stat().st_size
                if size <= 0 or size > remaining:
                    raise ValueError("download size outside allowed budget")
                result["downloaded_bytes"] += size
                paths[kind] = path
            except Exception as exc:
                path.unlink(missing_ok=True)
                result["notes"].append(f"{kind} download failed ({type(exc).__name__}); other results retained")

        video_path = paths.get("video")
        if video_path:
            try:
                actual = await _probe(ffmpeg, video_path)
                if actual is not None and actual < end:
                    end = max(start, actual)
                    result["covered_range"]["end"] = end
                    result["notes"].append("downloaded video ends earlier than metadata")
            except Exception as exc:
                result["notes"].append(f"video duration probe failed ({type(exc).__name__})")
            if end > start:
                count = min(MAX_FRAMES, max(1, math.ceil((end - start) / 4)))
                final = max(start, end - min(0.5, (end - start) / 2))
                moments = [start + (final - start) * i / (count - 1)
                           for i in range(count)] if count > 1 else [start]
                for index, at in enumerate(moments):
                    output = folder / f"frame-{index}.jpg"
                    try:
                        rc, _ = await _ffmpeg(
                            ffmpeg, "-loglevel", "error", "-y", "-ss", at,
                            "-protocol_whitelist", "file,pipe", "-i", video_path,
                            "-map", "0:v:0", "-frames:v", "1", "-an",
                            "-filter_threads", "1", "-vf",
                            "scale=960:960:force_original_aspect_ratio=decrease",
                            "-q:v", "4", "-threads", "1", output,
                        )
                        if rc != 0:
                            raise ValueError("frame extraction failed")
                        item = {"at": round(at, 3), "mime": "image/jpeg",
                                "data": base64.b64encode(_jpeg(output)).decode("ascii")}
                        if not _append_media(result, "frames", item):
                            result["notes"].append("frame omitted due to transfer budget")
                            break
                    except Exception as exc:
                        result["notes"].append(f"frame at {at:.3f}s failed ({type(exc).__name__})")

        audio_path = paths.get("audio")
        if audio_path:
            for index, left in enumerate(range(int(start), math.ceil(end), 60)):
                # Preserve non-integer requested starts in the first segment.
                left = start + index * 60
                right = min(left + 60, end)
                if right <= left:
                    break
                output = folder / f"audio-{index}.mp3"
                try:
                    rc, _ = await _ffmpeg(
                        ffmpeg, "-loglevel", "error", "-y", "-ss", left,
                        "-protocol_whitelist", "file,pipe", "-i", audio_path,
                        "-t", right - left, "-map", "0:a:0", "-vn",
                        "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame",
                        "-b:a", "32k", "-threads", "1", output,
                    )
                    if rc != 0 or not output.exists():
                        raise ValueError("audio extraction failed")
                    raw = output.read_bytes()
                    if not raw or len(raw) > MAX_AUDIO_BYTES:
                        raise ValueError("audio exceeds transfer budget")
                    actual = await _probe(ffmpeg, output)
                    if actual is None or actual <= 0:
                        raise ValueError("audio duration could not be verified")
                    item = {"start": round(left, 3), "end": round(min(right, left + actual), 3),
                            "mime": "audio/mpeg", "data": base64.b64encode(raw).decode("ascii")}
                    if not _append_media(result, "audio", item):
                        result["notes"].append("audio omitted due to transfer budget")
                        break
                except Exception as exc:
                    result["notes"].append(f"audio {left:.3f}-{right:.3f}s failed ({type(exc).__name__})")
    result["notes"].append(
        "frames are samples, not continuous viewing; covered_range is the bounded requested "
        "window; only listed frame times, subtitle intervals and audio intervals were obtained"
    )
    return result
