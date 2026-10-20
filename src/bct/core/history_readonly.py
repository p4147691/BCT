"""Read-only historical collaboration projections; no live node mutation."""
import sqlite3
from pathlib import Path
from contextlib import closing

def connect(path):
    db=sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro&immutable=1",uri=True)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db

def rows(db,sql,args=()):
    return [dict(row) for row in db.execute(sql,args)]

def historical_nodes(path):
    with closing(connect(path)) as db:
        result=rows(db,"""SELECT n.node_id,n.name,n.role,n.active,n.revision,
          COUNT(DISTINCT sn.session_id) session_count FROM nodes n
          LEFT JOIN orchestration_session_nodes sn ON sn.node_id=n.node_id
          GROUP BY n.node_id ORDER BY n.node_id""")
        for node in result:
            node["sessions"]=rows(db,"""SELECT sn.session_id,s.work_id,s.state,
              sn.session_role,s.created_at FROM orchestration_session_nodes sn
              JOIN orchestration_sessions s ON s.session_id=sn.session_id
              WHERE sn.node_id=? ORDER BY s.created_at,s.session_id""",(node["node_id"],))
            node["historical_identity_coverage"]="CURRENT_IDENTITY_ONLY"
            node["is_currently_connected"]="NOT_INFERRED"
        return result

def timeline(path,session_id):
    with closing(connect(path)) as db:
        s=db.execute("SELECT * FROM orchestration_sessions WHERE session_id=?",(session_id,)).fetchone()
        if s is None: raise KeyError("SESSION_NOT_FOUND")
        participants=rows(db,"""SELECT sn.node_id,n.name,sn.session_role FROM orchestration_session_nodes sn
                JOIN nodes n ON n.node_id=sn.node_id WHERE sn.session_id=? ORDER BY sn.node_id""",(session_id,))
        assignments=rows(db,"SELECT * FROM orchestration_assignments WHERE session_id=? ORDER BY created_at,assignment_id",(session_id,))
        messages=rows(db,"SELECT * FROM orchestration_mailbox WHERE session_id=? ORDER BY created_at,message_id",(session_id,))
        decisions=rows(db,"SELECT * FROM orchestration_consumption_decisions WHERE session_id=? ORDER BY created_at,decision_id",(session_id,))
        receipts=rows(db,"SELECT * FROM orchestration_consumption_receipts WHERE session_id=? ORDER BY created_at,result_message_id",(session_id,))
        wakes=rows(db,"SELECT * FROM orchestration_manager_wakes WHERE session_id=? ORDER BY created_at,event_id",(session_id,))
        ordering=[]
        for kind,records,key in (("ASSIGNMENT",assignments,"assignment_id"),("DECISION",decisions,"decision_id"),("CONSUMPTION_ACK",receipts,"result_message_id"),("WAKE",wakes,"event_id")):
            ordering += [{"kind":kind,"timestamp":r["created_at"],"id":r[key]} for r in records]
        ordering += [{"kind":r["kind"],"timestamp":r["created_at"],"id":r["message_id"]} for r in messages]
        ordering.sort(key=lambda r:(r["timestamp"],r["kind"],r["id"]))
        return {"session":dict(s),"participants":participants,"assignments":assignments,
          "messages":messages,"decisions":decisions,"receipts":receipts,"wakes":wakes,
          "timeline":ordering,"chat_transcript_coverage":"NOT_VERIFIED",
          "full_history_verified":False}

def integrity(path):
    with closing(connect(path)) as db:
        return {"integrity":[x[0] for x in db.execute("PRAGMA integrity_check")],
                "foreign_key_errors":[list(x) for x in db.execute("PRAGMA foreign_key_check")],
                "nodes":db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
                "sessions":db.execute("SELECT COUNT(*) FROM orchestration_sessions").fetchone()[0],
                "messages":db.execute("SELECT COUNT(*) FROM orchestration_mailbox").fetchone()[0]}

def current_nodes(path):
    """Registration/connection facts, not a claim of a live AI worker."""
    with closing(connect(path)) as db:
        result=rows(db,"""SELECT n.node_id,n.name,n.role,n.active,n.revision,
          COUNT(c.connection_id) AS registered_connections,
          SUM(CASE WHEN c.active=1 THEN 1 ELSE 0 END) AS active_connection_records
          FROM nodes n LEFT JOIN connections c ON n.node_id=c.node_id
          WHERE n.active=1 GROUP BY n.node_id ORDER BY n.node_id""")
        for record in result:
            record["live_presence"]="UNVERIFIED_REQUIRES_RCC"
            record["assignable"]="UNVERIFIED_REQUIRES_RUNTIME_POLICY"
        return result

def work_history(path,work_id):
    """Return one Work and all its durable collaboration sessions."""
    with closing(connect(path)) as db:
        w=db.execute("SELECT * FROM works WHERE work_id=?",(work_id,)).fetchone()
        if w is None: raise KeyError("WORK_NOT_FOUND")
        ids=[r[0] for r in db.execute("""SELECT session_id FROM orchestration_sessions
           WHERE work_id=? ORDER BY created_at,session_id""",(work_id,))]
    return {"work":dict(w),"sessions":[timeline(path,sid) for sid in ids],
            "chat_transcript_coverage":"NOT_VERIFIED","full_history_verified":False}
