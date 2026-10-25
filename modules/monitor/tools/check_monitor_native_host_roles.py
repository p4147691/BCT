#!/usr/bin/env python3
"""Fail-closed, read-only Chrome Native Messaging role check for Monitor.
Browser-host role manifests are separate; file shell must support list,
window/virtual desktop control must support getVirtualDesktops.
No browser, Chrome, RCC, Native service, or user file mutations are performed.
"""
from __future__ import annotations
import argparse, hashlib, json, struct, subprocess
from pathlib import Path

FILE_NAME="com.pas40.desktop_window_monitor"
CONTROL_NAME="com.pas40.desktop_window_monitor_control"
ORIGIN="chrome-extension://kaigandfpieiogfbfaemoimenmipedck/"

def load(path:Path,name:str)->dict:
    data=json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("name") != name:raise ValueError("NATIVE_HOST_NAME_MISMATCH:"+name)
    if data.get("type")!="stdio":raise ValueError("NATIVE_STDIO_REQUIRED:"+name)
    origins=data.get("allowed_origins")
    if not isinstance(origins,list) or origins != [ORIGIN]:raise ValueError("NATIVE_ORIGIN_SCOPE_MISMATCH:"+name)
    exe=Path(str(data.get("path","")))
    if exe.name not in (("DesktopWindowMonitorHost.exe",) if name==FILE_NAME else ("DesktopWindowMonitorControlHost.exe",)):
        raise ValueError("NATIVE_EXECUTABLE_ROLE_MISMATCH:"+name)
    return data

def ask(exe:Path,payload:dict)->dict:
    raw=json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode("utf-8")
    process=subprocess.Popen([str(exe)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:out,err=process.communicate(struct.pack("<I",len(raw))+raw,timeout=13)
    except subprocess.TimeoutExpired:
        process.kill();process.communicate();raise TimeoutError("NATIVE_ROLE_PROBE_TIMEOUT")
    if process.returncode!=0:raise RuntimeError("NATIVE_ROLE_PROCESS_EXIT:"+str(process.returncode))
    offset=0;replies=[]
    while offset+4<=len(out):
        length=struct.unpack_from("<I",out,offset)[0];offset+=4
        if length < 1 or length > 1024*1024 or len(out)-offset<length:
            raise RuntimeError("NATIVE_ROLE_MESSAGE_FRAMING_INVALID")
        reply=json.loads(out[offset:offset+length].decode("utf-8"));offset+=length
        if isinstance(reply,dict) and reply.get("event") is not True:replies.append(reply)
    if offset!=len(out) or len(replies)!=1:raise RuntimeError("NATIVE_ROLE_REPLY_COUNT_INVALID")
    return replies[0]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,required=True,help="Monitor module or installed Monitor root")
    parser.add_argument("--probe",action="store_true",help="Perform one read-only request per registered binary")
    args=parser.parse_args()
    native=args.root/"native"
    fm=load(native/(FILE_NAME+".json"),FILE_NAME)
    cm=load(native/(CONTROL_NAME+".json"),CONTROL_NAME)
    f=Path(fm["path"]);c=Path(cm["path"])
    if f.resolve()==c.resolve():raise RuntimeError("NATIVE_HOSTS_MUST_HAVE_DIFFERENT_BINARIES")
    result={"ok":True,"fileRole":FILE_NAME,"controlRole":CONTROL_NAME,"separatePaths":True,"probe":bool(args.probe)}
    if args.probe:
        if not f.is_file() or not c.is_file():raise FileNotFoundError("NATIVE_BINARY_MISSING")
        fhash=hashlib.sha256(f.read_bytes()).hexdigest()
        chash=hashlib.sha256(c.read_bytes()).hexdigest()
        if fhash==chash:raise RuntimeError("NATIVE_HOST_ROLE_BINARY_CONTENT_COLLISION")
        file_reply=ask(f,{"type":"list","includeVisuals":False})
        if file_reply.get("ok") is not True or not isinstance(file_reply.get("items"),list):
            raise RuntimeError("NATIVE_FILE_HOST_LIST_CONTRACT_FAILED")
        control_reply=ask(c,{"type":"getVirtualDesktops"})
        if control_reply.get("ok") is not True or not isinstance(control_reply.get("desktopIds"),list):
            raise RuntimeError("NATIVE_CONTROL_HOST_DESKTOP_CONTRACT_FAILED")
        result.update(fileItems=len(file_reply["items"]),desktops=len(control_reply["desktopIds"]),
            fileBinaryShaPrefix=fhash[:16],controlBinaryShaPrefix=chash[:16])
    print(json.dumps(result,ensure_ascii=False))

if __name__=="__main__":main()
