#!/usr/bin/env python3
"""Fail-closed sync gate for the shipped seven-scene LastTake video.

The earlier submission-kit gate was built for a four-card title/screencast/web/outro
cut. LastTake is a continuous browser recording instead. This gate measures the final
MP4, its audio stream and sampled pixels, then binds those measurements to the exact
seven scene holds, caption windows, raw capture and release receipt used by the build.

Adapted from upgradedev/archon-qwen-memoryagent commit 603349c. No pristine upstream
copy is vendored in this repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess


EXPECTED_SCENES = ("hook", "surface", "trigger", "live", "sponsor", "evidence", "close")
EXPECTED_WIDTH = 1920
EXPECTED_HEIGHT = 1080
EXPECTED_FPS = 25.0
FRAME_SECONDS = 1.0 / EXPECTED_FPS


class Gate:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, condition: bool, label: str, detail: str) -> None:
        if condition:
            print(f"PASS {label}: {detail}")
        else:
            print(f"FAIL {label}: {detail}")
            self.failures.append(label)


def command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe(path: Path) -> dict[str, object]:
    result = command(
        [
            os.environ.get("FFPROBE", "ffprobe"), "-v", "error",
            "-show_streams", "-show_format", "-of", "json", str(path),
        ]
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr[-2000:] or f"ffprobe failed for {path}")
    return json.loads(result.stdout)


def finite_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def rate(value: object) -> float | None:
    if not isinstance(value, str):
        return finite_number(value)
    if "/" in value:
        left, right = value.split("/", 1)
        numerator, denominator = finite_number(left), finite_number(right)
        if numerator is None or denominator in (None, 0):
            return None
        return numerator / denominator
    return finite_number(value)


def timestamp_seconds(value: str) -> float:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", value)
    if not match:
        raise ValueError(f"invalid SRT timestamp: {value}")
    hours, minutes, seconds, millis = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def parse_srt(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    blocks = re.split(r"\n{2,}", text) if text else []
    cues: list[dict[str, object]] = []
    for expected_number, block in enumerate(blocks, start=1):
        lines = block.splitlines()
        if len(lines) < 3 or lines[0].strip() != str(expected_number):
            raise ValueError(f"invalid SRT cue numbering at {expected_number}")
        match = re.fullmatch(
            r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})",
            lines[1].strip(),
        )
        if not match:
            raise ValueError(f"invalid SRT cue timing at {expected_number}")
        cues.append({
            "startSeconds": timestamp_seconds(match.group(1)),
            "endSeconds": timestamp_seconds(match.group(2)),
            "text": " ".join(line.strip() for line in lines[2:] if line.strip()),
        })
    return cues


def frame_md5(path: Path, seconds: float) -> str | None:
    result = command([
        os.environ.get("FFMPEG", "ffmpeg"), "-v", "error", "-ss", f"{seconds:.3f}",
        "-i", str(path), "-map", "0:v:0", "-frames:v", "1", "-vf",
        "scale=320:-2,format=gray", "-f", "md5", "-",
    ])
    if result.returncode != 0:
        return None
    match = re.search(r"MD5=([a-f0-9]{32})", result.stdout)
    return match.group(1) if match else None


def frame_luma(path: Path, seconds: float, region: str = "top") -> bytes | None:
    crop = (
        "crop=iw:trunc(ih*0.68/2)*2:0:0"
        if region == "top"
        else "crop=iw:trunc(ih*0.30/2)*2:0:ih-oh"
    )
    result = subprocess.run([
        os.environ.get("FFMPEG", "ffmpeg"), "-v", "error", "-ss", f"{seconds:.3f}",
        "-i", str(path), "-map", "0:v:0", "-frames:v", "1", "-vf",
        f"{crop},scale=96:54:flags=area,format=gray", "-f", "rawvideo", "-",
    ], capture_output=True, check=False)
    expected = 96 * 54
    return result.stdout if result.returncode == 0 and len(result.stdout) == expected else None


def frame_distance(left: bytes | None, right: bytes | None) -> float | None:
    if left is None or right is None or len(left) != len(right) or not left:
        return None
    return sum(abs(a - b) for a, b in zip(left, right, strict=True)) / (255 * len(left))


def audio_activity(path: Path, start: float, duration: float) -> tuple[float | None, float | None]:
    result = command([
        os.environ.get("FFMPEG", "ffmpeg"), "-hide_banner", "-nostats", "-ss",
        f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(path), "-map", "0:a:0",
        "-af", "silencedetect=noise=-45dB:d=0.2,volumedetect", "-f", "null", "-",
    ])
    match = re.search(r"max_volume:\s*(-?[0-9.]+)\s*dB", result.stderr)
    silent = sum(float(value) for value in re.findall(r"silence_duration:\s*([0-9.]+)", result.stderr))
    activity = max(0.0, min(1.0, (duration - silent) / duration)) if duration > 0 else None
    return (float(match.group(1)) if match else None, activity)


def load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", default=os.environ.get("LASTTAKE_VIDEO_ROOT", ""),
        help="media root containing narration/, capture/ and output/",
    )
    args = parser.parse_args(argv)
    if not args.root:
        raise SystemExit("LASTTAKE_VIDEO_ROOT or --root is required")
    root = Path(args.root).resolve()
    narration, capture_dir, output = root / "narration", root / "capture", root / "output"
    paths = {
        "mp4": output / "lasttake-demo.mp4",
        "output_captions": output / "captions.en.srt",
        "output_timing": output / "timing.json",
        "output_caption_windows": output / "caption-windows.json",
        "timing": narration / "timing.json",
        "captions": narration / "captions.en.srt",
        "caption_windows": narration / "caption-windows.json",
        "capture": capture_dir / "production.webm",
        "capture_receipt": capture_dir / "capture-receipt.json",
        "video_receipt": output / "video-receipt.json",
    }
    for label, path in paths.items():
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"::error::verify_video_sync: required {label} missing: {path}")

    timing = load_json(paths["timing"])
    windows_manifest = load_json(paths["caption_windows"])
    capture_receipt = load_json(paths["capture_receipt"])
    video_receipt = load_json(paths["video_receipt"])
    media, raw_media = probe(paths["mp4"]), probe(paths["capture"])
    gate = Gate()

    scenes = timing.get("scenes") if isinstance(timing.get("scenes"), list) else []
    scene_ids = tuple(str(scene.get("id", "")) for scene in scenes if isinstance(scene, dict))
    total = finite_number(timing.get("totalSeconds"))
    gate.check(timing.get("schemaVersion") == "lasttake.submission-video-timing/v1",
               "timing-schema", str(timing.get("schemaVersion")))
    gate.check(scene_ids == EXPECTED_SCENES, "scene-order", f"observed={scene_ids}")
    gate.check(total is not None and 90 <= total < 175, "timing-budget", f"total={total}")

    holds: list[float] = []
    timing_shape = len(scenes) == len(EXPECTED_SCENES)
    expected_start = 0.0
    for scene in scenes:
        if not isinstance(scene, dict):
            timing_shape = False
            continue
        start = finite_number(scene.get("startSeconds"))
        duration = finite_number(scene.get("durationSeconds"))
        hold = finite_number(scene.get("holdSeconds"))
        timing_shape = timing_shape and all(item is not None for item in (start, duration, hold))
        timing_shape = timing_shape and isinstance(scene.get("audioSha256"), str) \
            and re.fullmatch(r"[a-f0-9]{64}", str(scene.get("audioSha256"))) is not None
        if start is None or duration is None or hold is None:
            continue
        timing_shape = timing_shape and abs(start - expected_start) <= 0.01
        timing_shape = timing_shape and 3 <= duration <= 40
        timing_shape = timing_shape and duration <= hold <= duration + 1.0
        holds.append(hold)
        expected_start += hold
    reconstructed = sum(holds)
    gate.check(timing_shape and total is not None and abs(reconstructed - total) <= 0.01,
               "scene-timing", f"holds={reconstructed:.3f} total={total}")

    streams = media.get("streams") if isinstance(media.get("streams"), list) else []
    videos = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"]
    audios = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"]
    media_format = media.get("format") if isinstance(media.get("format"), dict) else {}
    measured = finite_number(media_format.get("duration"))
    fps = rate(videos[0].get("avg_frame_rate")) if len(videos) == 1 else None
    gate.check(len(videos) == 1 and len(audios) == 1, "streams",
               f"video={len(videos)} audio={len(audios)}")
    gate.check(
        len(videos) == 1 and videos[0].get("width") == EXPECTED_WIDTH
        and videos[0].get("height") == EXPECTED_HEIGHT and fps is not None
        and abs(fps - EXPECTED_FPS) < 0.01,
        "video-shape",
        f"width={videos[0].get('width') if videos else None} "
        f"height={videos[0].get('height') if videos else None} fps={fps}",
    )
    gate.check(measured is not None and total is not None
               and abs(measured - total) <= FRAME_SECONDS + 0.002,
               "video-duration", f"measured={measured} timing={total}")
    audio_duration = finite_number(audios[0].get("duration")) if len(audios) == 1 else None
    gate.check(audio_duration is not None and measured is not None
               and abs(audio_duration - measured) <= FRAME_SECONDS + 0.002,
               "audio-video-duration", f"audio={audio_duration} video={measured}")

    capture_timings = capture_receipt.get("sceneTimings") \
        if isinstance(capture_receipt.get("sceneTimings"), list) else []
    capture_ids = tuple(str(item.get("id", "")) for item in capture_timings
                        if isinstance(item, dict))
    capture_ok = capture_ids == EXPECTED_SCENES
    expected_capture_start = 0.0
    for index, item in enumerate(capture_timings):
        if not isinstance(item, dict) or index >= len(scenes) or not isinstance(scenes[index], dict):
            capture_ok = False
            continue
        action = finite_number(item.get("actionMilliseconds"))
        hold_ms = finite_number(item.get("holdMilliseconds"))
        start_ms = finite_number(item.get("startMilliseconds"))
        end_ms = finite_number(item.get("endMilliseconds"))
        expected_hold = finite_number(scenes[index].get("holdSeconds"))
        capture_ok = capture_ok and all(v is not None for v in
                                        (action, hold_ms, start_ms, end_ms, expected_hold))
        if any(v is None for v in (action, hold_ms, start_ms, end_ms, expected_hold)):
            continue
        capture_ok = capture_ok and 0 <= action <= hold_ms
        capture_ok = capture_ok and abs(hold_ms - expected_hold * 1000) <= 1.1
        capture_ok = capture_ok and abs((end_ms - start_ms) - hold_ms) <= 1500
        capture_ok = capture_ok and abs(start_ms - expected_capture_start) <= 1500
        expected_capture_start = end_ms
    if total is not None:
        capture_ok = capture_ok and abs(expected_capture_start - total * 1000) <= 1500
    gate.check(capture_ok, "capture-scene-holds", f"ids={capture_ids}")
    gate.check(capture_receipt.get("pageErrors") == [], "capture-browser-errors",
               str(capture_receipt.get("pageErrors")))
    gate.check(capture_receipt.get("bytes") == paths["capture"].stat().st_size
               and capture_receipt.get("sha256") == sha256(paths["capture"]),
               "capture-digest", f"bytes={paths['capture'].stat().st_size}")
    raw_format = raw_media.get("format") if isinstance(raw_media.get("format"), dict) else {}
    raw_duration = finite_number(raw_format.get("duration"))
    trim_lead = finite_number(capture_receipt.get("trimLeadSeconds"))
    gate.check(raw_duration is not None and trim_lead is not None and total is not None
               and 0 <= trim_lead <= 30 and raw_duration + FRAME_SECONDS >= trim_lead + total,
               "capture-duration", f"raw={raw_duration} trim={trim_lead} timeline={total}")

    try:
        cues = parse_srt(paths["captions"])
    except ValueError as error:
        cues = []
        gate.check(False, "captions-parse", str(error))
    else:
        gate.check(bool(cues), "captions-parse", f"cues={len(cues)}")
    manifest_windows = windows_manifest.get("windows") \
        if isinstance(windows_manifest.get("windows"), list) else []
    gate.check(windows_manifest.get("schemaVersion") ==
               "lasttake.submission-video-caption-windows/v1"
               and tuple(windows_manifest.get("scenes", [])) == EXPECTED_SCENES,
               "caption-manifest", f"scenes={windows_manifest.get('scenes')}")
    caption_ok = len(cues) == len(manifest_windows) and len(cues) >= len(EXPECTED_SCENES)
    previous_end = -1.0
    scene_with_caption: set[str] = set()
    timing_by_id = {str(scene.get("id")): scene for scene in scenes if isinstance(scene, dict)}
    for index, window in enumerate(manifest_windows):
        if not isinstance(window, dict) or index >= len(cues):
            caption_ok = False
            continue
        start, end = finite_number(window.get("startSeconds")), finite_number(window.get("endSeconds"))
        scene_id = str(window.get("sceneId", ""))
        scene = timing_by_id.get(scene_id)
        if start is None or end is None or not isinstance(scene, dict):
            caption_ok = False
            continue
        scene_start = finite_number(scene.get("startSeconds"))
        scene_duration = finite_number(scene.get("durationSeconds"))
        cue_start = finite_number(cues[index].get("startSeconds"))
        cue_end = finite_number(cues[index].get("endSeconds"))
        if any(v is None for v in (scene_start, scene_duration, cue_start, cue_end)):
            caption_ok = False
            continue
        caption_ok = caption_ok and start >= previous_end - 0.002 and 0 <= start < end
        caption_ok = caption_ok and end <= (total or 0) + 0.002
        caption_ok = caption_ok and start >= scene_start - 0.002
        caption_ok = caption_ok and end <= scene_start + scene_duration + 0.002
        caption_ok = caption_ok and abs(cue_start - start) <= 0.002
        caption_ok = caption_ok and abs(cue_end - end) <= 0.002
        caption_ok = caption_ok and re.sub(r"\s+", " ", str(cues[index].get("text", "")).strip()) \
            == re.sub(r"\s+", " ", str(window.get("text", "")).strip())
        previous_end = end
        scene_with_caption.add(scene_id)
    caption_ok = caption_ok and scene_with_caption == set(EXPECTED_SCENES)
    gate.check(caption_ok, "captions-aligned",
               f"windows={len(manifest_windows)} scenes={sorted(scene_with_caption)}")
    caption_pixel_differences: list[float | None] = []
    clear_pixel_differences: list[float | None] = []
    for scene_id in EXPECTED_SCENES:
        scene = timing_by_id.get(scene_id)
        scene_windows = [window for window in manifest_windows
                         if isinstance(window, dict) and window.get("sceneId") == scene_id]
        if not isinstance(scene, dict) or not scene_windows:
            caption_pixel_differences.append(None)
            clear_pixel_differences.append(None)
            continue
        window = max(
            scene_windows,
            key=lambda item: (finite_number(item.get("endSeconds")) or 0)
            - (finite_number(item.get("startSeconds")) or 0),
        )
        window_start = finite_number(window.get("startSeconds"))
        window_end = finite_number(window.get("endSeconds"))
        scene_start = finite_number(scene.get("startSeconds"))
        duration = finite_number(scene.get("durationSeconds"))
        hold = finite_number(scene.get("holdSeconds"))
        if any(value is None for value in
               (window_start, window_end, scene_start, duration, hold, trim_lead)):
            caption_pixel_differences.append(None)
            clear_pixel_differences.append(None)
            continue
        caption_sample = (window_start + window_end) / 2
        clear_sample = scene_start + duration + (hold - duration) / 2
        caption_pixel_differences.append(frame_distance(
            frame_luma(paths["mp4"], caption_sample, "bottom"),
            frame_luma(paths["capture"], trim_lead + caption_sample, "bottom"),
        ))
        clear_pixel_differences.append(frame_distance(
            frame_luma(paths["mp4"], clear_sample, "bottom"),
            frame_luma(paths["capture"], trim_lead + clear_sample, "bottom"),
        ))
    caption_pixels_ok = len(caption_pixel_differences) == len(EXPECTED_SCENES)
    for visible, clear in zip(caption_pixel_differences, clear_pixel_differences, strict=True):
        caption_pixels_ok = caption_pixels_ok and visible is not None and clear is not None
        if visible is not None and clear is not None:
            caption_pixels_ok = caption_pixels_ok and clear <= 0.12
            caption_pixels_ok = caption_pixels_ok and visible >= clear * 1.5 + 0.001
    gate.check(caption_pixels_ok, "captions-visible-in-shipped-pixels",
               f"caption={caption_pixel_differences} clear={clear_pixel_differences}")
    gate.check(paths["captions"].read_bytes() == paths["output_captions"].read_bytes(),
               "captions-shipped", "source and uploaded SRT match")
    gate.check(paths["timing"].read_bytes() == paths["output_timing"].read_bytes()
               and paths["caption_windows"].read_bytes()
               == paths["output_caption_windows"].read_bytes(),
               "manifests-shipped", "timing and caption-window manifests match")

    pixel_hashes: list[str | None] = []
    final_scene_frames: list[bytes | None] = []
    raw_scene_frames: list[bytes | None] = []
    audible = True
    active_enough = True
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        start = finite_number(scene.get("startSeconds"))
        duration = finite_number(scene.get("durationSeconds"))
        if start is None or duration is None:
            continue
        sample = start + duration / 2
        pixel_hashes.append(frame_md5(paths["mp4"], sample))
        raw_sample = (trim_lead or 0) + sample
        final_scene_frames.append(frame_luma(paths["mp4"], sample))
        raw_scene_frames.append(frame_luma(paths["capture"], raw_sample))
        volume, activity = audio_activity(paths["mp4"], start, max(0.5, duration))
        audible = audible and volume is not None and volume > -55.0
        active_enough = active_enough and activity is not None and activity >= 0.25
    gate.check(len(pixel_hashes) == len(EXPECTED_SCENES) and None not in pixel_hashes
               and all(a != b for a, b in zip(pixel_hashes, pixel_hashes[1:])),
               "scene-pixels-change", f"sampled={pixel_hashes}")
    pixel_matrix = [
        [frame_distance(final_frame, raw_frame) for raw_frame in raw_scene_frames]
        for final_frame in final_scene_frames
    ]
    pixel_mapping = [
        min(range(len(row)), key=lambda index: row[index] if row[index] is not None else 2.0)
        for row in pixel_matrix
    ] if all(row for row in pixel_matrix) else []
    diagonal = [row[index] for index, row in enumerate(pixel_matrix)]
    gate.check(len(diagonal) == len(EXPECTED_SCENES) and None not in diagonal
               and max(diagonal, default=1.0) <= 0.12
               and pixel_mapping == list(range(len(EXPECTED_SCENES))),
               "scene-pixels-match-capture",
               f"mapping={pixel_mapping} diagonal={diagonal}")
    gate.check(audible, "scene-audio-present",
               "each measured narration scene exceeds -55 dB peak")
    gate.check(active_enough, "scene-audio-sustained",
               "each measured narration scene is non-silent for at least 25 percent")

    final_digest = sha256(paths["mp4"])
    receipt_duration = finite_number(video_receipt.get("durationSeconds"))
    receipt_ok = (
        video_receipt.get("schemaVersion") == "lasttake.submission-video-receipt/v1"
        and video_receipt.get("sceneCount") == len(EXPECTED_SCENES)
        and video_receipt.get("sha256") == final_digest
        and video_receipt.get("bytes") == paths["mp4"].stat().st_size
        and video_receipt.get("captureSha256") == sha256(paths["capture"])
        and video_receipt.get("timingSha256") == sha256(paths["timing"])
        and video_receipt.get("captionWindowsSha256") == sha256(paths["caption_windows"])
        and video_receipt.get("captionsSha256") == sha256(paths["output_captions"])
        and isinstance(timing.get("narrationSourceSha256"), str)
        and re.fullmatch(r"[a-f0-9]{64}", str(timing.get("narrationSourceSha256"))) is not None
        and video_receipt.get("narrationSourceSha256") == timing.get("narrationSourceSha256")
        and receipt_duration is not None and measured is not None
        and abs(receipt_duration - measured) <= 0.002
    )
    gate.check(receipt_ok, "video-receipt-binding", f"sha256={final_digest}")

    if gate.failures:
        print("::error::verify_video_sync FAILED:")
        for failure in gate.failures:
            print(f"::error::  - {failure}")
        return 1
    print("verify_video_sync: ALL LASTTAKE CONTINUOUS SYNC GATES PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
