from __future__ import annotations

from .store import Store


class IdentityService:
    def __init__(self, store: Store):
        self.store = store

    def create_node(self, **values):
        return self.store.create_node(**values)

    def update_node(self, **values):
        return self.store.update_node(**values)

    def replace_connection(self, **values):
        return self.store.replace_connection(**values)

    def handoff_work(self, **values):
        return self.store.handoff_work(**values)

