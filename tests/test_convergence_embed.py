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
      const context={document:{getElementById:id=>id==='y'?{}:frame,querySelectorAll:()=>[]},
        window:{addEventListener:(name,fn)=>handler=fn}};
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
