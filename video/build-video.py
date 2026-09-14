#!/usr/bin/env python3
"""Compose the CI browser capture, measured narration, and captions.

Adapted from upgradedev/archon-datahub, master a1feb16, file
video/build-video.py. No pristine upstream copy is vendored here. The
LastTake-specific changes are:

  1. OUTPUT.mkdir(exist_ok=True). The original refused to compose twice into the same
     directory, which made re-rendering one beat impossible.
  2. The two evidence run ids in the receipt are written only when the environment
     supplies them. They bind two DataHub-specific workflows that a new project does
     not have. The release SHA stays required.
  3. The composed length must equal the measured narration length within one frame. The
     original checked only that the result was 90 to 179 seconds, so a capture shorter
     than the trim lead plus the narration produced a short video with the last beats of
     speech missing, and it passed.

Final composition remains owner-gated. The receipt binds the exact raw capture,
narration timing, caption windows and shipped caption file as well as the release pair.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess

from release_proof import recording_binding


ROOT = pathlib.Path(os.environ["LASTTAKE_VIDEO_ROOT"])
NARRATION = ROOT / "narration"
CAPTURE = ROOT / "capture" / "production.webm"
OUTPUT = ROOT / "output"
FRAME_SECONDS = 1 / 25  # matches fps=25 in the video filter below
EXPECTED_SCENES = ("hook", "surface", "trigger", "live", "sponsor", "evidence", "close")
NARRATION_SPEC = pathlib.Path(__file__).with_name("narration.json")


def run(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(result.stderr[-3000:] or "media command failed")
    return result.stdout.strip()


def probe(path: pathlib.Path) -> dict[str, object]:
    return json.loads(
        run(
            [
                os.environ["FFPROBE"],
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ]
        )
    )


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    timing_path = NARRATION / "timing.json"
    captions_path = NARRATION / "captions.en.srt"
    caption_windows_path = NARRATION / "caption-windows.json"
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    capture_receipt = json.loads(
        (ROOT / "capture" / "capture-receipt.json").read_text(encoding="utf-8")
    )
    before = json.loads((ROOT / "release-before.json").read_text(encoding="utf-8"))
    after = json.loads((ROOT / "release-after.json").read_text(encoding="utf-8"))
    binding = recording_binding(
        before, after, capture_receipt, os.environ["LASTTAKE_RELEASE_SHA"],
        os.environ.get("LASTTAKE_HOSTED_RUN_ID", ""),
        os.environ.get("LASTTAKE_GOVERNED_RUN_ID", ""),
    )
    scenes = timing["scenes"]
    total = float(timing["totalSeconds"])
    scene_ids = tuple(str(scene.get("id", "")) for scene in scenes)
    if timing.get("schemaVersion") != "lasttake.submission-video-timing/v1":
        raise SystemExit("narration timing schema is invalid")
    narration_source_digest = sha256(NARRATION_SPEC)
    if timing.get("narrationSourceSha256") != narration_source_digest:
        raise SystemExit("narration timing does not match the committed narration source")
    if scene_ids != EXPECTED_SCENES or not 90 <= total < 175:
        raise SystemExit("narration scene order or duration is outside the final contract")
    expected_start = 0.0
    for scene in scenes:
        start = float(scene["startSeconds"])
        hold = float(scene["holdSeconds"])
        duration = float(scene["durationSeconds"])
        if abs(start - expected_start) > 0.01 or not 3 <= duration <= hold <= duration + 1.0:
            raise SystemExit("narration scene offsets or holds are outside the final contract")
        audio = NARRATION / str(scene["audio"])
        if not audio.is_file() or scene.get("audioSha256") != sha256(audio):
            raise SystemExit("narration audio does not match its measured timing record")
        expected_start += hold
    if abs(expected_start - total) > 0.01:
        raise SystemExit("narration scene holds do not reconstruct the total duration")
    if capture_receipt.get("sceneCount") != len(EXPECTED_SCENES):
        raise SystemExit("capture receipt scene count is invalid")
    if tuple(item.get("id") for item in capture_receipt.get("sceneTimings", [])) != EXPECTED_SCENES:
        raise SystemExit("capture receipt scene order is invalid")
    capture_bytes = CAPTURE.stat().st_size
    capture_digest = sha256(CAPTURE)
    if capture_receipt.get("bytes") != capture_bytes or capture_receipt.get("sha256") != capture_digest:
        raise SystemExit("raw capture bytes do not match the capture receipt")
    trim_lead = float(capture_receipt["trimLeadSeconds"])
    if not 0 <= trim_lead <= 30:
        raise SystemExit("capture trim lead is outside the bounded contract")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    filters: list[str] = []
    labels: list[str] = []
    args = [os.environ["FFMPEG"], "-y", "-i", str(CAPTURE)]
    for index, scene in enumerate(scenes, start=1):
        audio = NARRATION / str(scene["audio"])
        args.extend(["-i", str(audio)])
        delay = round(float(scene["startSeconds"]) * 1000)
        hold = float(scene["holdSeconds"])
        label = f"a{index}"
        filters.append(
            f"[{index}:a]aresample=48000,apad=pad_dur={hold},atrim=0:{hold},"
            f"adelay={delay}:all=1[{label}]"
        )
        labels.append(f"[{label}]")
    captions = str(captions_path).replace("\\", "/").replace(":", "\\:")
    style = (
        "FontName=DejaVu Sans,FontSize=14,PrimaryColour=&H00FFFFFF,"
        "BackColour=&HA0000000,BorderStyle=4,Outline=0,Shadow=0,MarginV=38,Alignment=2"
    )
    filters.append(
        f"[0:v]trim=start={trim_lead}:end={trim_lead + total},setpts=PTS-STARTPTS,"
        "fps=25,scale=1920:1080:"
        "force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x07111f,"
        f"subtitles='{captions}':force_style='{style}',format=yuv420p[v]"
    )
    filters.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0,"
        f"loudnorm=I=-16:LRA=7:TP=-1.5,atrim=0:{total}[a]"
    )
    final = OUTPUT / "lasttake-demo.mp4"
    args.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(final),
        ]
    )
    run(args)
    media = probe(final)
    duration = float(media["format"]["duration"])
    streams = media["streams"]
    videos = [item for item in streams if item.get("codec_type") == "video"]
    audios = [item for item in streams if item.get("codec_type") == "audio"]
    if not 90 <= duration < 179 or len(videos) != 1 or len(audios) != 1:
        raise SystemExit("final media contract failed")
    if videos[0].get("width") != 1920 or videos[0].get("height") != 1080:
        raise SystemExit("final video dimensions are not 1920x1080")
    if abs(duration - total) > FRAME_SECONDS:
        raise SystemExit(
            f"composed {duration:.3f}s but the narration measures {total:.3f}s. "
            "The capture is shorter than the trim lead plus the narration, so -shortest "
            "cut the last beats off both streams. Record a longer capture. Do not widen "
            "this tolerance."
        )
    captions_out = OUTPUT / "captions.en.srt"
    captions_out.write_bytes(captions_path.read_bytes())
    timing_out = OUTPUT / "timing.json"
    timing_out.write_bytes(timing_path.read_bytes())
    caption_windows_out = OUTPUT / "caption-windows.json"
    caption_windows_out.write_bytes(caption_windows_path.read_bytes())
    digest = sha256(final)
    receipt = {
        "schemaVersion": "lasttake.submission-video-receipt/v1",
        **binding,
        "durationSeconds": round(duration, 3),
        "width": 1920,
        "height": 1080,
        "sceneCount": len(scenes),
        "sha256": digest,
        "bytes": final.stat().st_size,
        "captureSha256": capture_digest,
        "timingSha256": sha256(timing_out),
        "captionWindowsSha256": sha256(caption_windows_out),
        "captionsSha256": sha256(captions_out),
        "narrationSourceSha256": narration_source_digest,
    }
    (OUTPUT / "video-receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, separators=(",", ":")))


if __name__ == "__main__":
    main()
