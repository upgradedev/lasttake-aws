"""Content addressing and sealed records.

Every artifact this system reasons about is identified by the SHA-256 of its
bytes, and every record it emits is sealed with the SHA-256 of its own
canonical JSON. A finding that cites a source cites that source's digest, so a
reader can re-hash the file and tell whether the finding is still about the
thing it was written about.

Pre-existing component. ``sha256_bytes``, ``canonical_json`` and the sealed
manifest approach are carried from ClaimScene (MIT, same author) at
``src/claimscene/provenance.py``, which in turn shares them with Cinemory.
Disclosed in the README under "Pre-existing components".

Nothing in this module imports an SDK. It is arithmetic on bytes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

#: Key that holds a record's own digest. Excluded when the digest is computed,
#: because a hash cannot cover itself.
SEAL_KEY = "record_sha256"


def sha256_bytes(data: bytes) -> str:
    """Digest of raw bytes. Used for source artifacts."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_json(obj: Any) -> bytes:
    """Sorted-key, whitespace-free JSON.

    Two records that differ only in key order or spacing must produce the same
    digest, otherwise a seal proves nothing about content.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_of(obj: Any) -> str:
    """Digest of a record, ignoring any seal already present."""
    if isinstance(obj, dict):
        obj = {k: v for k, v in obj.items() if k != SEAL_KEY}
    return sha256_bytes(canonical_json(obj))


def seal(record: dict) -> dict:
    """Return ``record`` with its own digest attached under :data:`SEAL_KEY`."""
    sealed = {k: v for k, v in record.items() if k != SEAL_KEY}
    sealed[SEAL_KEY] = digest_of(sealed)
    return sealed


def verify_seal(record: dict) -> bool:
    """True when the record's contents still match the digest it carries.

    A record with no seal is not verifiable, so it is false. Absent evidence is
    never a pass. That rule is the spine of this product and it applies to the
    product's own records first.
    """
    claimed = record.get(SEAL_KEY)
    if not claimed:
        return False
    return claimed == digest_of(record)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def short_digest(digest: str, length: int = 12) -> str:
    """First ``length`` characters, for display only. Never for comparison."""
    return digest[:length]
