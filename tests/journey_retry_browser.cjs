/* Isolated protocol tests. fetch is entirely synthetic; no browser/account/production access. */
const assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {environment,tick}=require('./journey_browser.cjs');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const event=(step='quote')=>({version:1,event_id:randomUUID(),timestamp:new Date().toISOString(),step,outcome:'success',category:'none',source:'direct'});
const button=(env,text)=>env.root.children.find(n=>n.textContent===text);
const allow=async env=>{button(env,'Allow diagnostics').onclick();await tick();};
const withdraw=async env=>{button(env,'Turn off and delete this session').onclick();await tick();};
const events=env=>env.calls.filter(c=>c.url.endsWith('/journey/event'));
async function until(test){for(let i=0;i<300&&!test();i++)await tick();assert(test(),'Synthetic operation did not start');}
async function main(){
  // Every transient retry reuses the full immutable event body, not a new UUID.
  for(const failure of ['network','timeout',429,503]){
    const env=environment();await tick();const native=env.app.fetch;let tries=0;
    env.app.fetch=async(url,opts)=>{
      const response=await native(url,opts);
      if(!url.endsWith('/journey/event'))return response;
      if(++tries===1){
        if(failure==='network')throw Error('synthetic network failure');
        if(failure==='timeout')return new Promise((_,reject)=>opts.signal.addEventListener('abort',()=>reject(Error('synthetic abort')),{once:true}));
        return {ok:false,status:failure};
      }
      return response;
    };
    await allow(env);await until(()=>events(env).length===2);
    assert.equal(events(env).length,2,String(failure));
    assert.equal(events(env)[0].opts.body,events(env)[1].opts.body,'Original UUID and timestamp retained');
    assert.equal(events(env)[0].opts.headers['X-Journey-Session'],events(env)[1].opts.headers['X-Journey-Session']);
  }
  // Exhaustion reserves the key separately from delivery. Rerenders cannot storm.
  const down=environment();await tick();const nativeDown=down.app.fetch;
  down.app.fetch=async(url,opts)=>{const r=await nativeDown(url,opts);return url.endsWith('/journey/event')?{ok:false,status:503}:r;};
  await allow(down);await until(()=>events(down).length===2);assert.equal(events(down).length,2);
  for(let i=0;i<20;i++)await down.app.__oplatesJourneyEmit({...JSON.parse(events(down)[0].opts.body),event_id:randomUUID()});
  assert.equal(events(down).length,2,'Two attempts maximum per observation/session');
  // Concurrent rerenders share the reservation while the original request awaits ACK.
  const concurrent=environment();await tick();const nativeConcurrent=concurrent.app.fetch;let finish;
  concurrent.app.fetch=async(url,opts)=>{const r=await nativeConcurrent(url,opts);return url.endsWith('/journey/event')?new Promise(resolve=>{finish=()=>resolve(r);}):r;};
  const first=allow(concurrent);await until(()=>finish);
  const duplicate=concurrent.app.__oplatesJourneyEmit({...JSON.parse(events(concurrent)[0].opts.body),event_id:randomUUID()});
  assert.equal(events(concurrent).length,1);finish();await Promise.all([first,duplicate]);
  await concurrent.app.__oplatesJourneyEmit({...JSON.parse(events(concurrent)[0].opts.body),event_id:randomUUID()});
  assert.equal(events(concurrent).length,1,'Successful 204 suppresses subsequent stage duplicates');
  // Non-retryable invalid/unauthorized requests must not loop.
  for(const status of [200,400,403]){
    const env=environment();await tick();const native=env.app.fetch;
    env.app.fetch=async(url,opts)=>{const r=await native(url,opts);return url.endsWith('/journey/event')?{ok:status===200,status}:r;};
    await allow(env);assert.equal(events(env).length,1);
  }
  // Preserve one expiry recovery, within the same two-event-attempt budget.
  const expired=environment();await tick();const nativeExpired=expired.app.fetch;
  expired.app.fetch=async(url,opts)=>{const r=await nativeExpired(url,opts);return url.endsWith('/journey/event')?{ok:false,status:410}:r;};
  await allow(expired);
  assert.equal(events(expired).length,2);
  assert.equal(expired.calls.filter(c=>c.url.endsWith('/journey/session')).length,2);
  assert.equal(events(expired)[0].opts.body,events(expired)[1].opts.body);
  // Cancel backoff for withdrawal, GPC, DNT and shared-cookie refusal.
  for(const restriction of ['withdraw','gpc','dnt','cookie']){
    const env=environment();await tick();const native=env.app.fetch;
    env.app.fetch=async(url,opts)=>{const r=await native(url,opts);return url.endsWith('/journey/event')?{ok:false,status:503}:r;};
    const delivery=allow(env);await until(()=>events(env).length===1);
    if(restriction==='withdraw')await withdraw(env);
    if(restriction==='gpc')env.app.navigator.globalPrivacyControl=true;
    if(restriction==='dnt')env.app.navigator.doNotTrack='1';
    if(restriction==='cookie')env.cookies.set('oplates_journey_choice',encodeURIComponent(JSON.stringify({version:'journey-2026-10-v1',allow:false})));
    await delivery;await sleep(300);
    assert.equal(events(env).length,1,restriction+' must stop the scheduled retry');
    await env.app.__oplatesJourneyEmit(event('cart'));assert.equal(events(env).length,1);
    if(restriction==='withdraw')assert(env.calls.some(c=>c.opts.method==='DELETE'));
  }
  // Abort in-flight telemetry too; an already sent request cannot be unsent.
  for(const restriction of ['withdraw','gpc']){
    const env=environment();await tick();const native=env.app.fetch;let aborted=false;
    env.app.fetch=async(url,opts)=>{
      const r=await native(url,opts);if(!url.endsWith('/journey/event'))return r;
      return new Promise((_,reject)=>opts.signal.addEventListener('abort',()=>{aborted=true;reject(Error('synthetic abort'));},{once:true}));
    };
    const delivery=allow(env);await until(()=>events(env).length===1);
    if(restriction==='withdraw')await withdraw(env);else env.app.navigator.globalPrivacyControl=true;
    await delivery;await until(()=>aborted);await sleep(300);assert.equal(events(env).length,1);
  }
  // Withdrawing and opting in again never revives an old generation's retry.
  const renewed=environment();await tick();const nativeRenewed=renewed.app.fetch;let tries=0;
  renewed.app.fetch=async(url,opts)=>{const r=await nativeRenewed(url,opts);return url.endsWith('/journey/event')&&++tries===1?{ok:false,status:503}:r;};
  const old=allow(renewed);await until(()=>events(renewed).length===1);await withdraw(renewed);await allow(renewed);await old;await sleep(300);
  assert.equal(events(renewed).length,2);
  assert.notEqual(JSON.parse(events(renewed)[0].opts.body).event_id,JSON.parse(events(renewed)[1].opts.body).event_id);
  // Parent withdrawal cancels an embedded component's pending retry.
  const embedded=environment({component:true,source:'embed'});await tick();const nativeEmbedded=embedded.app.fetch;
  embedded.app.fetch=async(url,opts)=>{const r=await nativeEmbedded(url,opts);return url.endsWith('/journey/event')?{ok:false,status:503}:r;};
  const nonce=embedded.messages.find(m=>m.data.type==='oplates:journey-ready').data.nonce;
  const context={type:'oplates:journey-context',version:1,nonce,session:embedded.token,consent:true,internal:true};
  const receive=embedded.appListeners.message[0],sender={origin:'https://www.o-plates.com',source:embedded.app.parent};
  receive({...sender,data:context});await until(()=>events(embedded).length===1);
  receive({...sender,data:{...context,session:null,consent:false}});await sleep(350);
  assert.equal(events(embedded).length,1);
  // A session response arriving after privacy restriction cannot set an identifier.
  const pending=environment();await tick();const nativePending=pending.app.fetch;let finishStart;
  pending.app.fetch=async(url,opts)=>{const r=await nativePending(url,opts);return url.endsWith('/journey/session')?new Promise(resolve=>{finishStart=()=>resolve(r);}):r;};
  const starting=allow(pending);await until(()=>finishStart);pending.app.navigator.doNotTrack='1';finishStart();await starting;
  assert.equal(events(pending).length,0);assert(!pending.cookies.has('oplates_journey_v1'));
  // Keep the existing 100-observation cap; bounded failures also consume slots.
  const capped=environment();await tick();await allow(capped);
  const combos=[['reached','none'],['success','none'],['blocked','system_restriction'],...['invalid_input','unsupported','api_failure','technical_failure'].map(c=>['error',c])];
  for(const source of ['direct','embed'])for(const step of ['landing','configurator','configuration','quote','analyzer','cart','pdf_quote','checkout'])for(const [outcome,category] of combos){
    await capped.app.__oplatesJourneyEmit({...event(step),source,outcome,category});
  }
  assert.equal(events(capped).length,100);
  console.log('ACK/retry protocol passed: immutable UUIDs; bounded retry and expiry recovery; concurrent dedup; terminal errors; withdrawal/GPC/DNT/cookie/parent cancellation; in-flight abort; stale response rejection; 100-observation cap.');
}
main().catch(e=>{console.error(e);process.exitCode=1});
