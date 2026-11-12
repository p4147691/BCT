"""Commit-driven invalidation for Monitor's display roster."""

import asyncio
import threading


DISPLAY_TABLES = frozenset({
    "conversation_network_projects", "conversation_network_conversations",
    "conversation_network_memberships", "conversation_network_membership_tags",
    "conversation_network_node_labels", "dot_node_info", "codex_surface_nodes",
    "github_run_inbox", "github_run_inbox_recipients",
})


class MonitorEvents:
    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers = set()
        self.revision = 0

    def publish(self):
        with self._lock:
            self.revision += 1
            for loop, ready in self._subscribers:
                if not loop.is_closed():
                    loop.call_soon_threadsafe(ready.set)

    async def stream(self):
        ready = asyncio.Event()
        subscriber = (asyncio.get_running_loop(), ready)
        with self._lock:
            self._subscribers.add(subscriber)
        try:
            # Reconcile once when connecting or reconnecting. Subscribe first
            # so commits during that snapshot also schedule another update.
            yield "data: changed\n\n"
            while True:
                await ready.wait()
                ready.clear()
                await asyncio.sleep(0.06)
                # Commits during the coalescing window belong to this event.
                ready.clear()
                yield "data: changed\n\n"
        finally:
            with self._lock:
                self._subscribers.discard(subscriber)
