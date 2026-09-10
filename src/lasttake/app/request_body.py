"""Bound the gateway body before decoding/parsing or touching saved state."""
from __future__ import annotations

import base64
import json


MAX_BODY_BYTES = 128_000


class BodyError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def parse_body(event: dict) -> dict:
    raw = event.get("body")
    if raw is None:
        raw = "{}"
    encoded = event.get("isBase64Encoded", False)
    if not isinstance(raw, str) or type(encoded) is not bool:
        raise BodyError("body must be JSON text with a boolean base64 flag")
    # Bound encoded input before allocating decoded bytes. UTF-8 can only
    # increase a plain string's byte length, so the character check is safe.
    limit = 4 * ((MAX_BODY_BYTES + 2) // 3) if encoded else MAX_BODY_BYTES
    if len(raw) > limit:
        raise BodyError(f"body exceeds {MAX_BODY_BYTES} decoded UTF-8 bytes", 413)
    try:
        data = base64.b64decode(raw, validate=True) if encoded else raw.encode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise BodyError("body must contain valid base64 and UTF-8 text") from exc
    if len(data) > MAX_BODY_BYTES:
        raise BodyError(f"body exceeds {MAX_BODY_BYTES} decoded UTF-8 bytes", 413)
    try:
        text = data.decode("utf-8")
        body = json.loads(text) if text.strip() else {}
    except (ValueError, RecursionError) as exc:
        raise BodyError("body must be JSON") from exc
    if not isinstance(body, dict):
        raise BodyError("body must be a JSON object")
    return body
