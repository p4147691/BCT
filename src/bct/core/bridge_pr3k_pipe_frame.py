"""PR3-k: production-disabled framing for a future Bridge-only pipe relay.

This module does not create a pipe, resolve a binding, load a secret, or call
Core ingress.  It only preserves one canonical PR3-e peer frame inside a
strict, length-prefixed transport envelope for isolated tests.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import struct

from .bridge_pr3e_peer_adapter import MAX_PEER_FRAME_BYTES


PIPE_FRAME_VERSION = 1
MAX_PIPE_FRAME_BYTES = MAX_PEER_FRAME_BYTES * 2
_FIELDS = frozenset(("version", "operation", "peer_frame_b64"))
_OPERATIONS = frozenset(("peer_frame",))


class PipeFrameError(ValueError):
    """A peer-visible transport denial that contains no frame body."""


@dataclass(frozen=True)
class PipeFrame:
    operation: str
    peer_frame: bytes


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("DUPLICATE_FIELD")
        value[key] = item
    return value


def _deny() -> PipeFrameError:
    return PipeFrameError("PIPE_FRAME_DENIED")


def _valid_peer_frame(value: object) -> bool:
    return isinstance(value, bytes) and 0 < len(value) <= MAX_PEER_FRAME_BYTES


def encode_peer_frame(peer_frame: bytes) -> bytes:
    """Encode one canonical peer frame without inspecting or authorizing it."""
    if not _valid_peer_frame(peer_frame):
        raise ValueError("PIPE_FRAME_ARGUMENT_DENIED")
    body = json.dumps(
        {"version": PIPE_FRAME_VERSION, "operation": "peer_frame",
         "peer_frame_b64": base64.b64encode(peer_frame).decode("ascii")},
        separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")
    if len(body) > MAX_PIPE_FRAME_BYTES:
        raise ValueError("PIPE_FRAME_ARGUMENT_DENIED")
    return struct.pack("<I", len(body)) + body


def decode_peer_frame(frame: bytes) -> PipeFrame:
    """Strictly decode one complete relay frame; never accept trailing bytes."""
    if not isinstance(frame, bytes) or len(frame) < 4:
        raise _deny()
    size = struct.unpack("<I", frame[:4])[0]
    if not 0 < size <= MAX_PIPE_FRAME_BYTES:
        raise _deny()
    if len(frame) != 4 + size:
        raise _deny()
    try:
        value = json.loads(
            frame[4:].decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NONFINITE")),
        )
        if (not isinstance(value, dict) or set(value) != _FIELDS
                or type(value["version"]) is not int
                or value["version"] != PIPE_FRAME_VERSION
                or value["operation"] not in _OPERATIONS
                or not isinstance(value["peer_frame_b64"], str)):
            raise ValueError("FRAME_SCHEMA")
        peer_frame = base64.b64decode(value["peer_frame_b64"].encode("ascii"), validate=True)
        if (not _valid_peer_frame(peer_frame)
                or base64.b64encode(peer_frame).decode("ascii") != value["peer_frame_b64"]):
            raise ValueError("FRAME_PAYLOAD")
        return PipeFrame(value["operation"], peer_frame)
    except (UnicodeError, ValueError, TypeError, OverflowError, RecursionError):
        raise _deny() from None
