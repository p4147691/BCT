import json
import shutil
import subprocess
import time
from pathlib import Path

import requests
import websocket

ROOT = Path(r"D:\BCT\runtime\modules\chrome-auto-proxy")
EXT = Path(r"D:\ChromeExtensions\BCT-Auto-Proxy\extension")
PROFILE = Path(r"D:\BCT\data\test-profiles\chrome-auto-proxy")
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
PORT = 9237

def wait_json(url, timeout=20):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            return requests.get(url, timeout=1).json()
        except Exception as exc:
            last = exc
            time.sleep(0.25)
    raise RuntimeError(f"CDP_NOT_READY: {last}")

class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=10, origin=f"http://127.0.0.1:{PORT}")
        self.seq = 0
    def call(self, method, params=None):
        self.seq += 1
        ident = self.seq
        self.ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
        deadline = time.time() + 20
        while time.time() < deadline:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == ident:
                if "error" in msg:
                    raise RuntimeError(f"CDP_ERROR {method}: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(method)
    def close(self):
        self.ws.close()

def eval_js(cdp, expression):
    result = cdp.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    return result.get("result", {}).get("value")

def navigate(cdp, url, wait=6):
    cdp.call("Page.navigate", {"url": url})
    time.sleep(wait)
    return {
        "url": eval_js(cdp, "location.href"),
        "title": eval_js(cdp, "document.title"),
        "body": eval_js(cdp, "document.body ? document.body.innerText.slice(0,700) : ''"),
    }

if PROFILE.exists():
    shutil.rmtree(PROFILE, ignore_errors=True)
PROFILE.mkdir(parents=True, exist_ok=True)

args = [
    str(CHROME),
    f"--user-data-dir={PROFILE}",
    f"--remote-debugging-port={PORT}",
    "--remote-allow-origins=*",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-mode",
    "--disable-gpu",
    "--window-position=-32000,-32000",
    "--window-size=800,600",
    f"--disable-extensions-except={EXT}",
    f"--load-extension={EXT}",
    "about:blank",
]
proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
summary = {"chrome_pid": proc.pid}

try:
    wait_json(f"http://127.0.0.1:{PORT}/json/version")
    time.sleep(4)
    targets = requests.get(f"http://127.0.0.1:{PORT}/json", timeout=3).json()
    summary["extension_targets"] = [
        {"type": t.get("type"), "url": t.get("url", "")}
        for t in targets if "chrome-extension://" in t.get("url", "")
    ]
    summary["has_background_js"] = any(
        t.get("url", "").endswith("/background.js") for t in targets
    )
    page = next((t for t in targets if t.get("type") == "page" and t.get("url", "").startswith(("about:", "http://", "https://"))), None)
    if not page:
        raise RuntimeError("NO_PAGE_TARGET")
    cdp = CDP(page["webSocketDebuggerUrl"])
    try:
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        direct = navigate(cdp, "https://www.cloudflare.com/cdn-cgi/trace", 5)
        direct_lines = {}
        for line in (direct["body"] or "").splitlines():
            if line.startswith(("loc=", "colo=", "warp=", "http=", "tls=")):
                k, v = line.split("=", 1)
                direct_lines[k] = v
        summary["direct_trace"] = direct_lines
        f95 = navigate(cdp, "https://f95zone.to/", 8)
        body = f95["body"] or ""
        summary["f95"] = {
            "url": f95["url"],
            "title": f95["title"],
            "body_has_451": ("451" in body and "법적" in body),
            "body_has_f95": ("F95" in body.upper()),
            "body_prefix": body[:220],
        }
    finally:
        cdp.close()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
    time.sleep(1)
    err = ""
    try:
        err = proc.stderr.read()[-3000:] if proc.stderr else ""
    except Exception:
        pass
    summary["chrome_stderr_tail"] = err
    shutil.rmtree(PROFILE, ignore_errors=True)

print(json.dumps(summary, ensure_ascii=False))
