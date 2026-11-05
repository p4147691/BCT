"""PR3-o: explicit, production-disabled Bridge listener composition.

This module owns no pipe name, credential path, process verifier, listener
implementation, or runtime entry point.  It composes only explicitly injected
PR3-f/PR3-h dependencies with PR3-l.  Normal Native Messaging code cannot
construct or start it accidentally.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from .bridge_pr3e_peer_adapter import PeerBinding
from .bridge_pr3f_binding_lifecycle import BindingLifecycle
from .bridge_pr3h_dpapi_file_store import DpapiFileSecretStore
from .bridge_pr3l_pipe_relay import PipeClientVerifier, PipeRelay


class ListenerEndpoint(Protocol):
    """Injected bounded transport; the Windows implementation owns policy."""

    def start(self, *, timeout_seconds: float) -> None: ...
    def accept(self, *, timeout_seconds: float) -> object: ...
    def stop(self, *, timeout_seconds: float) -> None: ...


class ListenerConnection(Protocol):
    """One already-connected endpoint handed to the accepted PR3-l relay."""

    def read_frame(self, *, timeout_seconds: float) -> bytes: ...
    def publish_result(self, result: object, *, timeout_seconds: float) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class ListenerConfig:
    enabled: bool = False
    fixture_only: bool = False
    peer_id: str = ""
    startup_timeout_seconds: float = 10.0
    accept_timeout_seconds: float = 15.0
    shutdown_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 15.0
    publish_timeout_seconds: float = 15.0


def _bounded(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value <= 30


class ProductionDisabledListener:
    """Lifecycle shell around one injected endpoint and the existing relay.

    There is deliberately no default constructor path.  The caller must opt in
    twice (``enabled`` and ``fixture_only``) and provide the exact accepted
    lifecycle, DPAPI store, verifier and endpoint objects.
    """

    def __init__(self, config: ListenerConfig, *, binding_lifecycle: BindingLifecycle,
                 secret_store: DpapiFileSecretStore,
                 client_verifier: PipeClientVerifier,
                 endpoint: ListenerEndpoint):
        if not isinstance(config, ListenerConfig):
            raise ValueError("BRIDGE_LISTENER_CONFIG_REQUIRED")
        if not isinstance(binding_lifecycle, BindingLifecycle):
            raise ValueError("BRIDGE_LISTENER_BINDING_LIFECYCLE_REQUIRED")
        if not isinstance(secret_store, DpapiFileSecretStore):
            raise ValueError("BRIDGE_LISTENER_DPAPI_STORE_REQUIRED")
        if not binding_lifecycle.uses_secret_store(secret_store):
            raise ValueError("BRIDGE_LISTENER_STORE_MISMATCH")
        if client_verifier is None or endpoint is None:
            raise ValueError("BRIDGE_LISTENER_BOUNDARY_REQUIRED")
        if (not isinstance(config.peer_id, str) or not 0 < len(config.peer_id) <= 128
                or not all(_bounded(value) for value in (
                    config.startup_timeout_seconds, config.accept_timeout_seconds,
                    config.shutdown_timeout_seconds, config.read_timeout_seconds,
                    config.publish_timeout_seconds))):
            raise ValueError("BRIDGE_LISTENER_CONFIG_DENIED")
        self._config = config
        self._binding_lifecycle = binding_lifecycle
        self._endpoint = endpoint
        self._relay = PipeRelay(peer_id=config.peer_id,
                                binding_provider=binding_lifecycle,
                                client_verifier=client_verifier)
        self._started = False
        self._poisoned = False
        self._dispatch_lock = Lock()

    @property
    def started(self) -> bool:
        return self._started

    def start(self) -> None:
        if not self._config.enabled or not self._config.fixture_only:
            raise RuntimeError("BRIDGE_LISTENER_DISABLED")
        if self._started:
            raise RuntimeError("BRIDGE_LISTENER_ALREADY_STARTED")
        if self._poisoned:
            raise RuntimeError("BRIDGE_LISTENER_CLEANUP_UNKNOWN")
        # READY belongs after the durable binding is known active.  PipeRelay
        # repeats this lookup immediately before every payload read.
        try:
            binding = self._binding_lifecycle.resolve_peer_binding(self._config.peer_id)
        except Exception:
            raise RuntimeError("BRIDGE_LISTENER_BINDING_DENIED") from None
        if not isinstance(binding, PeerBinding):
            raise RuntimeError("BRIDGE_LISTENER_BINDING_DENIED")
        try:
            self._endpoint.start(timeout_seconds=self._config.startup_timeout_seconds)
        except Exception:
            # A partially-created pipe/process belongs to the injected endpoint.
            # Ask it to remove only its own receipt-backed resources.
            try:
                self._endpoint.stop(
                    timeout_seconds=self._config.shutdown_timeout_seconds)
            except Exception:
                self._poisoned = True
                raise RuntimeError("BRIDGE_LISTENER_CLEANUP_UNKNOWN") from None
            raise RuntimeError("BRIDGE_LISTENER_START_DENIED") from None
        self._started = True

    def dispatch_once(self, store):
        if not self._started:
            raise RuntimeError("BRIDGE_LISTENER_NOT_STARTED")
        if not self._dispatch_lock.acquire(blocking=False):
            raise RuntimeError("BRIDGE_LISTENER_DISPATCH_BUSY")
        connection = None
        try:
            connection = self._endpoint.accept(
                timeout_seconds=self._config.accept_timeout_seconds)
            if connection is None or not all(callable(getattr(connection, name, None))
                                             for name in ("read_frame", "publish_result", "close")):
                raise RuntimeError("BRIDGE_LISTENER_ACCEPT_DENIED")
            # PR3-l performs verifier-before-read, current binding/proof/generation
            # fencing, exact PR3-k decoding, and UNKNOWN-without-retry semantics.
            return self._relay.dispatch(
                store, connection=connection,
                read_frame=lambda: connection.read_frame(
                    timeout_seconds=self._config.read_timeout_seconds),
                publish_result=lambda result: connection.publish_result(
                    result, timeout_seconds=self._config.publish_timeout_seconds),
            )
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    self._poisoned = True
            self._dispatch_lock.release()

    def stop(self) -> None:
        if not self._started:
            return
        try:
            self._endpoint.stop(
                timeout_seconds=self._config.shutdown_timeout_seconds)
        except Exception:
            self._poisoned = True
            raise RuntimeError("BRIDGE_LISTENER_CLEANUP_UNKNOWN") from None
        finally:
            self._started = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, _kind, _value, _traceback):
        self.stop()
        return False
