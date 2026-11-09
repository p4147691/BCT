"""Typed local Codex route references and independent persistent C display labels."""
from __future__ import annotations
import re
from urllib.parse import urlsplit

_LOCAL = re.compile(r"/local/client-new-thread:([a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12})/?\Z")

def local_codex_reference(url):
    try:
        parsed = urlsplit(str(url))
        if parsed.scheme != "https" or parsed.netloc.lower() not in {"chatgpt.com"}:
            return ""
        match = _LOCAL.fullmatch(parsed.path)
        return match[1].lower() if match else ""
    except ValueError:
        return ""

def codex_directory(store):
    if not callable(getattr(store,"transaction",None)):
        return {}
    with store.transaction() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='codex_surface_nodes' AND type='table'").fetchone():
            return {}
        return {r["reference"]: {"identity_kind":"CODEX_LOCAL_DRAFT","reference":r["reference"],
                "node_label":f'C{((r["number"]-1)%99)+1}',"assignment_sequence":r["number"],
                "conversation_key":"","routable":False}
                for r in db.execute("SELECT reference,number FROM codex_surface_nodes")}

def register_codex_surfaces(store, urls):
    if not isinstance(urls,list) or len(urls)>64 or any(not isinstance(u,str) for u in urls):
        raise ValueError("CODEX_SURFACE_URLS_INVALID")
    refs = list(dict.fromkeys(local_codex_reference(u) for u in urls))
    if "" in refs:
        raise ValueError("CODEX_LOCAL_ROUTE_UNSUPPORTED")
    with store.transaction() as db:
        db.execute("CREATE TABLE IF NOT EXISTS codex_surface_nodes(reference TEXT PRIMARY KEY,number INTEGER NOT NULL UNIQUE CHECK(number>0))")
        for ref in refs:
            if not db.execute("SELECT 1 FROM codex_surface_nodes WHERE reference=?",(ref,)).fetchone():
                number = db.execute("SELECT COALESCE(MAX(number),0)+1 FROM codex_surface_nodes").fetchone()[0]
                db.execute("INSERT INTO codex_surface_nodes VALUES(?,?)",(ref,number))
    return codex_directory(store)

def observed_codex_nodes(store, instances):
    directory = codex_directory(store)
    result = []
    for instance in instances:
        for tab in instance.get("tabs",[]):
            ref = local_codex_reference(tab.get("url",""))
            if not ref:
                continue
            result.append({**directory.get(ref,{"identity_kind":"CODEX_LOCAL_DRAFT","reference":ref,
                "node_label":"","conversation_key":"","routable":False}),
                "instance_id":instance.get("instance_id",""),"session_id":instance.get("session_id",""),
                "window_id":tab.get("window_id"),"tab_id":tab.get("tab_id"),
                "source":"OBSERVED_LOCAL_ROUTE","identity_stability":"LOCAL_REFERENCE_ONLY",
                "observation_state":"FRESH" if instance.get("state")=="OPEN" and not instance.get("cached") else "UNAVAILABLE"})
    return result
