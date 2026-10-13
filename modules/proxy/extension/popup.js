const $ = (id) => document.getElementById(id);
async function call(msg){ return await chrome.runtime.sendMessage(msg); }
function jobText(job){
  if(!job) return "현재 설정 사용 중";
  const map={
    opening:"Proton 페이지 여는 중",
    navigating:"설정 화면 찾는 중",
    login_required:"Proton 로그인 필요",
    configuring:"WireGuard 설정 입력 중",
    creating:"설정 생성 중",
    downloading:"설정 다운로드 중",
    importing:"다운로드 파일 적용 중",
    ready:"새 설정 적용 완료",
    error:"설정 적용 실패",
    manual_required:"자동 처리 확인 필요"
  };
  return (map[job.state]||job.state||"처리 중") + (job.detail ? " · "+job.detail : "");
}
async function render(){
  const s=await call({type:"status"});
  const helper=s.helper||{};
  const controlled=s.proxyControl==="controlled_by_this_extension";
  const good=controlled&&helper.ok&&helper.proxy_alive;
  $("state").textContent=good?"● 자동 우회 활성":"● 확인 필요";
  $("state").className=good?"ok":"bad";
  $("helper").textContent=helper.config&&helper.config.server
    ? "Proton: "+helper.config.server
    : "로컬 프록시: "+(helper.state||"unknown");
  $("job").textContent=jobText(s.job);
  const list=$("routes"); list.textContent="";
  for(const d of (s.routes||[])){
    const li=document.createElement("li");
    li.textContent=d;
    list.appendChild(li);
  }
}
$("proton").addEventListener("click",async()=>{
  await call({type:"startProtonDownload"});
  window.close();
});
$("reset").addEventListener("click",async()=>{
  await chrome.storage.local.set({routedDomains:["f95zone.to"]});
  await render();
});
render().catch(e=>{
  $("state").textContent="상태 확인 실패";
  $("state").className="bad";
  console.error(e);
});
