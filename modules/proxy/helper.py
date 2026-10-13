import json
import os
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(r"D:\BCT\runtime\modules\chrome-auto-proxy")
PRIVATE = ROOT / "private"
ACTIVE = PRIVATE / "active.conf"
INCOMING = PRIVATE / "incoming.conf"
TOKEN_FILE = PRIVATE / "helper.token"
WIREPROXY = ROOT / "wireproxy.exe"
WRAPPER = ROOT / "wireproxy.conf"
LOG = ROOT / "helper.log"
SOCKS = "127.0.0.1:25344"
HTTP_PROXY = "127.0.0.1:25345"
HELPER = ("127.0.0.1", 25346)
MAX_CONF = 65536

_lock = threading.RLock()
_proxy = None
_last = {"ok": False, "state": "starting", "detail": ""}

def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass

def token():
    return TOKEN_FILE.read_text(encoding="utf-8").strip()

def public_config_summary(path):
    text = Path(path).read_text(encoding="utf-8", errors="strict")
    if len(text.encode("utf-8")) > MAX_CONF:
        raise ValueError("CONFIG_TOO_LARGE")
    required = ["[Interface]", "PrivateKey", "Address", "[Peer]", "PublicKey", "Endpoint"]
    for item in required:
        if item not in text:
            raise ValueError(f"CONFIG_MISSING:{item}")
    if "AllowedIPs" not in text:
        raise ValueError("CONFIG_MISSING:AllowedIPs")
    endpoint = ""
    server = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Endpoint") and "=" in line:
            endpoint = line.split("=", 1)[1].strip()
        if line.startswith("#") and "FREE#" in line.upper():
            server = line.lstrip("#").strip()
    if not endpoint:
        raise ValueError("CONFIG_ENDPOINT_EMPTY")
    return {"server": server or "Proton WireGuard", "endpoint_host": endpoint.rsplit(":", 1)[0]}

def write_wrapper():
    WRAPPER.write_text(
        f"WGConfig = {ACTIVE}\n\n"
        "[Socks5]\nBindAddress = 127.0.0.1:25344\n\n"
        "[http]\nBindAddress = 127.0.0.1:25345\n",
        encoding="utf-8",
    )

