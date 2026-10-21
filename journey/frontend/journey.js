/* First-party, opt-in coarse events only. No form/DOM scraping or click stream. */
(() => {
  'use strict';
  // Component runtime announces itself through Streamlit render; landing boots explicitly below.
  const VERSION='journey-2026-10-v1';
  const PROD=['https://www.o-plates.com','https://o-plates.com'];
  const STAGE=['https://oplates-landing-page-staging.onrender.com'];
  const QUOTES=['https://quote.o-plates.com','https://oplates-customer-ui-staging.onrender.com'];
  const APIS=['https://orifice-pricing-api.onrender.com','https://oplates-pricing-api-staging.onrender.com'];
  const fields=['version','event_id','timestamp','step','outcome','category','source'];
  const steps=['landing','configurator','configuration','quote','analyzer','cart','pdf_quote','checkout'];
  const outcomes=['reached','success','attempted','blocked','error'];
  const categories=['none','invalid_input','unsupported','api_failure','system_restriction','technical_failure'];
  const tokenOK=t=>typeof t==='string' && /^[a-f0-9]{32}\.[0-9]{10}\.[a-f0-9]{64}$/.test(t);
  let app,config,token=null,internal=false,consent=false,nonce=null,pending=false,last=0,epoch=0;
  let seen=new Set(),pendingEvents=[], controller=null,publishedSession;
  const protectedBrowser=()=>app.navigator.globalPrivacyControl===true || app.navigator.doNotTrack==='1';
  function read(key,session=false){try{return JSON.parse((session?app.sessionStorage:app.localStorage).getItem(key));}catch(_){return null;}}
  function write(key,value,session=false){try{const store=session?app.sessionStorage:app.localStorage;if(value===null)store.removeItem(key);else store.setItem(key,JSON.stringify(value));}catch(_){}}
  function sharedCookie(value){
    if(![...PROD,QUOTES[0]].includes(app.location.origin))return;
    try{app.document.cookie='oplates_journey_v1='+(value?encodeURIComponent(JSON.stringify(value)):'')+
      '; Domain=o-plates.com; Path=/; Secure; SameSite=Lax; Max-Age='+(value?'1800':'0');}catch(_){}
  }
  function readCookie(key){
    try {const text=app.document.cookie.split('; ').find(x=>x.startsWith(key+'='));
      return text?JSON.parse(decodeURIComponent(text.split('=').slice(1).join('='))):null;}catch(_){return null;}
  }
  function sharedChoice(value){
    if(![...PROD,QUOTES[0]].includes(app.location.origin))return;
    try{app.document.cookie='oplates_journey_choice='+encodeURIComponent(JSON.stringify(value))+
      '; Domain=o-plates.com; Path=/; Secure; SameSite=Lax; Max-Age=2592000';}catch(_){}
  }
  function saveSession(){const value={token,last,internal,version:VERSION};write('oplates-journey-session',value,true);sharedCookie(value);}
  function publish(){
    // Streamlit reruns on every component value message, including identical
    // null values. Publish identity transitions only, never each observation.
    if(!config.component || publishedSession===token)return;
    publishedSession=token;
    window.parent.postMessage({isStreamlitMessage:true,type:'streamlit:setComponentValue',value:{session:token},dataType:'json'},app.location.origin);
  }
  async function request(path,body,method='POST',useToken=true){
    const abort=new AbortController();const timer=setTimeout(()=>abort.abort(),1500);
    try{return await app.fetch(config.endpoint+path,{method,credentials:'omit',referrerPolicy:'no-referrer',signal:abort.signal,
      headers:{'Content-Type':'application/json',...(useToken&&token?{'X-Journey-Session':token}:{})},...(body?{body:JSON.stringify(body)}:{})});}
    catch(_){return null;}finally{clearTimeout(timer);}
  }
  function context(){return {type:'oplates:journey-context',version:1,nonce,session:token,consent,internal};}
  function share(){
    if(config.component)return;
    const frame=app.document.getElementById('plate-configurator');
    if(frame?.contentWindow && nonce)frame.contentWindow.postMessage(context(),new URL(frame.src,app.location.href).origin);
  }
  async function begin(){
    if(!consent || protectedBrowser() || pending)return;
    if(token && Number(token.split('.')[1])*1000>Date.now() && Date.now()-last<1800000){publish();share();return;}
    token=null;seen.clear();pending=true;const generation=epoch;
    const response=await request('/journey/session',{consent_version:VERSION,internal},'POST',false);
    if(response?.ok){try{const value=await response.json();if(consent&&generation===epoch&&tokenOK(value.session)){token=value.session;last=Date.now();saveSession();}}catch(_){}}
    pending=false;publish();share();
  }
  function valid(e){return e && Object.keys(e).length===fields.length && fields.every(k=>Object.hasOwn(e,k)) && e.version===1 &&
    steps.includes(e.step)&&outcomes.includes(e.outcome)&&categories.includes(e.category)&&['landing','direct','embed'].includes(e.source) &&
    typeof e.timestamp==='string' && typeof e.event_id==='string';}
  async function emit(e){
    const choice=readCookie('oplates_journey_choice');
    if(choice?.version===VERSION&&choice.allow===false){consent=false;token=null;publish();render();return;}
    if(!valid(e) || !consent || protectedBrowser())return;
    if(!token){if(pendingEvents.length<16)pendingEvents.push(e);return;}
    if(Date.now()-last>=1800000||Number(token.split('.')[1])*1000<=Date.now()){await begin();if(!token)return;}
    const key=[e.step,e.outcome,e.category,e.source].join(':');if(seen.has(key))return;
    if(seen.size>=100)return;seen.add(key);last=Date.now();saveSession();
    const response=await request('/journey/event',e);
    if(response?.status===410&&consent&&!protectedBrowser()){
      // A staging restart or token expiry cannot leave diagnostics permanently stale.
      token=null;write('oplates-journey-session',null,true);sharedCookie(null);
      await begin();
      if(token)await request('/journey/event',e); // One best-effort retry; never blocks the customer.
    }
  }
  function event(step,outcome='reached',category='none'){return {version:1,event_id:app.crypto.randomUUID(),timestamp:new Date().toISOString(),step,outcome,category,source:config.source};}
  async function flush(){const events=pendingEvents.splice(0,16);for(const e of events)await emit(e);}
  async function choose(allow){
    const previous=token;epoch++;consent=allow&&!protectedBrowser();
    if(!allow && previous)await request('/journey/session',null,'DELETE');
    consent=allow&&!protectedBrowser();token=null;seen.clear();pendingEvents=[];
    write('oplates-journey-session',null,true);sharedCookie(null);const choice={allow:consent,internal,version:VERSION,at:Date.now()};write('oplates-journey-preference',choice);sharedChoice(choice);
    publish();share();render();
    if(consent){await begin();await initial();await flush();}
  }
  function render(){
    const root=window.document.getElementById('journey-consent');if(!root)return;
    root.replaceChildren();root.hidden=false;
    if(config.source==='embed') {height(0);return;}
    const note=document.createElement('span');note.textContent=protectedBrowser()?'Journey diagnostics disabled by your browser privacy preference.':
      'Optional anonymous journey diagnostics help us find quoting problems. No field values, drawings or recordings. Timelines: 7 days; daily totals: 90 days. ';
    root.append(note);const policy=document.createElement('a');policy.textContent='Privacy';policy.href=config.endpoint===APIS[0]?'https://www.o-plates.com/privacy.html':'https://oplates-landing-page-staging.onrender.com/privacy.html';policy.target='_blank';policy.rel='noopener';root.append(policy);
    if(!protectedBrowser()){
      const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.checked=internal;check.disabled=consent||config.endpoint===APIS[1];check.onchange=()=>{internal=check.checked;};label.append(check,' Internal test session');root.append(label);
      for(const [label,allow] of [[consent?'Diagnostics enabled':'Allow diagnostics',true],[consent?'Turn off and delete this session':'Decline',false]]){
        const button=document.createElement('button');button.textContent=label;button.disabled=allow&&consent;button.onclick=()=>{choose(allow).catch(()=>{});};root.append(button);
      }
    }
    height(Math.min(350,Math.max(40,(Number(root.scrollHeight)||98)+12)));
  }
  function height(value){if(config.component)window.parent.postMessage({isStreamlitMessage:true,type:'streamlit:setFrameHeight',height:value},app.location.origin);}
  async function initial(){
    if(config.source==='landing')await emit(event('landing'));
    else if(config.entry)await emit(event(config.entry));
  }
  function receive(e){
    const data=e.data;
    if(config.component){
      const allowed=app.location.origin===QUOTES[0]?PROD:STAGE;
      if(!allowed.includes(e.origin)||e.source!==app.parent||data?.type!=='oplates:journey-context'||data.version!==1||data.nonce!==nonce)return;
      if(Object.keys(data).some(k=>!['type','version','nonce','session','consent','internal'].includes(k)))return;
      const previous=token;consent=data.consent===true&&!protectedBrowser();token=consent&&tokenOK(data.session)?data.session:null;internal=data.internal===true;
      if(previous!==token)seen.clear();last=Date.now();if(token)saveSession();else sharedCookie(null);publish();initial().then(flush).catch(()=>{});
    } else {
      const frame=app.document.getElementById('plate-configurator');
      if(!frame||!frame.contentWindow||e.origin!==new URL(frame.src,app.location.href).origin||!QUOTES.includes(e.origin))return;
      // Streamlit components are direct children of the configured quote iframe.
      let trusted=e.source===frame.contentWindow;
      for(let i=0;!trusted&&i<frame.contentWindow.length;i++)trusted=e.source===frame.contentWindow[i];
      if(!trusted)return;
      if(data?.type!=='oplates:journey-ready'||data.version!==1||typeof data.nonce!=='string'||!/^[a-f0-9-]{36}$/.test(data.nonce))return;
      nonce=data.nonce;share();
    }
  }
  async function boot(args,isComponent){
    if(config)return;app=isComponent?window.parent:window;
    const endpoint=args.endpoint?.replace(/\/$/,'');if(!APIS.includes(endpoint))return;
    if((endpoint===APIS[0]) !== [...PROD,QUOTES[0]].includes(app.location.origin))return;
    publishedSession=args.session??null;
    config={endpoint,source:args.source,component:isComponent,entry:['configurator','cart'].includes(args.entry)?args.entry:null};
    const pref=readCookie('oplates_journey_choice')||read('oplates-journey-preference');consent=Boolean(pref?.version===VERSION&&pref.allow===true&&Date.now()-pref.at<2592000000&&!protectedBrowser());internal=pref?.internal===true;
    const shared=readCookie('oplates_journey_v1');if(pref?.allow!==false&&shared?.version===VERSION&&tokenOK(shared.token)&&Date.now()-shared.last<1800000&&!protectedBrowser()){consent=true;internal=shared.internal===true;}
    const saved=read('oplates-journey-session',true)||shared;if(consent&&tokenOK(saved?.token)&&Date.now()-saved.last<1800000){token=saved.token;last=saved.last;internal=saved.internal===true;}
    if(endpoint===APIS[1])internal=true;
    publish();
    app.addEventListener('message',receive);
    app.__oplatesJourneyEmit=emit;
    app.__oplatesJourneyInternal=()=>{internal=true;if(token){request('/journey/internal',{}).catch(()=>{});saveSession();sharedChoice({allow:true,internal:true,version:VERSION,at:Date.now()});share();}};
    if(app.__oplatesJourneyOwnerTest===true)internal=true;
    render();
    if(config.source==='embed'){
      nonce=app.crypto.randomUUID();const parents=app.location.origin===QUOTES[0]?PROD:STAGE;
      for(const origin of parents)app.parent.postMessage({type:'oplates:journey-ready',version:1,nonce},origin);
      return;
    }
    await begin();await initial();await flush();
    if(config.source==='landing'){
      const target=app.document.getElementById('configurator');
      if(target){const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){emit(event('configurator'));observer.disconnect();}},{threshold:0.1});observer.observe(target);}
    }
  }
  window.addEventListener('message',e=>{
    if(e.source!==window.parent||e.data?.type!=='streamlit:render')return;
    boot(e.data.args,true).catch(()=>{});
  });
  if(window.OPLATES_JOURNEY?.enabled===true)boot({source:'landing',endpoint:window.OPLATES_JOURNEY.endpoint},false).catch(()=>{});
  else if(window.parent!==window)window.parent.postMessage({isStreamlitMessage:true,type:'streamlit:componentReady',apiVersion:1},window.location.origin);
})();
