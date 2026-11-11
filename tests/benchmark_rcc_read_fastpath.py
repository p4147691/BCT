"""Controlled no-effect microbenchmark; not a physical RCC latency claim."""
import json
import statistics
import time
from pathlib import Path
from unittest.mock import Mock

from bct.send_delayed_message import SendDelayedMessageService

INSTANCE = "bench-instance"
UUID = "11111111-2222-3333-4444-555555555555"
SESSION = "a" * 32
TARGET = {"instance_id": INSTANCE, "conversation_key": UUID,
          "session_id": SESSION, "tab_id": 100, "window_id": 200}

def quantile(values, q):
    seq = sorted(values)
    pos = (len(seq) - 1) * q
    low = int(pos)
    return round(seq[low] + (seq[min(low + 1, len(seq)-1)] - seq[low]) * (pos-low), 3)

def benchmark(rounds=60):
    client = Mock()
    client.request.side_effect = lambda **kw: (time.sleep(0.003),
        {"ok": True, "conversationKey": UUID})[1]
    svc = object.__new__(SendDelayedMessageService)
    svc.browser_feature = Mock(client=client)
    svc._locate = lambda *_: (time.sleep(0.005), (SESSION, 100, 200))[1]
    metrics = {"baseline": [], "exact_target": []}
    timings = {"baseline": [], "exact_target": []}
    for _ in range(rounds):
        for route, extra in (("baseline", {}), ("exact_target", {"verified_target": TARGET})):
            start = time.perf_counter()
            svc.latest(instance_id=INSTANCE, conversation_key=UUID,
                       timing_sink=timings[route].append, **extra)
            metrics[route].append((time.perf_counter() - start) * 1000)
    return {"environment": "mocked RCC request and discovery, 3ms/5ms simulated waits; not LIVE",
            "rounds_per_route": rounds,
            "results": {name: {
                "p50_ms": quantile(vals, 0.5),
                "p95_ms": quantile(vals, 0.95),
                "mean_ms": round(statistics.mean(vals), 3),
                "discovery_p50_ms": quantile([t["discovery_ms"] for t in timings[name]], 0.5),
                "rcc_roundtrip_p50_ms": quantile([t["rcc_roundtrip_ms"] for t in timings[name]], 0.5),
            } for name, vals in metrics.items()}}

if __name__ == "__main__":
    print(json.dumps(benchmark(), indent=2))