def config_test():
    p = subprocess.run(
        [str(WIREPROXY), "-c", str(WRAPPER), "-n"],
        capture_output=True, text=True, timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if p.returncode != 0:
        raise RuntimeError("WIREPROXY_CONFIG_INVALID:" + (p.stderr or p.stdout)[-500:])

def proxy_alive():
    global _proxy
    return _proxy is not None and _proxy.poll() is None

def stop_proxy():
    global _proxy
    if _proxy is None:
        return
    if _proxy.poll() is None:
        _proxy.terminate()
        try:
            _proxy.wait(timeout=8)
        except subprocess.TimeoutExpired:
            _proxy.kill()
            _proxy.wait(timeout=5)
    _proxy = None

def start_proxy():
    global _proxy
    if not ACTIVE.is_file():
        raise FileNotFoundError("ACTIVE_CONFIG_MISSING")
    write_wrapper()
    config_test()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    _proxy = subprocess.Popen(
        [str(WIREPROXY), "-c", str(WRAPPER), "-s"],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    time.sleep(1.2)
    if _proxy.poll() is not None:
        raise RuntimeError("WIREPROXY_START_FAILED")

def probe():
    p = subprocess.run(
        ["curl.exe", "-L", "-sS", "--connect-timeout", "8", "--max-time", "25",
         "--proxy", "socks5h://127.0.0.1:25344", "-o", "NUL",
         "-w", "%{http_code}|%{time_total}", "https://f95zone.to/"],
        capture_output=True, text=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    out = (p.stdout or "").strip()
    code = 0
    total = None
    try:
        parts = out.split("|")
        code = int(parts[0])
        total = float(parts[1])
    except Exception:
        pass
    return {"ok": p.returncode == 0 and 200 <= code < 400, "http": code, "seconds": total}

def set_state(ok, state, detail="", extra=None):
    global _last
    _last = {"ok": bool(ok), "state": state, "detail": str(detail), "proxy_alive": proxy_alive()}
    if extra:
        _last.update(extra)
    return dict(_last)

def import_config(source):
    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError("DOWNLOADED_CONFIG_MISSING")
    if source.suffix.lower() != ".conf":
        raise ValueError("NOT_CONF")
    stat = source.stat()
    if stat.st_size < 100 or stat.st_size > MAX_CONF:
        raise ValueError("CONFIG_SIZE_INVALID")
    if time.time() - stat.st_mtime > 20 * 60:
        raise ValueError("CONFIG_NOT_RECENT")
    summary = public_config_summary(source)
    old = ACTIVE.read_bytes() if ACTIVE.exists() else None
    PRIVATE.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, INCOMING)
    try:
        public_config_summary(INCOMING)
        stop_proxy()
        os.replace(INCOMING, ACTIVE)
        start_proxy()
        result = probe()
        if not result["ok"]:
            raise RuntimeError(f"PROXY_PROBE_FAILED:{result}")
    except Exception:
        try:
            stop_proxy()
        except Exception:
            pass
        if old is not None:
            ACTIVE.write_bytes(old)
            start_proxy()
        elif ACTIVE.exists():
            ACTIVE.unlink()
        raise
    try:
        if source != ACTIVE:
            source.unlink()
    except Exception:
        pass
    return set_state(True, "ready", "config_applied", {"config": summary, "probe": result})

def bootstrap():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    if not TOKEN_FILE.exists():
        raise RuntimeError("HELPER_TOKEN_MISSING")
    if ACTIVE.exists():
        summary = public_config_summary(ACTIVE)
        start_proxy()
        result = probe()
        set_state(result["ok"], "ready" if result["ok"] else "degraded", "startup", {"config": summary, "probe": result})
    else:
        set_state(False, "needs_config", "active.conf missing")

class Handler(BaseHTTPRequestHandler):
    server_version = "ChromeAutoProxy/1.0"
    def log_message(self, fmt, *args):
        return
    def _origin(self):
        return self.headers.get("Origin", "")
    def _cors(self):
        origin = self._origin()
        if origin.startswith("chrome-extension://"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-CAP-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    def _json(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def _auth(self):
        supplied = self.headers.get("X-CAP-Token", "")
        return bool(supplied) and supplied == token()
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()
    def do_GET(self):
        if not self._auth():
            return self._json(403, {"ok": False, "error": "FORBIDDEN"})
        if self.path == "/status":
            with _lock:
                body = dict(_last)
                body["proxy_alive"] = proxy_alive()
            return self._json(200, body)
        return self._json(404, {"ok": False, "error": "NOT_FOUND"})
    def do_POST(self):
        if not self._auth():
            return self._json(403, {"ok": False, "error": "FORBIDDEN"})
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 65536)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(400, {"ok": False, "error": "BAD_JSON"})
        with _lock:
            try:
                if self.path == "/import":
                    path = body.get("path", "")
                    if not path:
                        raise ValueError("PATH_REQUIRED")
                    result = import_config(path)
                    return self._json(200, result)
                if self.path == "/restart":
                    stop_proxy()
                    start_proxy()
                    result = probe()
                    return self._json(200 if result["ok"] else 503, set_state(result["ok"], "ready" if result["ok"] else "degraded", "restart", {"probe": result}))
            except Exception as exc:
                log(f"operation_failed {type(exc).__name__}: {exc}")
                return self._json(500, set_state(False, "error", f"{type(exc).__name__}:{exc}"))
        return self._json(404, {"ok": False, "error": "NOT_FOUND"})

def main():
    try:
        bootstrap()
    except Exception as exc:
        log(f"bootstrap_failed {type(exc).__name__}: {exc}")
        set_state(False, "error", f"{type(exc).__name__}:{exc}")
    server = ThreadingHTTPServer(HELPER, Handler)
    log("helper_listening 127.0.0.1:25346")
    server.serve_forever()

if __name__ == "__main__":
    main()
