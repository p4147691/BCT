"""Browser -> isolated HTTP adapter -> production handler -> temporary SQLite.
The adapter supplies the trusted extension Origin for a localhost test page.
This is not acceptance of production extension authorization or live dot delivery.
"""
import ast
import asyncio
import json
import re
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from starlette.requests import Request
from bct.core.store import Store
from bct.dot_identity import save_dot_info, dot_directory
from bct.runtime_server import dot_node_info_response, MONITOR_EXTENSION_ORIGIN

root = Path(__file__).resolve().parents[1]
chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
if not chrome.exists():
    raise SystemExit("ISOLATED_CHROME_NOT_AVAILABLE")
tree = ast.parse((root / "tools/check_monitor_dot_browser.py").read_text(encoding="utf-8"))
bootstrap = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
                 and any(isinstance(t,ast.Name) and t.id=="bootstrap" for t in n.targets))
start = bootstrap.index("const monitorBctShell=")
end = bootstrap.index("function closeMonitorBctRenameEditor",start)
bootstrap = bootstrap[:start] + """
const monitorBctShell=MonitorBctShell.create({fetcher:async(url,init)=>{
 return fetch(location.origin+"/monitor/dot-node-info",init);
}});
""" + bootstrap[end:]
shell = (root / "extension/monitor-bct-shell.js").read_text(encoding="utf-8")
source = (root / "domains/conversations.js").read_text(encoding="utf-8")
editor = re.search(r"//@@FN_START:openMonitorBctRenameEditor\n(.*?)//@@FN_END:openMonitorBctRenameEditor",source,re.S)[1]
html = "<!doctype html><body><script>"+shell+"\n"+editor+"\n"+bootstrap+"</script>"
with tempfile.TemporaryDirectory(prefix="bct-dot-http-e2e-") as temp:
    temp = Path(temp)
    bct = SimpleNamespace(store=Store(temp / "state.sqlite"))
    save_dot_info(bct.store,{"dot_key":"opaque~context","display_name":"Dot",
                            "node_memo":"before","expected_revision":0})
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            if self.path == "/test.html":
                self.send_response(200);self.send_header("Content-Type","text/html;charset=utf-8")
                self.end_headers();self.wfile.write(html.encode());return
            self.dispatch()
        def do_POST(self): self.dispatch()
        def dispatch(self):
            if self.path != "/monitor/dot-node-info":
                self.send_error(404);return
            body = self.rfile.read(int(self.headers.get("Content-Length",0)))
            async def receive():
                return {"type":"http.request","body":body,"more_body":False}
            request = Request({"type":"http","method":self.command,"path":self.path,
                "headers":[(b"origin",MONITOR_EXTENSION_ORIGIN.encode())]},receive)
            response = asyncio.run(dot_node_info_response(bct,request))
            self.send_response(response.status_code)
            self.send_header("Content-Type","application/json")
            self.end_headers();self.wfile.write(response.body)
    server = ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        result = subprocess.run([str(chrome),"--headless=new","--no-first-run",
            "--no-default-browser-check","--user-data-dir="+str(temp / "profile"),
            "--virtual-time-budget=5000","--dump-dom",
            "http://127.0.0.1:"+str(server.server_port)+"/test.html"],
            capture_output=True,timeout=25)
        output=result.stdout.decode("utf-8",errors="replace")
        if 'data-test-result="PASS"' not in output:
            print(output[-6000:]);raise AssertionError("BROWSER_HTTP_ROUNDTRIP_FAILED")
        persisted=dot_directory(Store(temp / "state.sqlite"))["opaque~context"]
        assert persisted["node_memo"]=="after" and persisted["revision"]==2,persisted
        with bct.store.transaction() as db:
            assert db.execute("SELECT count(*) FROM conversation_network_node_labels").fetchone()[0]==0
        print("PASS isolated browser/HTTP/handler/SQLite roundtrip; trusted-Origin adapter simulated")
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
