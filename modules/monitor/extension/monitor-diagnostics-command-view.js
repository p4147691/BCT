// Diagnostics command presentation. No process, Chrome, Native or BCT authority.
// Run/reconcile ports must be backed by a verified ToolConnectorRegistry adapter.
(() => {
  "use strict";
  const ID=/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
  function create({host,document,run=null,reconcile=null,prepare=null}={}) {
    if(!host||!document)throw new TypeError("DIAGNOSTICS_COMMAND_VIEW_REQUIRED");
    const commands=new Map(),statuses=new Map();
    let inFlight=false;
    function setCommands(items=[]) {
      if(inFlight)throw new Error("COMMAND_BUSY");
      commands.clear();
      for(const item of items){
        if(!ID.test(String(item?.id||""))||!ID.test(String(item?.capability||""))||
          !ID.test(String(item?.toolId||""))||commands.has(item.id))
          throw new TypeError("INVALID_COMMAND_CONTRACT");
        commands.set(item.id,Object.freeze({id:item.id,label:String(item.label||item.id),
          toolId:item.toolId,capability:item.capability}));
      }
      render();
    }
    function render(){
      host.replaceChildren();
      if(!commands.size){
        const empty=document.createElement("span");
        empty.className="monitor-diag-command-empty";
        empty.textContent="승인된 진단 명령 미연결";
        host.append(empty);
        return;
      }
      for(const cmd of commands.values()){
        const group=document.createElement("div");group.className="monitor-diag-command-row";
        const button=document.createElement("button");button.type="button";
        button.className="monitor-diagnostics-icon-button monitor-diag-command";
        button.dataset.commandId=cmd.id;button.textContent=cmd.label;
        button.disabled=!run||!prepare||inFlight||statuses.get(cmd.id)?.outcome==="UNKNOWN";
        const status=document.createElement("span");status.className="monitor-diag-command-status";
        const record=statuses.get(cmd.id);
        status.textContent=record?.outcome||(!run?"권한 포트 미연결":"대기");
        button.addEventListener("click",()=>{
          if(!prepare || !run)return;
          void Promise.resolve().then(()=>prepare(cmd)).then(({context,payload})=>
            request(cmd.id,context,payload)
          ).catch(error=>{
            statuses.set(cmd.id,Object.freeze({outcome:"NOT_APPLIED",
              error:String(error?.message||error)}));render();
          });
        });
        group.append(button,status);host.append(group);
      }
    }
    async function request(id,context,payload){
      const cmd=commands.get(String(id||""));
      if(!cmd)throw new Error("COMMAND_NOT_REGISTERED");
      if(typeof run!=="function")throw new Error("COMMAND_AUTHORITY_PORT_NOT_CONNECTED");
      if(inFlight)throw new Error("COMMAND_BUSY");
      if(statuses.get(id)?.outcome==="UNKNOWN")throw new Error("UNKNOWN_RECONCILIATION_REQUIRED");
      inFlight=true;
      statuses.set(id,Object.freeze({outcome:"RUNNING",context:Object.freeze({...context})}));render();
      try{
        const receipt=await run(cmd,context,payload);
        const exact=receipt?.schema==="monitor.tool.operation.v1" &&
          receipt.toolId===cmd.toolId && receipt.capability===cmd.capability &&
          receipt.workId===context?.workId && receipt.operationId===context?.operationId &&
          receipt.requestHash===context?.requestHash;
        const outcome=exact&&["APPLIED","NOT_APPLIED"].includes(receipt.outcome)?receipt.outcome:"UNKNOWN";
        const record=Object.freeze({outcome,receipt:exact?receipt:null,context:Object.freeze({...context})});
        statuses.set(id,record);
        return record;
      }catch(error){
        const record=Object.freeze({outcome:"UNKNOWN",context:Object.freeze({...context}),error:String(error?.message||error)});
        statuses.set(id,record);return record;
      }finally{inFlight=false;render();}
    }
    async function resolveUnknown(id,proof){
      const cmd=commands.get(id), original=statuses.get(id);
      if(!cmd||original?.outcome!=="UNKNOWN")throw new Error("NO_UNKNOWN_COMMAND");
      if(typeof reconcile!=="function")throw new Error("EXACT_RECEIPT_PORT_REQUIRED");
      const receipt=await reconcile(cmd,proof);
      if(!receipt||receipt.schema!=="monitor.tool.reconciliation.v1"||
        !["APPLIED","NOT_APPLIED"].includes(receipt.outcome)||
        receipt.toolId!==cmd.toolId || receipt.workId!==original.context?.workId ||
        receipt.operationId!==original.context?.operationId ||
        receipt.requestHash!==original.context?.requestHash
      )throw new Error("RECONCILIATION_UNVERIFIED");
      statuses.set(id,Object.freeze({outcome:receipt.outcome,receipt}));render();
      return receipt.outcome;
    }
    return Object.freeze({setCommands,render,request,resolveUnknown,
      snapshot:id=>statuses.get(id)||null});
  }
  globalThis.MonitorDiagnosticsCommandView=Object.freeze({create});
})();
