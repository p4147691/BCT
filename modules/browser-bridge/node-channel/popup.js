"use strict";
const el=id=>document.getElementById(id);
const result=el("result"),list=el("nodes");
const show=data=>{ result.textContent=JSON.stringify(data,null,2); };
async function refresh(){
  list.textContent="";
  const r=await chrome.runtime.sendMessage({type:"BRIDGE_NODE_LIST"});
  if(!r?.ok){show(r);return;}
  for(const node of r.nodes){
    const area=document.createElement("section");
    const label=document.createElement("strong");
    label.textContent=node.title+" · "+(node.nodeId||"미등록");
    const sub=document.createElement("small");
    sub.textContent=" #"+node.tabId+" "+node.conversationKey;
    area.append(label,document.createElement("br"),sub,document.createElement("br"));
    const choice=document.createElement("select");
    for(const name of ["N13","N14","N23","N21","N22","N24"]){
      const option=document.createElement("option");option.value=name;option.textContent=name;
      choice.appendChild(option);
    }
    if(node.nodeId)choice.value=node.nodeId;
    const bind=document.createElement("button");bind.textContent="노드 등록";
    bind.onclick=async()=>{
      show(await chrome.runtime.sendMessage({type:"BRIDGE_NODE_BIND",
        nodeId:choice.value,conversationKey:node.conversationKey}));
      await refresh();
    };
    const read=document.createElement("button");read.textContent="노드 응답 읽기";
    read.disabled=!node.nodeId;
    read.onclick=async()=>{
      show(await chrome.runtime.sendMessage({type:"BRIDGE_NODE_READ",
        nodeId:node.nodeId,conversationKey:node.conversationKey,tabId:node.tabId}));
    };
    area.append(choice,bind,read);list.append(area);
  }
  el("group").disabled=r.nodes.filter(n=>n.nodeId).length<2;
  if(r.duplicates?.length)show({warning:"같은 대화 UUID가 여러 탭에 있어 해당 노드를 읽지 않음",duplicates:r.duplicates});
}
el("refresh").onclick=()=>refresh().catch(e=>show({error:String(e)}));
el("group").onclick=async()=>{
  const nodes=(await chrome.runtime.sendMessage({type:"BRIDGE_NODE_LIST"})).nodes||[];
  const targets=nodes.filter(n=>n.nodeId).map(n=>({
    nodeId:n.nodeId,conversationKey:n.conversationKey,tabId:n.tabId
  }));
  if(targets.length<2||targets.length>6){show({error:"2~6개 등록 노드 필요"});return;}
  show(await chrome.runtime.sendMessage({type:"BRIDGE_NODE_READ_GROUP",targets}));
};
refresh().catch(e=>show({error:String(e)}));
