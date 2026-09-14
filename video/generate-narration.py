#!/usr/bin/env python3
"""Generate short, measured TTS scenes and aligned captions in CI.

Adapted from upgradedev/archon-datahub, master a1feb16, file
video/generate-narration.py. No pristine upstream copy is vendored here. The
LastTake-specific changes are:

  1. Per-scene caching. A scene is re-synthesized only when its speech text or its
     voice settings change, so fixing one beat costs one TTS call instead of all of
     them. ElevenLabs does not return identical audio for identical input, so without
     this every fix re-rolls every other beat and shifts every measured offset.
  2. An ElevenLabs provider next to the original Google Cloud TTS provider.
  3. OUT.mkdir(exist_ok=True), which caching requires. The original refused to run
     twice into the same directory.
  4. A fail-closed check that no scene still contains an unfilled <PLACEHOLDER>, so
     the template cannot be narrated verbatim into a shipped video.

The timing-preview mode may synthesize and measure narration while the source is
NOT_CONFIGURED. It cannot capture or compose a candidate. Final production remains
gated on READY_OWNER_VERIFIED.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import pathlib
import re
import subprocess
import time
import urllib.error
import urllib.request


ROOT = pathlib.Path(os.environ["LASTTAKE_VIDEO_ROOT"])
SPEC = pathlib.Path(__file__).with_name("narration.json")
OUT = ROOT / "narration"
TAIL_SECONDS = 0.65
CACHE_SCHEMA_VERSION = "lasttake-narration-cache/v2"
ELEVENLABS_VOICE_SETTINGS = {
    "stability": 0.45,
    "similarity_boost": 0.8,
    "use_speaker_boost": True,
}

# Historical names across the fourteen entries, in precedence order. Whichever is set
# is used. The value is never printed and never written to a receipt.
ELEVENLABS_KEY_ENV_NAMES = ("ELEVENLABS_API_KEY", "XI_API_KEY", "ELEVEN_LABS_KEY")


def run(args: list[str]) -> str:
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def duration(path: pathlib.Path) -> float:
    return float(
        run(
            [
                os.environ["FFPROBE"],
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ]
        )
    )


def timestamp(value: float) -> str:
    millis = round(max(0.0, value) * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    seconds, millis = divmod(millis, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def wrapped(text: str, width: int = 66) -> str:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if line and len(candidate) > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    if len(lines) <= 2:
        return "\n".join(lines)
    midpoint = max(1, len(words) // 2)
    return " ".join(words[:midpoint]) + "\n" + " ".join(words[midpoint:])


def elevenlabs_key() -> str:
    for name in ELEVENLABS_KEY_ENV_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise SystemExit(
        "no ElevenLabs key: set one of " + ", ".join(ELEVENLABS_KEY_ENV_NAMES)
    )


def synthesize_elevenlabs(text: str, spec: dict[str, object], retries: int = 3) -> bytes:
    """Body copied from upgradedev/archon-qwen-autopilot, 2a85b4f, file
    scripts/build_video.py, function synth_elevenlabs (lines 313-338). Changed only to
    read the voice and model from the narration spec and to return the bytes instead of
    writing the file."""
    config = spec.get("elevenLabs")
    if not isinstance(config, dict):
        raise SystemExit("provider is elevenlabs but the spec has no elevenLabs block")
    voice_id = str(config.get("voiceId", ""))
    model_id = str(config.get("modelId", "eleven_multilingual_v2"))
    output_format = str(config.get("outputFormat", "mp3_44100_128"))
    if not re.fullmatch(r"[A-Za-z0-9]{16,40}", voice_id):
        raise SystemExit("elevenLabs.voiceId is missing or malformed")
    if not re.fullmatch(r"[a-z0-9_]{4,40}", model_id):
        raise SystemExit("elevenLabs.modelId is malformed")
    if not re.fullmatch(r"[a-z0-9_]{4,32}", output_format):
        raise SystemExit("elevenLabs.outputFormat is malformed")
    key = elevenlabs_key()
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        f"?output_format={output_format}"
    )
    body = json.dumps(
        {
            "text": text,
            "model_id": model_id,
            "voice_settings": ELEVENLABS_VOICE_SETTINGS,
        }
    ).encode("utf-8")
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url,
                data=body,
                headers={
                    "xi-api-key": key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                data = response.read()
            if len(data) < 3000:
                raise RuntimeError(f"tiny audio ({len(data)} bytes)")
            return data
        except Exception as error:  # noqa: BLE001
            last = error
            time.sleep(2 * (attempt + 1))
    raise SystemExit(f"ElevenLabs failed after {retries} tries: {last}")


def voice_signature(spec: dict[str, object], provider: str) -> str:
    """Everything except the text that changes how a scene sounds. Part of the cache
    key, so changing the voice re-synthesizes every scene rather than mixing voices."""
    if provider == "elevenlabs":
        fields: dict[str, object] = {
            "cacheSchema": CACHE_SCHEMA_VERSION,
            "elevenLabs": spec.get("elevenLabs"),
            "voiceSettings": ELEVENLABS_VOICE_SETTINGS,
        }
    else:
        fields = {
            key: spec.get(key)
            for key in ("languageCode", "voice", "speakingRate")
        }
        fields["cacheSchema"] = CACHE_SCHEMA_VERSION
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))


def cache_key(speech: str, spec: dict[str, object], provider: str) -> str:
    payload = json.dumps(
        {
            "provider": provider,
            "speech": speech,
            "voice": voice_signature(spec, provider),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cached_key(sidecar: pathlib.Path) -> str | None:
    try:
        recorded = json.loads(sidecar.read_text(encoding="utf-8")).get("cacheKey")
    except (OSError, ValueError):
        return None
    return recorded if isinstance(recorded, str) else None


def file_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def cached_audio_sha256(sidecar: pathlib.Path) -> str | None:
    try:
        recorded = json.loads(sidecar.read_text(encoding="utf-8")).get("audioSha256")
    except (OSError, ValueError):
        return None
    return recorded if isinstance(recorded, str) and re.fullmatch(r"[a-f0-9]{64}", recorded) else None


def synthesize(text: str, spec: dict[str, object], token: str) -> bytes:
    if str(spec.get("provider", "google")) == "elevenlabs":
        return synthesize_elevenlabs(text, spec)
    return synthesize_google(text, spec, token)


def synthesize_google(text: str, spec: dict[str, object], token: str) -> bytes:
    body = json.dumps(
        {
            "input": {"text": text},
            "voice": {
                "languageCode": spec["languageCode"],
                "name": spec["voice"],
            },
            "audioConfig": {
                "audioEncoding": "MP3",
                "speakingRate": spec["speakingRate"],
                "pitch": -1.0,
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://texttospeech.googleapis.com/v1/text:synthesize",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"Cloud TTS failed with HTTP {error.code}") from error
    encoded = payload.get("audioContent")
    if not isinstance(encoded, str) or len(encoded) < 32:
        raise SystemExit("Cloud TTS returned no bounded audio payload")
    return base64.b64decode(encoded, validate=True)


def main() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    mode = os.environ.get("LASTTAKE_NARRATION_MODE", "final").strip()
    if mode not in {"preview", "final"}:
        raise SystemExit("LASTTAKE_NARRATION_MODE must be preview or final")
    status = spec.get("recording_status")
    if mode == "final" and status != "READY_OWNER_VERIFIED":
        raise SystemExit("NOT_CONFIGURED: owner must approve narration, measured timing and the exact live journey before final synthesis.")
    if mode == "preview" and status not in {"NOT_CONFIGURED", "READY_OWNER_VERIFIED"}:
        raise SystemExit("timing preview requires NOT_CONFIGURED or READY_OWNER_VERIFIED source")
    segments = spec.get("segments")
    if spec.get("schemaVersion") != "lasttake.submission-video/v1" or not isinstance(segments, list):
        raise SystemExit("narration contract is invalid")
    provider = str(spec.get("provider", "google"))
    if provider not in ("google", "elevenlabs"):
        raise SystemExit("provider must be google or elevenlabs")
    forced = {
        item.strip()
        for item in os.environ.get("NARRATION_FORCE", "").split(",")
        if item.strip()
    }
    token = ""
    if provider == "google":
        token = run(["gcloud", "auth", "print-access-token"])
        if not token or len(token) > 4096:
            raise SystemExit("bounded Google access token is unavailable")
    OUT.mkdir(parents=True, exist_ok=True)
    timing: list[dict[str, object]] = []
    cues: list[tuple[float, float, str]] = []
    cue_windows: list[dict[str, object]] = []
    offset = 0.0
    for index, segment in enumerate(segments, start=1):
        identifier = segment.get("id")
        speech = segment.get("speechText")
        caption = segment.get("captionText")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z-]{1,24}", identifier):
            raise SystemExit("scene identifier is invalid")
        if not all(isinstance(value, str) and 20 <= len(value) <= 800 for value in (speech, caption)):
            raise SystemExit(f"scene text is invalid: {identifier}")
        if "<" in f"{speech}{caption}" or ">" in f"{speech}{caption}":
            raise SystemExit(
                f"scene {identifier} still contains a <PLACEHOLDER>; fill it in before synthesis"
            )
        audio = OUT / f"{index:02d}-{identifier}.mp3"
        sidecar = OUT / f"{index:02d}-{identifier}.cache.json"
        key = cache_key(speech, spec, provider)
        reuse = (
            identifier not in forced
            and "all" not in forced
            and audio.is_file()
            and cached_key(sidecar) == key
            and cached_audio_sha256(sidecar) == file_sha256(audio)
        )
        if reuse:
            print(f"reused {audio.name}")
        else:
            audio.write_bytes(synthesize(speech, spec, token))
            audio_digest = file_sha256(audio)
            sidecar.write_text(
                json.dumps(
                    {"cacheKey": key, "provider": provider, "audioSha256": audio_digest},
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            print(f"synthesized {audio.name}")
        audio_digest = file_sha256(audio)
        seconds = duration(audio)
        if seconds < 3 or seconds > 40:
            raise SystemExit(f"scene audio duration is unsafe: {identifier}")
        hold = seconds + TAIL_SECONDS
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", caption) if part.strip()]
        spoken_sentences = [
            part.strip() for part in re.split(r"(?<=[.!?])\s+", speech) if part.strip()
        ]
        if len(sentences) != len(spoken_sentences):
            raise SystemExit(
                f"scene {identifier} must pair each caption sentence with one spoken sentence"
            )
        weight = sum(len(part) for part in spoken_sentences) or 1
        cursor = 0.0
        for sentence, spoken_sentence in zip(sentences, spoken_sentences, strict=True):
            share = seconds * len(spoken_sentence) / weight
            cues.append((offset + cursor, offset + cursor + share, wrapped(sentence)))
            cue_windows.append(
                {
                    "sceneId": identifier,
                    "startSeconds": round(offset + cursor, 3),
                    "endSeconds": round(offset + cursor + share, 3),
                    "text": sentence,
                }
            )
            cursor += share
        timing.append(
            {
                "id": identifier,
                "audio": audio.name,
                "durationSeconds": round(seconds, 3),
                "holdSeconds": round(hold, 3),
                "startSeconds": round(offset, 3),
                "cacheHit": reuse,
                "audioSha256": audio_digest,
            }
        )
        offset += hold
    if not 90 <= offset < 175:
        raise SystemExit(f"narration must be 90-174 seconds, observed {offset:.3f}")
    (OUT / "timing.json").write_text(
        json.dumps(
            {
                "schemaVersion": "lasttake.submission-video-timing/v1",
                "mode": mode,
                "narrationSourceSha256": hashlib.sha256(SPEC.read_bytes()).hexdigest(),
                "totalSeconds": round(offset, 3),
                "scenes": timing,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    srt: list[str] = []
    for number, (start, end, text) in enumerate(cues, start=1):
        srt.extend([str(number), f"{timestamp(start)} --> {timestamp(end)}", text, ""])
    (OUT / "captions.en.srt").write_text("\n".join(srt), encoding="utf-8")
    (OUT / "caption-windows.json").write_text(
        json.dumps(
            {
                "schemaVersion": "lasttake.submission-video-caption-windows/v1",
                "scenes": [scene["id"] for scene in timing],
                "windows": cue_windows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    token = ""
    print(f"Generated {len(timing)} {mode} scenes across {offset:.3f} seconds")


if __name__ == "__main__":
    main()
