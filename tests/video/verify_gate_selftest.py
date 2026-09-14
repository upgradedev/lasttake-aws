#!/usr/bin/env python3
"""Prove the continuous LastTake video sync gate passes good media and rejects drift.

The fixture contains no provider audio, browser session or external request. ffmpeg
creates one synthetic seven-scene-sized MP4, and the real gate reads its streams and
pixels. Mutations then prove scene order, offsets, capture continuity, rendered pixels,
caption alignment, duration and receipt binding fail closed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
GATE = REPO / "scripts" / "verify_video_sync.py"
SCENES = ("hook", "surface", "trigger", "live", "sponsor", "evidence", "close")
HOLD = 13.0
SPEECH = 12.35
TOTAL = HOLD * len(SCENES)


def run(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(result.stderr[-3000:] or "fixture command failed")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    seconds, millis = divmod(millis, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def fixture(root: Path) -> dict[str, object]:
    narration, capture, output = root / "narration", root / "capture", root / "output"
    narration.mkdir(parents=True)
    capture.mkdir()
    output.mkdir()
    final = output / "lasttake-demo.mp4"
    raw_source = capture / "raw-source.mp4"
    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=s=1920x1080:r=25:duration={TOTAL}",
        "-map", "0:v:0", "-an", "-c:v", "libx264", "-preset", "ultrafast",
        "-crf", "36", "-pix_fmt", "yuv420p", str(raw_source),
    ])
    raw = capture / "production.webm"
    shutil.move(raw_source, raw)

    scenes = []
    windows = []
    srt = []
    scene_timings = []
    for index, scene_id in enumerate(SCENES, start=1):
        start = (index - 1) * HOLD
        scenes.append({
            "id": scene_id, "audio": f"{index:02d}-{scene_id}.mp3",
            "durationSeconds": SPEECH, "holdSeconds": HOLD,
            "startSeconds": start, "cacheHit": False, "audioSha256": "c" * 64,
        })
        text = f"Synthetic caption for {scene_id}."
        windows.append({
            "sceneId": scene_id, "startSeconds": start + 0.2,
            "endSeconds": start + 1.2, "text": text,
        })
        srt.extend([
            str(index), f"{stamp(start + 0.2)} --> {stamp(start + 1.2)}", text, "",
        ])
        scene_timings.append({
            "id": scene_id, "startMilliseconds": start * 1000,
            "endMilliseconds": (start + HOLD) * 1000,
            "actionMilliseconds": 100, "holdMilliseconds": HOLD * 1000,
        })

    timing = {
        "schemaVersion": "lasttake.submission-video-timing/v1",
        "mode": "final", "narrationSourceSha256": "d" * 64,
        "totalSeconds": TOTAL, "scenes": scenes,
    }
    caption_manifest = {
        "schemaVersion": "lasttake.submission-video-caption-windows/v1",
        "scenes": list(SCENES), "windows": windows,
    }
    write_json(narration / "timing.json", timing)
    write_json(narration / "caption-windows.json", caption_manifest)
    (narration / "captions.en.srt").write_text("\n".join(srt), encoding="utf-8")
    shutil.copyfile(narration / "captions.en.srt", output / "captions.en.srt")
    shutil.copyfile(narration / "timing.json", output / "timing.json")
    shutil.copyfile(narration / "caption-windows.json", output / "caption-windows.json")
    captions_filter = str(narration / "captions.en.srt").replace("\\", "/").replace(":", "\\:")
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={TOTAL}",
        "-map", "0:v:0", "-map", "1:a:0", "-vf",
        f"subtitles='{captions_filter}':force_style='FontSize=14,BorderStyle=4,MarginV=38'",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "36", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-shortest", str(final),
    ])
    capture_receipt = {
        "schemaVersion": "lasttake.submission-video-capture/v1",
        "releaseSha": "a" * 40, "appOrigin": "https://example.invalid",
        "sceneCount": len(SCENES), "sceneTimings": scene_timings,
        "workflowResult": {}, "trimLeadSeconds": 0, "timelineSeconds": TOTAL,
        "pageErrors": [], "bytes": raw.stat().st_size, "sha256": digest(raw),
    }
    write_json(capture / "capture-receipt.json", capture_receipt)
    receipt = {
        "schemaVersion": "lasttake.submission-video-receipt/v1",
        "releaseSha": "a" * 40, "backendSha": "b" * 40,
        "durationSeconds": TOTAL, "width": 1920, "height": 1080,
        "sceneCount": len(SCENES), "sha256": digest(final), "bytes": final.stat().st_size,
        "captureSha256": digest(raw), "timingSha256": digest(narration / "timing.json"),
        "captionWindowsSha256": digest(narration / "caption-windows.json"),
        "captionsSha256": digest(output / "captions.en.srt"),
        "narrationSourceSha256": "d" * 64,
    }
    write_json(output / "video-receipt.json", receipt)
    return {
        "timing": timing, "windows": caption_manifest,
        "capture": capture_receipt, "receipt": receipt,
    }


def restore(root: Path, values: dict[str, object]) -> None:
    write_json(root / "narration" / "timing.json", values["timing"])
    write_json(root / "narration" / "caption-windows.json", values["windows"])
    shutil.copyfile(root / "narration" / "timing.json", root / "output" / "timing.json")
    shutil.copyfile(root / "narration" / "caption-windows.json",
                    root / "output" / "caption-windows.json")
    write_json(root / "capture" / "capture-receipt.json", values["capture"])
    write_json(root / "output" / "video-receipt.json", values["receipt"])


def swap_first_two_capture_scenes(root: Path) -> None:
    source = root / "output" / "lasttake-demo.mp4"
    swapped = root / "capture" / "swapped.mp4"
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
        "-filter_complex",
        f"[0:v]trim=start={HOLD}:end={2 * HOLD},setpts=PTS-STARTPTS[v1];"
        f"[0:v]trim=start=0:end={HOLD},setpts=PTS-STARTPTS[v0];"
        f"[0:v]trim=start={2 * HOLD}:end={TOTAL},setpts=PTS-STARTPTS[v2];"
        "[v1][v0][v2]concat=n=3:v=1:a=0[v]",
        "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "ultrafast",
        "-crf", "36", "-pix_fmt", "yuv420p", str(swapped),
    ])
    shutil.move(swapped, root / "capture" / "production.webm")


def gate(root: Path) -> tuple[int, list[str], str]:
    result = subprocess.run(
        [sys.executable, str(GATE), "--root", str(root)],
        capture_output=True, text=True, check=False,
    )
    output = result.stdout + result.stderr
    return result.returncode, re.findall(r"::error::  - (\S+)", output), output


def main() -> int:
    if not GATE.is_file():
        raise SystemExit(f"gate not found: {GATE}")
    for tool in ("ffmpeg", "ffprobe"):
        if subprocess.run([tool, "-version"], capture_output=True).returncode != 0:
            raise SystemExit(f"{tool} is required")

    results = []
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        original = fixture(root)

        rc, failures, output = gate(root)
        results.append(("GOOD", rc == 0, failures, output))

        mutated = copy.deepcopy(original)
        mutated["timing"]["scenes"][0]["id"] = "surface"
        restore(root, mutated)
        rc, failures, output = gate(root)
        results.append(("BAD_SCENE_ORDER", rc == 1 and "scene-order" in failures, failures, output))

        mutated = copy.deepcopy(original)
        for index, scene in enumerate(mutated["timing"]["scenes"]):
            scene["startSeconds"] = index * 2
        restore(root, mutated)
        rc, failures, output = gate(root)
        results.append(("BAD_SCENE_OFFSETS", rc == 1 and "scene-timing" in failures, failures, output))

        mutated = copy.deepcopy(original)
        mutated["capture"]["sceneTimings"][1]["startMilliseconds"] = 0
        mutated["capture"]["sceneTimings"][1]["endMilliseconds"] = HOLD * 1000
        restore(root, mutated)
        rc, failures, output = gate(root)
        results.append(("BAD_CAPTURE_TIMELINE", rc == 1 and "capture-scene-holds" in failures,
                        failures, output))

        mutated = copy.deepcopy(original)
        mutated["windows"]["windows"][1]["startSeconds"] = 0.5
        restore(root, mutated)
        rc, failures, output = gate(root)
        results.append(("BAD_CAPTION_ALIGNMENT", rc == 1 and "captions-aligned" in failures, failures, output))

        mutated = copy.deepcopy(original)
        mutated["timing"]["totalSeconds"] = TOTAL - 1
        restore(root, mutated)
        rc, failures, output = gate(root)
        results.append(("BAD_DURATION", rc == 1 and "video-duration" in failures, failures, output))

        mutated = copy.deepcopy(original)
        mutated["receipt"]["sha256"] = "0" * 64
        restore(root, mutated)
        rc, failures, output = gate(root)
        results.append(("BAD_RECEIPT", rc == 1 and "video-receipt-binding" in failures, failures, output))

        mutated = copy.deepcopy(original)
        raw = root / "capture" / "production.webm"
        shutil.copyfile(root / "output" / "lasttake-demo.mp4", raw)
        mutated["capture"]["bytes"] = raw.stat().st_size
        mutated["capture"]["sha256"] = digest(raw)
        mutated["receipt"]["captureSha256"] = digest(raw)
        restore(root, mutated)
        rc, failures, output = gate(root)
        results.append(("BAD_CAPTION_PIXELS",
                        rc == 1 and "captions-visible-in-shipped-pixels" in failures,
                        failures, output))

        mutated = copy.deepcopy(original)
        swap_first_two_capture_scenes(root)
        raw = root / "capture" / "production.webm"
        mutated["capture"]["bytes"] = raw.stat().st_size
        mutated["capture"]["sha256"] = digest(raw)
        mutated["receipt"]["captureSha256"] = digest(raw)
        restore(root, mutated)
        rc, failures, output = gate(root)
        results.append(("BAD_RENDERED_ORDER",
                        rc == 1 and "scene-pixels-match-capture" in failures,
                        failures, output))

    for label, ok, failures, output in results:
        print(f"[{'OK' if ok else 'FAIL'}] {label}: {failures or 'PASS'}")
        if not ok:
            print(output)
    if not all(item[1] for item in results):
        print("::error::continuous video sync selftest failed")
        return 1
    print("continuous video sync selftest: good media passed and every mutation failed closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
