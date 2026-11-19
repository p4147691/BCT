"""One OS fence shared by external maintenance, BCT deployment and supervision."""
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import threading

from .service_runtime import RuntimeWriterLock

_guard = threading.Lock()
_threads = {}
_local = threading.local()


@contextmanager
def maintenance_lock(root):
    key = str(Path(root).resolve()).casefold()
    with _guard:
        thread_lock = _threads.setdefault(key, threading.RLock())
    with thread_lock:
        held = getattr(_local, "held", None)
        if held is None:
            held = _local.held = set()
        if key in held:
            yield
            return
        with RuntimeWriterLock(Path(root) / "state" / "maintenance.lock"):
            held.add(key)
            try:
                yield
            finally:
                held.remove(key)


def serialized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with maintenance_lock(self.runtime_root):
            return method(self, *args, **kwargs)
    return wrapped
