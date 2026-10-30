// Explicit composition adapter between DiagnosticsCommandView and ToolConnectorRegistry.
// No DOM/global state, no new authorization or OS command execution.
(() => {
  "use strict";
  function create({registry,prepare} = {}) {
    if(!registry || typeof registry.request!=="function" ||
       typeof registry.reconcile!=="function" || typeof prepare!=="function")
      throw new TypeError("DIAGNOSTICS_TOOL_PORTS_REQUIRED");
    return Object.freeze({
      prepare: async command => {
        const value=await prepare(command);
        if(!value?.context || !value.context.workId ||
           !value.context.operationId || !value.context.requestHash)
          throw new TypeError("EXACT_OPERATION_CONTEXT_REQUIRED");
        return Object.freeze({context:Object.freeze({...value.context}),payload:value.payload});
      },
      run: (command,context,payload) =>
        registry.request(command.toolId,command.capability,payload,context),
      reconcile:(command,proof) => registry.reconcile(command.toolId,proof)
    });
  }
  globalThis.MonitorDiagnosticsToolPort = Object.freeze({create});
})();
