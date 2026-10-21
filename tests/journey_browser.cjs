const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');const {randomUUID}=require('node:crypto');
const script=fs.readFileSync('journey/frontend/journey.js','utf8');
const tick=()=>new Promise(r=>setTimeout(r,10));
function environment({component=false,gpc=false,source='direct'}={}){
  const calls=[],messages=[],listeners={},appListeners={},cookies=new Map();
  const storage=()=>{const values=new Map();return {getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)}};
  function node(tag){return {tag,children:[],hidden:true,textContent:'',append(...v){this.children.push(...v)},replaceChildren(){this.children=[]}};}
  const root=node('div'),frameWindow={postMessage:(data,origin)=>messages.push({data,origin,target:'frame'})};
  const frame={src:'https://quote.o-plates.com/Quote?embed=true',contentWindow:frameWindow};
  const document={getElementById:id=>id==='journey-consent'?root:id==='plate-configurator'?frame:null,createElement:node};
  Object.defineProperty(document,'cookie',{get:()=>[...cookies].map(([k,v])=>k+'='+v).join('; '),set:value=>{
    const [entry,...attrs]=value.split('; ');const index=entry.indexOf('=');const key=entry.slice(0,index),v=entry.slice(index+1);
    if(attrs.includes('Max-Age=0'))cookies.delete(key);else cookies.set(key,v);
  }});
  const token='a'.repeat(32)+'.'+Math.floor(Date.now()/1000+86400)+'.'+'b'.repeat(64);
  const app={document,navigator:{globalPrivacyControl:gpc},crypto:{randomUUID},location:{origin:component?'https://quote.o-plates.com':'https://www.o-plates.com',href:'https://www.o-plates.com/'},sessionStorage:storage(),localStorage:storage(),
    addEventListener:(k,fn)=>(appListeners[k]??=[]).push(fn),fetch:async(url,opts)=>{calls.push({url,opts});return {ok:true,json:async()=>({session:token})}},postMessage:(data,origin)=>messages.push({data,origin,target:'app'})};
  app.parent=component?{postMessage:(data,origin)=>messages.push({data,origin,target:'host'})}:app;
  const window=component?{parent:app,document,location:app.location,addEventListener:(k,fn)=>(listeners[k]??=[]).push(fn)}:app;
  if(!component)window.OPLATES_JOURNEY={enabled:true,endpoint:'https://orifice-pricing-api.onrender.com'};
  const context={window,document,Date,JSON,URL,Object,Set,Number,Boolean,String,AbortController,setTimeout,clearTimeout,IntersectionObserver:class {observe(){} disconnect(){}}};
  vm.runInNewContext(script,context);
  if(component)for(const fn of listeners.message||[])fn({source:app,data:{type:'streamlit:render',args:{endpoint:'https://orifice-pricing-api.onrender.com',source,entry:'configurator'}}});
  return {calls,messages,root,app,frameWindow,appListeners,token,cookies};
}
async function main(){
  const first=environment();await tick();assert.equal(first.calls.length,0,'No identifier or request before opt-in');
  await first.root.children.find(n=>n.textContent==='Decline').onclick();await tick();assert.equal(first.calls.length,0);
  const allowed=environment();await tick();await allowed.root.children.find(n=>n.textContent==='Allow diagnostics').onclick();await tick();
  assert.equal(allowed.calls[0].url.endsWith('/journey/session'),true);
  assert.equal(allowed.calls[0].opts.credentials,'omit');assert.equal(allowed.calls[0].opts.referrerPolicy,'no-referrer');
  assert.equal(JSON.parse(allowed.calls[1].opts.body).step,'landing');
  const e={version:1,event_id:randomUUID(),timestamp:new Date().toISOString(),step:'quote',outcome:'success',category:'none',source:'direct'};
  await allowed.app.__oplatesJourneyEmit({...e,email:'do-not-capture@example.com'});assert.equal(allowed.calls.length,2,'Sensitive extra field rejected');
  await allowed.app.__oplatesJourneyEmit(e);await allowed.app.__oplatesJourneyEmit(e);assert.equal(allowed.calls.length,3,'Rerender duplicates suppressed');
  await allowed.root.children.find(n=>n.textContent==='Turn off and delete this session').onclick();await tick();
  assert.equal(allowed.calls.at(-1).opts.method,'DELETE');const count=allowed.calls.length;await allowed.app.__oplatesJourneyEmit({...e,step:'cart'});assert.equal(allowed.calls.length,count);
  assert(!allowed.cookies.has('oplates_journey_v1'));
  const recovery=environment();await tick();const originalFetch=recovery.app.fetch;let expired=true;
  recovery.app.fetch=async(url,opts)=>{const result=await originalFetch(url,opts);if(url.endsWith('/journey/event')&&expired){expired=false;return {ok:false,status:410};}return result;};
  await recovery.root.children.find(n=>n.textContent==='Allow diagnostics').onclick();await tick();
  assert.equal(recovery.calls.filter(r=>r.url.endsWith('/journey/session')).length,2,'Expired anonymous session recovers once without touching quoting');
  const privacy=environment({gpc:true});await tick();assert.equal(privacy.calls.length,0);assert(!privacy.root.children.some(n=>n.textContent==='Allow diagnostics'));
  const embedded=environment({component:true,source:'embed'});await tick();assert.equal(embedded.calls.length,0);
  const ready=embedded.messages.find(m=>m.data.type==='oplates:journey-ready');assert(ready);
  const context={type:'oplates:journey-context',version:1,nonce:ready.data.nonce,session:embedded.token,consent:true,internal:false};
  const receive=embedded.appListeners.message[0];
  receive({origin:'https://evil.invalid',source:embedded.app.parent,data:context});await tick();assert.equal(embedded.calls.length,0);
  receive({origin:'https://www.o-plates.com',source:{},data:context});await tick();assert.equal(embedded.calls.length,0);
  receive({origin:'https://www.o-plates.com',source:embedded.app.parent,data:{...context,nonce:randomUUID()}});await tick();assert.equal(embedded.calls.length,0);
  receive({origin:'https://www.o-plates.com',source:embedded.app.parent,data:{...context,credentials:'forbidden'}});await tick();assert.equal(embedded.calls.length,0);
  receive({origin:'https://www.o-plates.com',source:embedded.app.parent,data:context});await tick();assert.equal(embedded.calls.length,1);assert.equal(JSON.parse(embedded.calls[0].opts.body).source,'embed');
  const publications=env=>env.messages.filter(m=>m.data.type==='streamlit:setComponentValue');
  const beforeSame=publications(embedded).length;
  receive({origin:'https://www.o-plates.com',source:embedded.app.parent,data:context});await tick();
  assert.equal(publications(embedded).length,beforeSame,'Unchanged embedded identity must not rerun Streamlit');
  for(const source of ['direct','embed']){
    const declined=environment({component:true,source});await tick();
    if(source==='direct')await declined.root.children.find(n=>n.textContent==='Decline').onclick();
    else {
      const ready=declined.messages.find(m=>m.data.type==='oplates:journey-ready');
      declined.cookies.set('oplates_journey_choice',encodeURIComponent(JSON.stringify({version:'journey-2026-10-v1',allow:false})));
      declined.appListeners.message[0]({origin:'https://www.o-plates.com',source:declined.app.parent,
        data:{type:'oplates:journey-context',version:1,nonce:ready.data.nonce,session:null,consent:false,internal:true}});
    }
    await tick();const before=publications(declined).length;
    for(let i=0;i<12;i++)await declined.app.__oplatesJourneyEmit({...e,event_id:randomUUID(),source,step:i%2?'quote':'configuration'});
    assert.equal(publications(declined).length,before,'Declined observations must not cause a Streamlit rerun loop');
    assert.equal(declined.calls.length,0,'Declined diagnostics still send no analytics');
  }
  const host=environment();await tick();const hostReceive=host.appListeners.message.at(-1);
  hostReceive({origin:'https://quote.o-plates.com',source:{},data:{type:'oplates:journey-ready',version:1,nonce:randomUUID()}});
  assert(!host.messages.some(m=>m.target==='frame'));
  hostReceive({origin:'https://quote.o-plates.com',source:host.frameWindow,data:{type:'oplates:journey-ready',version:1,nonce:randomUUID()}});
  assert(host.messages.some(m=>m.target==='frame'&&m.origin==='https://quote.o-plates.com'));
  const nested={};host.frameWindow.length=1;host.frameWindow[0]=nested;
  const before=host.messages.length;
  hostReceive({origin:'https://quote.o-plates.com',source:nested,data:{type:'oplates:journey-ready',version:1,nonce:randomUUID()}});
  assert.equal(host.messages.length,before+1,'Only a direct child of the configured quote frame is also trusted');
  console.log('Browser protocol: consent, withdrawal, GPC, deduplication, sensitive-field rejection and origin/source/nonce checks passed.');
}
main().catch(e=>{console.error(e);process.exitCode=1});
