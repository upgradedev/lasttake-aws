"""Bounded registration pages; no mutation or deletion of historical arrays."""
from __future__ import annotations

import base64
import json

PAGE_SIZE = 10
MAX_PAGE_SIZE = 20
WINDOW_BYTES = 65_536


class HistoryChanged(Exception):
    pass


class HistoryUnavailable(Exception):
    pass


def page_size(value):
    if type(value) is not int or not 1 <= value <= MAX_PAGE_SIZE:
        raise ValueError("page_size must be a whole number from 1 to 20")
    return value


def decode_cursor(value, owner):
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= 1024:
        raise ValueError("Invalid saved-history cursor. Refresh the run list.")
    try:
        data = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        if (not isinstance(data, dict) or set(data) != {"v", "owner", "position"}
                or type(data["v"]) is not int or data["v"] != 1 or data["owner"] != owner
                or not isinstance(data["position"], dict)):
            raise ValueError()
        return data["position"]
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid saved-history cursor. Refresh the run list.") from exc


def encode_cursor(position, owner):
    if position is None:
        return None
    return base64.urlsafe_b64encode(json.dumps({"v": 1, "owner": owner, "position": position},
                                             separators=(",", ":")).encode()).decode()


def array_end(position, size, version):
    if position is None:
        return size
    if (set(position) != {"kind", "before", "version"} or position["kind"] != "array"
            or type(position["before"]) is not int or not 0 < position["before"] <= size
            or not isinstance(position["version"], str) or len(position["version"]) > 256):
        raise ValueError("Invalid saved-history position. Refresh the run list.")
    if position["version"] != version:
        raise HistoryChanged("Saved history changed. Refresh the run list before loading older runs.")
    return position["before"]


def array_page(data, start, limit, version):
    """Read complete objects backwards from a bounded window ending at a boundary.

    Braces in quoted strings and nested values are not record boundaries. A
    record larger than the window is refused, never silently skipped or rewritten.
    """
    page_size(limit)
    if len(data) > WINDOW_BYTES:
        raise HistoryUnavailable("Saved history exceeded the bounded read.")
    rows, depth, quoted, end, boundary = [], 0, False, None, None
    for index in range(len(data) - 1, -1, -1):
        char = data[index]
        if char == 34:
            prior = index - 1
            while prior >= 0 and data[prior] == 92:
                prior -= 1
            if (index - prior - 1) % 2 == 0:
                quoted = not quoted
        if quoted or char == 34:
            continue
        if depth == 0 and char in b" \r\n\t,[]":
            continue
        if char in b"}]":
            if depth == 0:
                end = index + 1
            depth += 1
        elif char in b"{[":
            depth -= 1
            if depth == 0:
                try:
                    row = json.loads(data[index:end])
                except (ValueError, RecursionError) as exc:
                    raise HistoryUnavailable("Saved history could not be read.") from exc
                if not isinstance(row, dict):
                    raise HistoryUnavailable("Saved history could not be read.")
                boundary = index
                if row.get("kind") == "ui.run.created":
                    rows.append(row)
                if len(rows) == limit:
                    break
        elif depth == 0:
            raise HistoryUnavailable("Saved history could not be read.")
    if boundary is None:
        if start or data.strip(b" \r\n\t[]"):
            raise HistoryUnavailable("Saved history record exceeds the bounded read or is malformed.")
        return [], None
    more = start > 0 or bool(data[:boundary].strip(b" \r\n\t,[]"))
    if start == 0 and len(rows) < limit and (depth or quoted):
        raise HistoryUnavailable("Saved history could not be read.")
    return rows, {"kind": "array", "before": start + boundary, "version": version} if more else None
