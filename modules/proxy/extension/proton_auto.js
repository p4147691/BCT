(() => {
  const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
  const visible=(el)=>!!el && !!(el.offsetWidth||el.offsetHeight||el.getClientRects().length);
  const txt=(el)=>String((el&& (el.innerText||el.textContent))||"").replace(/\s+/g," ").trim();
  const clickable=()=>[...document.querySelectorAll('button,a,[role="button"],label')].filter(visible);
  const exactAll=(re,root=document)=>[...root.querySelectorAll('button,a,[role="button"],label')].filter(el=>visible(el)&&re.test(txt(el)));
  const exact=(re,root=document)=>exactAll(re,root)[0]||null;
  const contains=(re,root=document)=>[...root.querySelectorAll('button,a,[role="button"],label,h1,h2,h3,h4,div,span')].find(el=>visible(el)&&re.test(txt(el)));

  let createClicked=false;

  async function progress(state,detail=""){
    try{await chrome.runtime.sendMessage({type:"protonProgress",state:state,detail:detail});}catch(_){}
  }
  async function active(){
    try{return await chrome.runtime.sendMessage({type:"getProtonJob"});}catch(_){return {active:false};}
  }
  function setNativeValue(input,value){
    const proto=input instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
    const descriptor=Object.getOwnPropertyDescriptor(proto,"value");
    const setter=descriptor&&descriptor.set;
    if(setter)setter.call(input,value);else input.value=value;
    input.dispatchEvent(new Event("input",{bubbles:true}));
    input.dispatchEvent(new Event("change",{bubbles:true}));
  }
  function wireguardContainer(){
    const mark=contains(/WireGuard/i);
    if(!mark)return null;
    let cur=mark;
    for(let i=0;cur&&i<8;i++,cur=cur.parentElement){
      const t=txt(cur);
      if(/WireGuard/i.test(t) && (cur.querySelector('input') || /Create|생성|Download|다운로드/i.test(t))) return cur;
    }
    return mark.parentElement||document;
  }
  function downloadForNamedConfig(container){
    const named=[...container.querySelectorAll('*')].filter(el=>visible(el)&&/^Chrome-Auto-Proxy(?:\s|$)/i.test(txt(el))&&txt(el).length<160);
    for(const el of named.reverse()){
      let cur=el;
      for(let i=0;cur&&i<7;i++,cur=cur.parentElement){
        const b=exact(/^(다운로드|Download)$/i,cur);
        if(b)return b;
      }
    }
    const all=exactAll(/^(다운로드|Download)$/i,container);
    return all.length?all[all.length-1]:null;
  }

  async function run(){
    const gate=await active();
    if(!gate||!gate.active)return;

    for(let round=0;round<160;round++){
      const g=await active();
      if(!g||!g.active)return;

      const body=txt(document.body);
      if((document.querySelector('input[type="password"]') || /Sign in to Proton|Proton에 로그인|로그인.*Proton/i.test(body)) && !/WireGuard/i.test(body)){
        await progress("login_required","로그인 후 자동으로 계속됩니다");
        return;
      }

      const container=wireguardContainer();
      if(container){
        if(createClicked){
          const dl=downloadForNamedConfig(container);
          if(dl){
            await progress("downloading","새 WireGuard 설정 파일 다운로드 중");
            dl.click();
            return;
          }
          await progress("creating","설정 생성 완료를 기다리는 중");
          await sleep(900);
          continue;
        }

        const inputs=[...container.querySelectorAll('input[type="text"],input:not([type])')].filter(visible);
        if(inputs.length){
          await progress("configuring","WireGuard 설정 준비 중");
          const target=inputs.find(i=>/device|certificate|기기|증명서/i.test((i.getAttribute("placeholder")||"")+" "+(i.getAttribute("aria-label")||""))) || inputs[0];
          setNativeValue(target,"Chrome-Auto-Proxy");

          const win=exact(/^Windows$/i,container);
          if(win)win.click();

          let create=null;
          const nl=[...container.querySelectorAll('*')].find(el=>visible(el)&&/NL-FREE#/i.test(txt(el))&&txt(el).length<100);
          if(nl){
            let cur=nl;
            for(let i=0;cur&&i<7;i++,cur=cur.parentElement){
              const b=exact(/^(생성|Create)$/i,cur);
              if(b){create=b;break;}
            }
          }
          if(!create){
            const free=[...container.querySelectorAll('*')].find(el=>visible(el)&&/(무료 서버 구성|Free server configuration)/i.test(txt(el))&&txt(el).length<220);
            if(free){
              let cur=free;
              for(let i=0;cur&&i<6;i++,cur=cur.parentElement){
                const b=exact(/^(생성|Create)$/i,cur);
                if(b){create=b;break;}
              }
            }
          }
          if(!create)create=exact(/^(생성|Create)$/i,container);
          if(create){
            createClicked=true;
            await progress("creating","무료 WireGuard 설정 생성 중");
            create.click();
            await sleep(1400);
            continue;
          }
        }
      }

      const wg=exact(/WireGuard.*(구성|설정|configuration)/i) || exact(/^WireGuard$/i);
      if(wg){
        await progress("navigating","WireGuard 설정 화면으로 이동");
        wg.click();
        await sleep(1000);
        continue;
      }

      const downloads=clickable().find(el=>/^(다운로드|Downloads)$/i.test(txt(el)));
      if(downloads){
        await progress("navigating","다운로드 메뉴로 이동");
        downloads.click();
        await sleep(1000);
        continue;
      }

      await sleep(900);
    }

    await progress("manual_required","자동 생성 버튼을 찾지 못했습니다. 열린 Proton 화면에서 WireGuard 설정을 한 번 생성해 주세요.");
  }

  run().catch(async e=>{
    await progress("manual_required",String(e));
  });
})();
