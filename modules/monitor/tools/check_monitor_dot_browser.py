"""Isolated headless Chrome UI acceptance with a simulated BCT HTTP boundary."""
import json
import re
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
if not chrome.exists():
    raise SystemExit("ISOLATED_CHROME_NOT_AVAILABLE")
shell = (root / "extension/monitor-bct-shell.js").read_text(encoding="utf-8")
source = (root / "domains/conversations.js").read_text(encoding="utf-8")
editor = re.search(r"//@@FN_START:openMonitorBctRenameEditor\n(.*?)//@@FN_END:openMonitorBctRenameEditor",source,re.S)[1]
bootstrap = r"""
let monitorBctRenameEditor=null, monitorLastAiState={};
const node={dotKey:"opaque~context",dotReference:"opaque",dotContextReference:"context",
  dotRevision:1,nodeLabel:"O",title:"Dot",conversationKey:"",scopeId:"",scopeName:"",
  roleTags:["Orchestrator"],nodeMemo:"before",assignedTask:"task",instanceId:"instance",
  sessionId:"session",windowId:10,tabId:1};
let monitorBctWindowNodesCache=[node,{...node,tabId:2},{...node,dotKey:"",conversationKey:"ordinary",tabId:3},
  {...node,dotKey:"",codexLocalReference:"00000000-0000-4000-8000-000000000004",conversationKey:"",tabId:4}];
const monitorWindowDesktopLocations=new Map(),monitorDesktopState={desktopIds:[]};
const monitorBctShell=MonitorBctShell.create({fetcher:async(url,init)=>{
 const body=JSON.parse(init.body);
 if(!url.endsWith("/monitor/dot-node-info")||body.dot_key!=="opaque~context"||"conversation_key" in body)throw Error("bad target");
 return {ok:true,json:async()=>({status:"OK",conversation:{revision:2,node_memo:body.node_memo}})};
}});
function closeMonitorBctRenameEditor(){monitorBctRenameEditor?.overlay.remove();monitorBctRenameEditor=null;}
function setMonitorStatus(text,ok){document.body.dataset.status=String(ok);}
function monitorDisplayHwndForBrowserWindowId(){return "";}
function monitorBctNodeBurden(){return {label:"idle",title:"idle"};}
function monitorBctNodeLocationText(){return "test";}
function monitorBctNodeSurfaceText(){return "Dot";}
function monitorBctNodeObservedAgeText(){return "0";}
function monitorBctRoleTagsFromText(value){return value.split(",").map(x=>x.trim()).filter(Boolean);}
function renderMonitorBctWindowNodes(){}
async function refreshMonitorBctWindowNodes(){}
function openMonitorTrashRecovery(){}
const row=document.createElement("article");document.body.append(row);
row.addEventListener("contextmenu",e=>{e.preventDefault();openMonitorBctRenameEditor(node,row)});
row.dispatchEvent(new MouseEvent("contextmenu",{bubbles:true,cancelable:true}));
const active=monitorBctRenameEditor;
if(!active || !active.input.disabled || !active.scopeInput.disabled)throw Error("dot editor guard");
active.memoInput.value="after";
active.dialog.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true}));
setTimeout(()=>{
 const dots=monitorBctWindowNodesCache.filter(n=>n.dotKey);
 if(document.body.dataset.status!=="true" || !dots.every(n=>n.nodeMemo==="after"&&n.dotRevision===2)
 || monitorBctWindowNodesCache[2].nodeMemo!=="before" || monitorBctWindowNodesCache[3].nodeMemo!=="before")throw Error("save/cache isolation");
 document.body.dataset.testResult="PASS";
document.body.textContent="PASS: contextmenu, dot Node Info edit, exact metadata route, two tabs plus ordinary and Codex-local node isolation";
},50);
"""
import sys
if "--codex" in sys.argv:
    bootstrap = bootstrap.replace('dotKey:"opaque~context"', 'dotKey:"",codexLocalReference:"00000000-0000-4000-8000-000000000001"')
    bootstrap = bootstrap.replace('nodeLabel:"O"', 'nodeLabel:"C1"')
    bootstrap = bootstrap[:bootstrap.index("const active=monitorBctRenameEditor;")] + """
const active=monitorBctRenameEditor;
if(!active || !active.input.disabled || !active.scopeInput.disabled ||
   !active.memoInput.disabled || !active.confirm.hidden)throw Error("Codex draft edit guard");
if(!active.dialog.textContent.includes("C1") || !active.dialog.textContent.includes("Codex local reference")
 || !active.dialog.textContent.includes("비공개 로컬 바인딩"))
 throw Error("Codex facts missing");
active.dialog.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true}));
if(monitorBctRenameEditor!==null)throw Error("Codex draft submit must close without writes");
document.body.dataset.testResult="PASS";
document.body.textContent="PASS Codex local Node Info read-only";
"""
with tempfile.TemporaryDirectory(prefix="bct-dot-ui-") as temp:
    temp = Path(temp)
    page = temp / "test.html"
    page.write_text("<!doctype html><body><script>"+shell+"\n"+editor+"\n"+bootstrap+"</script>",encoding="utf-8")
    result = subprocess.run([str(chrome),"--headless=new","--no-first-run","--no-default-browser-check",
        "--user-data-dir="+str(temp / "profile"),"--virtual-time-budget=2000","--dump-dom",page.as_uri()],
        capture_output=True,timeout=25)
    output=result.stdout.decode("utf-8",errors="replace")
    if 'data-test-result="PASS"' not in output:
        print(output[-6000:])
        raise SystemExit("ISOLATED_BROWSER_UI_FAILED")
    print("PASS isolated Chrome UI with simulated BCT backend; temporary profile only")
