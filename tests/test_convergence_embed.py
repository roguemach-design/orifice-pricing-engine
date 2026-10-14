"""Only trusted configurator frames can resize the landing-page embed."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_embed_accepts_only_finite_heights_from_its_own_origin_and_frame():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for the embed message test")
    result = subprocess.run(
        [
            node,
            "-e",
            r"""
      const fs=require('fs'),vm=require('vm'),assert=require('assert');
      const child={},configWindow={0:child,length:1},frame={contentWindow:configWindow,style:{}};
      let handler;
      const context={document:{documentElement:{classList:{contains:()=>false}},getElementById:id=>id==='y'?{}:(id==='plate-configurator'?frame:null),querySelectorAll:()=>[]},
        window:{addEventListener:(name,fn)=>{if(name==='message')handler=fn}}};
      vm.runInNewContext(fs.readFileSync('o-plates landing/configurator.js','utf8'),context);
      const event={origin:'https://quote.o-plates.com',source:child,data:{type:'oplates:height',height:1400}};
      handler({...event,origin:'https://untrusted.example'});assert.strictEqual(frame.style.height,undefined);
      handler({...event,source:{}});assert.strictEqual(frame.style.height,undefined);
      for(const height of [NaN,Infinity,-1,399,30001,'1400']){
        handler({...event,data:{type:'oplates:height',height}});assert.strictEqual(frame.style.height,undefined);
      }
      handler(event);assert.strictEqual(frame.style.height,'1400px');
      handler({...event,source:configWindow,data:{type:'oplates:height',height:1800.5}});
      assert.strictEqual(frame.style.height,'1801px');
    """,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr



def test_feedback_projection_is_trusted_display_only_and_falls_back_on_narrow_screens():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for the embed message test")
    result = subprocess.run([node, "-e", r"""
      const fs=require('fs'),vm=require('vm'),assert=require('assert');
      const listeners={},messages=[];
      const element=()=>({children:[],style:{setProperty(k,v){this[k]=v}},classList:{toggle(k,v){this[k]=v}},
        append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items}});
      const stage=element(),rail=element();stage.getBoundingClientRect=()=>({height:2400});rail.hidden=true;
      const rootClasses={contains(k){return !!this[k]},toggle(k,v){this[k]=v}};
      const source={length:0,postMessage:(data,origin)=>messages.push({data,origin})};
      const frame={contentWindow:source,style:{},clientWidth:1080,offsetTop:20,offsetLeft:0};
      const context={document:{documentElement:{classList:rootClasses},getElementById:id=>({y:{},'plate-configurator':frame,'configurator-stage':stage,'configurator-feedback':rail}[id]),
        querySelector:()=>({getBoundingClientRect:()=>({height:68})}),querySelectorAll:()=>[],createElement:element},
        DOMParser:class{parseFromString(){return {documentElement:{localName:'parsererror'},querySelector:()=>null}}},
        window:{innerWidth:1363,addEventListener:(name,fn)=>listeners[name]=fn}};
      vm.runInNewContext(fs.readFileSync('o-plates landing/configurator.js','utf8'),context);
      const data={type:'oplates:layout',height:2400,feedback:{top:220,left:40,width:430,svg:'',
        prices:[{label:'Unit price',value:'$12.34'},{label:'Total price',value:'$24.68'}],
        previewNotice:'Complete dimensions.',priceNotice:'',shipping:'',fulfillment:[
          {label:'Estimated ship time',value:'21 calendar days'},
          {label:'Estimated total weight',value:'2.28 lb'},
          {label:'Estimated package',value:'14.5 × 7.0 × 1.0 in.'}]}};
      const event={origin:'https://quote.o-plates.com',source,data};
      listeners.message({...event,origin:'https://untrusted.example'});assert.equal(rail.hidden,true);
      listeners.message({...event,source:{}});assert.equal(rail.hidden,true);
      listeners.message(event);assert.equal(rail.hidden,false);assert.equal(rail.style.marginTop,'240px');
      assert.equal(stage.style['--preview-top'],'80px');
      assert.equal(rail.children[2].children[0].children[1].textContent,'$12.34');
      assert.equal(messages.at(-1).data.enabled,true);
      const summary=rail.children[3];
      assert.equal(summary.children[0].children[1].textContent,'21 calendar days');
      assert.equal(summary.children[1].textContent,'Shipping estimates');
      assert.equal(summary.children[2].children[0].children[1].textContent,'2.28 lb');
      assert.equal(summary.children[2].children[1].children[1].textContent,'14.5 × 7.0 × 1.0 in.');
      listeners.message({...event,origin:'https://untrusted.example',data:{...data,modalOpen:true}});
      assert.equal(rootClasses.contains('oplates-modal-open'),false);
      listeners.message({...event,data:{...data,height:500,modalOpen:true}});
      assert.equal(rootClasses.contains('oplates-modal-open'),true);
      assert.equal(stage.style['--modal-stage-height'],'2400px');
      assert.equal(frame.style.height,'2400px');
      assert.equal(rail.children[3],summary); // Modal opening preserves the preview content.
      listeners.message({...event,data:{...data,modalOpen:false}});
      assert.equal(rootClasses.contains('oplates-modal-open'),false);
      assert.equal(stage.style['--preview-top'],'80px');
      context.window.innerWidth=390;frame.clientWidth=350;listeners.resize();
      assert.equal(rail.hidden,true);assert.equal(messages.at(-1).data.enabled,false);
      context.window.innerWidth=1363;frame.clientWidth=1080;listeners.resize();assert.equal(rail.hidden,false);
      listeners.message({...event,data:{type:'oplates:layout',height:2400,feedback:null}});
      assert.equal(rail.hidden,true);assert.equal(messages.at(-1).data.enabled,false);
    """], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_checkout_navigation_requires_trusted_frame_and_test_stripe_url():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for the embed message test")
    result = subprocess.run([node, "-e", r"""
      const fs=require('fs'),vm=require('vm'),assert=require('assert');
      const listeners={},navigations=[],child={},frame={contentWindow:{0:child,length:1},style:{}};
      const context={URL,document:{documentElement:{classList:{contains:()=>false}},
        getElementById:id=>id==='y'?{}:(id==='plate-configurator'?frame:null),querySelectorAll:()=>[]},
        window:{location:{assign:url=>navigations.push(url)},addEventListener:(name,fn)=>listeners[name]=fn}};
      vm.runInNewContext(fs.readFileSync('o-plates landing/configurator.js','utf8'),context);
      const url='https://checkout.stripe.com/c/pay/cs_test_existing#existing-fragment';
      const event={origin:'https://quote.o-plates.com',source:child,data:{type:'oplates:checkout',url}};
      listeners.message({...event,origin:'https://untrusted.example'});
      listeners.message({...event,source:{}});
      for(const url of ['https://checkout.stripe.com/c/pay/cs_live_no',
          'https://checkout.stripe.com.evil.test/c/pay/cs_test_no',
          'http://checkout.stripe.com/c/pay/cs_test_no',
          'https://user@checkout.stripe.com/c/pay/cs_test_no','javascript:alert(1)','/c/pay/cs_test_no']) {
        listeners.message({...event,data:{type:'oplates:checkout',url}});
      }
      assert.deepEqual(navigations,[]);
      listeners.message(event);assert.deepEqual(navigations,[url]);
      assert.strictEqual(frame.style.height,undefined);
    """], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_embedded_checkout_uses_existing_url_without_changing_direct_navigation(monkeypatch):
    from types import SimpleNamespace
    import customer_navigation

    scripts, links, errors = [], [], []
    state = {}
    monkeypatch.setattr(customer_navigation, "st", SimpleNamespace(
        session_state=state, error=errors.append,
        link_button=lambda label, url: links.append(url)))
    monkeypatch.setattr(customer_navigation.components, "html", lambda html, **kwargs: scripts.append(html))
    url = "https://checkout.stripe.com/c/pay/cs_test_existing#existing-fragment"
    assert customer_navigation.render_integrated_checkout(url) is False
    assert not scripts and not links and not errors
    state["integrated_landing"] = True
    assert customer_navigation.render_integrated_checkout(url) is True
    assert links == [url]
    assert 'window.parent.parent.postMessage' in scripts[0]
    assert url in scripts[0]
    assert "refresh" not in scripts[0]
    assert customer_navigation.render_integrated_checkout(url.replace("cs_test_", "cs_live_")) is True
    assert len(scripts) == 1 and len(errors) == 1
