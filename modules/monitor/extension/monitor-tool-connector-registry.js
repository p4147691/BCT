// Monitor tool connection surface. The injected authority and adapter own ALL effects.
// No connector or OS/browser process is accessed by this presentation-only registry.
(() => {
  "use strict";
  const IDENT = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
  const STATES = Object.freeze({
    DISCONNECTED: "DISCONNECTED", CONNECTED: "CONNECTED",
    CONNECTING: "CONNECTING", DISCONNECTING: "DISCONNECTING",
    BUSY: "BUSY", ERROR: "ERROR", UNKNOWN: "UNKNOWN"
  });
  function clean(value) { return String(value || "").trim(); }
  function checkId(value, label) {
    const id = clean(value);
    if (!IDENT.test(id)) throw new TypeError("INVALID_" + label);
    return id;
  }
  function create({ authorize, verifyReceipt, onChange = () => {} } = {}) {
    if (typeof authorize !== "function" || typeof onChange !== "function")
      throw new TypeError("AUTHORITY_AND_EVENT_PORT_REQUIRED");
    const adapters = new Map(), records = new Map(), operations = new Map();
    const view = (id) => {
      const r = records.get(id);
      if (!r) return null;
      return Object.freeze({
        id, capabilities: Object.freeze([...r.capabilities]), state: r.state,
        connected: r.connected, busy: r.busy, needsReconciliation: r.uncertain, lastResult: r.lastResult,
        lastError: r.lastError
      });
    };
    function emit(id) { onChange(Object.freeze({ type:"tool-state", toolId:id, snapshot:view(id) })); }
    function register(adapter) {
      const id = checkId(adapter?.id, "TOOL_ID");
      if (adapters.has(id)) throw new Error("TOOL_ALREADY_REGISTERED");
      const capabilities = adapter?.capabilities;
      if (!Array.isArray(capabilities) || !capabilities.length || !capabilities.every(c => IDENT.test(clean(c))) ||
          new Set(capabilities).size !== capabilities.length ||
          ["connect","disconnect","status","request"].some(n => typeof adapter?.[n] !== "function"))
        throw new TypeError("INVALID_TOOL_PORTS");
      adapters.set(id, Object.freeze({...adapter, capabilities:Object.freeze([...capabilities])}));
      records.set(id, {capabilities:[...capabilities], state:STATES.DISCONNECTED, connected:false,
        busy:false, uncertain:false, unknownExact:null, lastResult:null, lastError:null});
      emit(id);
      return view(id);
    }
    async function unregister(id) {
      const toolId=checkId(id,"TOOL_ID"), adapter=adapters.get(toolId), r=records.get(toolId);
      if (!adapter || !r) throw new Error("TOOL_NOT_REGISTERED");
      if (r.connected || r.busy || r.uncertain) throw new Error("DISCONNECT_AND_RECONCILE_FIRST");
      if (typeof adapter.dispose === "function") await adapter.dispose();
      adapters.delete(toolId); records.delete(toolId);
      onChange(Object.freeze({type:"tool-removed",toolId,snapshot:null}));
      return true;
    }
    function contextFor(id, action, capability, context) {
      const toolId = checkId(id,"TOOL_ID");
      const workId = checkId(context?.workId,"WORK_ID");
      const operationId = checkId(context?.operationId,"OPERATION_ID");
      const requestHash = clean(context?.requestHash);
      if (!/^[0-9a-f]{64}$/i.test(requestHash)) throw new TypeError("REQUEST_HASH_REQUIRED");
      return Object.freeze({toolId, action, capability, workId, operationId,
        requestHash:requestHash.toLowerCase(), approvalRef:clean(context?.approvalRef)});
    }
    async function operation(id, action, capability, payload, context) {
      const adapter=adapters.get(id), r=records.get(id);
      if (!adapter || !r) throw new Error("TOOL_NOT_REGISTERED");
      if (action === "request" && !r.capabilities.includes(capability))
        throw new Error("UNSUPPORTED_CAPABILITY");
      const exact=contextFor(id,action,capability,context);
      const key=exact.workId + ":" + exact.operationId;
      const payloadIdentity=action==="request" ? JSON.stringify(payload) : "";
      if (action==="request" && payloadIdentity===undefined) throw new TypeError("INVALID_TOOL_PAYLOAD");
      const identity=JSON.stringify(exact)+":"+payloadIdentity;
      if (operations.has(key)) {
        const previous=operations.get(key);
        if (previous.identity !== identity) throw new Error("OPERATION_ID_REUSE_MISMATCH");
        return previous.ticket;
      }
      if (r.uncertain && action !== "status")
        throw new Error("UNKNOWN_RECONCILIATION_REQUIRED");
      if (r.busy) throw new Error("TOOL_BUSY");
      if (action === "request" && !r.connected) throw new Error("TOOL_DISCONNECTED");
      if (action === "disconnect" && !r.connected) throw new Error("TOOL_DISCONNECTED");
      if (action === "connect" && r.connected) throw new Error("TOOL_ALREADY_CONNECTED");
      // Reserve the exact operation before an authorization or adapter effect.
      const ticket=(async () => {
        r.busy=true;
        r.state=action==="connect" ? STATES.CONNECTING :
          action==="disconnect" ? STATES.DISCONNECTING : STATES.BUSY;
        emit(id);
        let result=null, authorized=false;
        try {
          const permit=await authorize(exact);
          // The external BCT authority must prove an exact, unexpired request.
          if (!permit || permit.ok !== true || permit.workId !== exact.workId ||
              permit.operationId !== exact.operationId || permit.requestHash !== exact.requestHash ||
              permit.toolId !== id || permit.action !== action || permit.capability !== capability)
            throw new Error("AUTHORITY_NOT_CONFIRMED");
          authorized=true;
          const raw=await adapter[action](Object.freeze({capability, payload, context:exact}));
          const evidence=raw && typeof raw==="object" ? raw : {};
          const trusted=(evidence.workId===exact.workId && evidence.operationId===exact.operationId &&
            evidence.requestHash===exact.requestHash);
          const state=trusted && evidence.outcome==="APPLIED" ? "APPLIED" :
            trusted && evidence.outcome==="NOT_APPLIED" ? "NOT_APPLIED" : "UNKNOWN";
          result=Object.freeze({schema:"monitor.tool.operation.v1",...exact,
            outcome:state, receipt:evidence.receipt||null, error:evidence.error||null});
          if (action==="connect" && state==="APPLIED") r.connected=true;
          if (action==="disconnect" && state==="APPLIED") r.connected=false;
        } catch(error) {
          // No adapter attempt on denied authorization; thrown errors after dispatch are UNKNOWN.
          const code=clean(error?.message || error);
          result=Object.freeze({schema:"monitor.tool.operation.v1",...exact,
            outcome:authorized?"UNKNOWN":"NOT_APPLIED",receipt:null,error:code});
        } finally {
          r.busy=false;
          r.lastResult=result;
          if (result?.outcome === "UNKNOWN") { r.uncertain=true; r.unknownExact=exact; }
          r.lastError=result?.error||null;
          r.state=r.uncertain ? STATES.UNKNOWN :
            r.connected ? STATES.CONNECTED :
            result?.outcome==="NOT_APPLIED" ? STATES.ERROR : STATES.DISCONNECTED;
          emit(id);
        }
        return result;
      })();
      operations.set(key,{identity,ticket});
      return ticket;
    }
    async function reconcile(id, proof) {
      const toolId=checkId(id,"TOOL_ID"), r=records.get(toolId);
      if (!r) throw new Error("TOOL_NOT_REGISTERED");
      if (!r.uncertain || !r.unknownExact) throw new Error("NO_UNKNOWN_TO_RECONCILE");
      if (r.busy) throw new Error("TOOL_BUSY");
      if (typeof verifyReceipt !== "function") throw new Error("RECEIPT_VERIFICATION_PORT_REQUIRED");
      const original=r.unknownExact;
      const verification=await verifyReceipt(Object.freeze({toolId,original,proof}));
      if (!verification || verification.ok!==true || verification.final!==true ||
          verification.toolId!==toolId || verification.workId!==original.workId ||
          verification.operationId!==original.operationId ||
          verification.requestHash!==original.requestHash ||
          !["APPLIED","NOT_APPLIED"].includes(verification.outcome))
        throw new Error("EXACT_RECEIPT_NOT_VERIFIED");
      r.uncertain=false;
      r.unknownExact=null;
      if (original.action==="connect" && verification.outcome==="APPLIED") r.connected=true;
      if (original.action==="disconnect" && verification.outcome==="APPLIED") r.connected=false;
      r.state=r.connected ? STATES.CONNECTED : STATES.DISCONNECTED;
      r.lastResult=Object.freeze({schema:"monitor.tool.reconciliation.v1",
        ...original,outcome:verification.outcome,receipt:verification.receipt||null,error:null});
      r.lastError=null;
      emit(toolId);
      return r.lastResult;
    }
    return Object.freeze({
      register,
      unregister,
      reconcile,
      list:() => Object.freeze([...records.keys()].map(view)),
      snapshot:id => view(checkId(id,"TOOL_ID")),
      connect:(id,context) => operation(id,"connect","",null,context),
      disconnect:(id,context) => operation(id,"disconnect","",null,context),
      status:(id,context) => operation(id,"status","",null,context),
      request:(id,capability,payload,context) =>
        operation(id,"request",checkId(capability,"CAPABILITY"),payload,context),
      STATES
    });
  }
  globalThis.MonitorToolConnectorRegistry = Object.freeze({create,STATES});
})();
