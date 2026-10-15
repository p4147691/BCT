"""Host-side encoder for the future PR3-e peer adapter.

It neither loads credentials nor connects to BCT. A future provisioned Host
must pass an OS-backed secret explicitly, then deliver the resulting bytes over
a separately protected local IPC path.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json


ORIGIN = "chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/"


def _valid_sha256(value):
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _proof_input(*, peer_id, binding_generation, launcher_sha256, origin, sequence, envelope):
    return json.dumps(
        ["bct-bridge-peer-adapter-v1", peer_id, binding_generation,
         launcher_sha256, origin, sequence, envelope.hex()],
        separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")


def build_peer_frame(*, secret, peer_id, binding_generation, launcher_sha256,
                     origin, sequence, envelope):
    """Return canonical PR3-e outer-frame bytes without retaining ``secret``."""
    if (not isinstance(secret, bytes) or len(secret) != 32
            or not isinstance(peer_id, str) or not 0 < len(peer_id) <= 128
            or type(binding_generation) is not int or not 1 <= binding_generation <= 2 ** 63 - 1
            or not _valid_sha256(launcher_sha256) or origin != ORIGIN
            or type(sequence) is not int or not 1 <= sequence <= 2 ** 63 - 1
            or not isinstance(envelope, bytes) or not 0 < len(envelope) <= 8192):
        raise ValueError("PEER_FRAME_ARGUMENT_DENIED")
    proof = hmac.new(
        secret,
        _proof_input(peer_id=peer_id, binding_generation=binding_generation,
                     launcher_sha256=launcher_sha256, origin=origin,
                     sequence=sequence, envelope=envelope),
        hashlib.sha256,
    ).hexdigest()
    return json.dumps(
        {"version": 1, "peer_id": peer_id, "binding_generation": binding_generation,
         "launcher_sha256": launcher_sha256, "origin": origin, "sequence": sequence,
         "envelope_b64": base64.b64encode(envelope).decode("ascii"), "proof": proof},
        separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
