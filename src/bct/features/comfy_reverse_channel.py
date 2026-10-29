"""Bounded, operation-scoped reverse ComfyUI transport over an existing host session."""
from __future__ import annotations
from dataclasses import dataclass, field
from threading import Condition, Event
from time import monotonic
import secrets

class ComfyTransportUnknown(RuntimeError):
    pass

@dataclass
class _Pending:
    work_id: str
    operation_id: str
    arguments: dict
    generation: int
    done: Event = field(default_factory=Event)
    response: dict | None = None
    delivered: bool = False

class ComfyReverseChannel:
    def __init__(self):
        self._lock = Condition()
        self._owner: tuple[str,str,int] | None = None
        self._generation = 0
        self._last_seen = 0.0
        self._pending: dict[str,_Pending] = {}

    def bind(self, work_id: str, session_id: str) -> int:
        if not work_id or not session_id:
            raise ValueError("COMFY_OWNER_INVALID")
        with self._lock:
            if self._owner is not None and monotonic() - self._last_seen > 35:
                self._owner = None
                for pending in self._pending.values():
                    pending.done.set()
            if self._owner is not None:
                if self._owner[:2] == (work_id, session_id):
                    self._last_seen = monotonic()
                    return self._generation
                raise PermissionError("COMFY_CHANNEL_ALREADY_OWNED")
            self._generation += 1
            self._owner = (work_id, session_id, self._generation)
            self._last_seen = monotonic()
            self._lock.notify_all()
            return self._generation

    def disconnect(self, work_id: str, session_id: str, generation: int):
        with self._lock:
            self._check(work_id, session_id, generation)
            self._owner = None
            for p in self._pending.values():
                p.done.set()
            self._lock.notify_all()

    def _check(self, work_id: str, session_id: str, generation: int):
        if self._owner != (work_id, session_id, generation):
            raise PermissionError("COMFY_CHANNEL_SESSION_STALE")

    def read_canvas(self, arguments: dict) -> dict:
        # This is invoked only after the normal BCT feature Work/Operation gate.
        operation_id = arguments.get("_operation_id")
        work_id = arguments.get("_work_id")
        if not operation_id or not work_id:
            raise ValueError("COMFY_OPERATION_ID_REQUIRED")
        with self._lock:
            if self._owner is None or self._owner[0] != work_id:
                raise PermissionError("COMFY_CHANNEL_WORK_NOT_BOUND")
            if operation_id in self._pending:
                raise ComfyTransportUnknown("COMFY_DUPLICATE_OPERATION_NO_RETRY")
            generation = self._generation
            p = _Pending(work_id, operation_id, dict(arguments), generation)
            self._pending[operation_id] = p
            self._lock.notify_all()
        try:
            if not p.done.wait(10):
                raise ComfyTransportUnknown("COMFY_REVERSE_TIMEOUT_NO_RETRY")
            with self._lock:
                if self._owner is None or self._generation != p.generation:
                    raise ComfyTransportUnknown("COMFY_REVERSE_DISCONNECTED_NO_RETRY")
                if p.response is None:
                    raise ComfyTransportUnknown("COMFY_REVERSE_REPLY_MISSING")
                return dict(p.response)
        finally:
            with self._lock:
                self._pending.pop(operation_id,None)

    def take(self, work_id: str, session_id: str, generation: int, wait_seconds: float = 0) -> dict | None:
        if not 0 <= wait_seconds <= 20:
            raise ValueError("COMFY_WAIT_INVALID")
        with self._lock:
            self._check(work_id,session_id,generation)
            self._last_seen = monotonic()
            deadline=monotonic()+wait_seconds
            while True:
                for p in self._pending.values():
                    if p.work_id == work_id and p.generation == generation and not p.delivered:
                        p.delivered=True
                        return {"operation_id":p.operation_id,"arguments":{k:v for k,v in p.arguments.items() if not k.startswith("_")},"generation":generation}
                remaining=deadline-monotonic()
                if remaining<=0:return None
                self._lock.wait(remaining)
                self._check(work_id,session_id,generation)

    def submit(self,work_id:str,session_id:str,generation:int,operation_id:str,response:dict)->bool:
        with self._lock:
            self._check(work_id,session_id,generation)
            if not isinstance(response,dict) or response.get("requestId") != operation_id or response.get("ok") is not True:
                return False
            p=self._pending.get(operation_id)
            if p is None or p.work_id!=work_id or p.generation!=generation or not p.delivered or p.done.is_set():
                return False
            p.response=dict(response)
            p.done.set()
            return True
