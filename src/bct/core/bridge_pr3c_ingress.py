"""PR3-c: strict in-process envelope boundary; never a listener or real Host."""
import json
import math
import time
from .models import ConflictError
from .bridge_pr3b_auth import call, OPERATIONS, ORIGIN, AUDIENCE

MAX_BYTES = 8192
FIELDS = frozenset(("version","operation","request_id","origin","audience","credential",
                    "session_id","node_id","attachment_id","generation","arguments"))
ARGS = {
 "completion_report": frozenset(("event_id","session_id","assignment_id","generation",
                                  "source_node_id","result_id","result_digest")),
 "result_get": frozenset(("event_id",)),
 "delivery_receipt_get": frozenset(("session_id","delivery_id")),
 "recipient_ack": frozenset(("delivery_id","command_id","target_node_id","attachment_id",
                              "attachment_generation","assignment_id","assignment_generation",
                              "payload_digest","ack_digest","recipient_proof","epoch","token")),
}

def _pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_FIELD")
        result[key]=value
    return result


def _finite_json(value):
    """Reject non-finite numbers anywhere in the decoded JSON tree."""
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)
        elif isinstance(current, float) and not math.isfinite(current):
            raise ValueError("NONFINITE")

def parse_envelope(frame):
    if not isinstance(frame,bytes) or not 0 < len(frame) <= MAX_BYTES:
        raise ConflictError("ENVELOPE_DENIED")
    try:
        value=json.loads(frame.decode("utf-8"),object_pairs_hook=_pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NONFINITE")))
        _finite_json(value)
        if not isinstance(value,dict) or set(value)!=FIELDS:
            raise ValueError("ENVELOPE_FIELDS")
        if type(value["version"]) is not int or value["version"]!=1:
            raise ValueError("ENVELOPE_VERSION")
        op=value["operation"]
        if not isinstance(op,str) or op not in OPERATIONS:
            raise ValueError("ENVELOPE_OPERATION")
        if value["origin"]!=ORIGIN or value["audience"]!=AUDIENCE:
            raise ValueError("ENVELOPE_AUDIENCE")
        if type(value["generation"]) is not int or value["generation"]<1:
            raise ValueError("ENVELOPE_GENERATION")
        for field in ("request_id","credential","session_id","node_id","attachment_id"):
            v=value[field]
            if not isinstance(v,str) or not 0<len(v)<=256:
                raise ValueError("ENVELOPE_ID")
        arguments=value["arguments"]
        if not isinstance(arguments,dict) or set(arguments)!=ARGS[op]:
            raise ValueError("ENVELOPE_ARGUMENTS")
        # Never serialize the credential or untrusted arguments in an exception.
        return value
    except (UnicodeError,ValueError,TypeError,OverflowError,RecursionError):
        raise ConflictError("ENVELOPE_DENIED") from None

def ingress(store, frame):
    envelope=parse_envelope(frame)
    arguments=dict(envelope["arguments"])
    # Lease fencing is Core authority. A future Host must never supply its clock.
    if envelope["operation"] == "recipient_ack":
        arguments["now"] = time.time()
    return call(store,credential=envelope["credential"],request_id=envelope["request_id"],
                operation=envelope["operation"],session_id=envelope["session_id"],
                node_id=envelope["node_id"],attachment_id=envelope["attachment_id"],
                generation=envelope["generation"],origin=envelope["origin"],
                audience=envelope["audience"],now=None,arguments=arguments)
