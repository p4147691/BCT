"""Output adapters for desktop capability commands."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable

async def desktop_session_status(run: Callable[..., Any], **v: Any) -> dict[str, Any]:
    result = await run(capability="desktop_session_status", arguments={}, **v)
    value = result.as_dict()
    if result.duplicate and "output" not in value:
        value["output"] = {"instanceId":result.evidence.get("instance_id"), "session":result.evidence.get("session"), "monitors":result.evidence.get("monitors")}
    return value

async def desktop_capture(run: Callable[..., Any], image_factory: Callable[..., Any], **v: Any) -> Any:
    arguments={key:v[key] for key in ("target_type","monitor_index","hwnd","max_width","max_height")}
    result=await run(capability="desktop_capture", arguments=arguments, principal=v["principal"], work_id=v["work_id"], operation_id=v["operation_id"], approval_ref=None)
    value=result.as_dict(); capture=result.output.get("capture") if isinstance(result.output,dict) else None
    capture=capture if isinstance(capture,dict) else result.evidence.get("capture")
    if result.outcome is not None and result.outcome.value=="APPLIED" and isinstance(capture,dict):
        path=Path(str(capture.get("path") or ""))
        if path.is_file(): value.pop("output",None); return value,image_factory(path=path,format="png")
    return value
