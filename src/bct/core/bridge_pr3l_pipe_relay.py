"""PR3-l: production-disabled composition for a verified Bridge pipe peer.

The relay deliberately owns no listener, credential path, registry entry, or
Chrome integration.  A caller must inject both a Bridge-only binding provider
and an operating-system client verifier.  The verifier runs before the relay
reads request bytes; the attested executable digest must then match the
canonical peer frame and its active binding before PR3-c ingress is reached.
"""
from __future__ import annotations

from typing import Callable, Protocol

from .bridge_pr3e_peer_adapter import (
    PeerAdapter,
    PeerBinding,
    PeerBindingProvider,
    parse_peer_frame,
)
from .bridge_pr3k_pipe_frame import PipeFrameError, decode_peer_frame
from .models import ConflictError


class PipeClientVerifier(Protocol):
    """Attest the already-connected pipe client without trusting its payload."""

    def verified_client_sha256(self, connection: object) -> str | None:
        """Return the connected executable digest, or ``None`` when denied."""


class PipeRelayUnknownEffect(RuntimeError):
    """Ingress completed but the result transport outcome is unknown."""


def _deny() -> ConflictError:
    return ConflictError("PIPE_RELAY_DENIED")


def _verified_sha256(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != 64:
        return None
    lowered = value.lower()
    if any(character not in "0123456789abcdef" for character in lowered):
        return None
    return lowered


class PipeRelay:
    """Join verified pipe identity and the existing canonical ingress stack."""

    def __init__(self, *, peer_id: str, binding_provider: PeerBindingProvider,
                 client_verifier: PipeClientVerifier):
        if not isinstance(peer_id, str) or not 0 < len(peer_id) <= 128:
            raise ValueError("PIPE_RELAY_PEER_ID_REQUIRED")
        if binding_provider is None:
            raise ValueError("PIPE_RELAY_BINDING_PROVIDER_REQUIRED")
        if client_verifier is None:
            raise ValueError("PIPE_RELAY_CLIENT_VERIFIER_REQUIRED")
        self._peer_id = peer_id
        self._binding_provider = binding_provider
        self._client_verifier = client_verifier
        self._peer_adapter = PeerAdapter(binding_provider)

    def dispatch(self, store, *, connection: object,
                 read_frame: Callable[[], bytes],
                 publish_result: Callable[[object], None]):
        """Verify, read once, dispatch once, and publish without retrying.

        A publish failure occurs after Core may have committed an effect.  It
        is therefore reported as UNKNOWN and this relay never replays the
        request.  Recovery must use the existing durable receipt contracts.
        """
        if not callable(read_frame) or not callable(publish_result):
            raise _deny()
        try:
            client_sha256 = _verified_sha256(
                self._client_verifier.verified_client_sha256(connection)
            )
        except Exception:
            raise _deny() from None
        if client_sha256 is None:
            raise _deny()

        # The endpoint is bound to one provisioned peer, so the active binding
        # and its approved executable can be checked before any request bytes
        # are read from the connection.
        try:
            binding = self._binding_provider.resolve_peer_binding(self._peer_id)
        except Exception:
            raise _deny() from None
        if (not isinstance(binding, PeerBinding)
                or binding.peer_id != self._peer_id
                or _verified_sha256(binding.launcher_sha256) != client_sha256):
            raise _deny()

        # Do not touch attacker-controlled request bytes until the connected
        # process has been attested by the injected OS boundary.
        try:
            transport = read_frame()
        except Exception:
            raise _deny() from None
        try:
            pipe_frame = decode_peer_frame(transport)
            peer_frame = parse_peer_frame(pipe_frame.peer_frame)
        except (PipeFrameError, ConflictError):
            raise _deny() from None
        if (peer_frame.peer_id != self._peer_id
                or peer_frame.launcher_sha256 != client_sha256):
            raise _deny()

        try:
            result = self._peer_adapter.ingress(store, pipe_frame.peer_frame)
        except ConflictError:
            raise _deny() from None

        try:
            publish_result(result)
        except Exception:
            raise PipeRelayUnknownEffect("PIPE_RELAY_EFFECT_UNKNOWN") from None
        return result
