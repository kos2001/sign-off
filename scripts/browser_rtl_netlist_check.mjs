import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE);
const fixture=JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE,'utf8'));
const base=process.env.SIGNOFF_TEST_UI;
assert.equal(base,'http://127.0.0.1:15174');
const browser=await chromium.launch({headless:true});
try {
 const context=await browser.newContext();
 async function login(role){
  const response=await context.request.post(`${base}/api/auth/login`,{headers:{'X-Signoff-Client':'1'},data:{username:`qa-${role}`,password:fixture.password}});
  assert.equal(response.status(),200);return response.json();
 }
 const editor=await login('editor');
 async function create(code){
  const response=await context.request.post(`${base}/api/analysis/rtl-signoff`,{headers:{'X-CSRF-Token':editor.csrf_token},timeout:90000,data:{project_id:fixture.project,code}});
  assert.equal(response.status(),200);return response.json();
 }
 const good=await create('module top(input a,output y); assign y=~a; endmodule');
 const bad=await create('module top(input a,output y); assign y=missing; endmodule');
 assert.equal(good.verdict,'CONDITIONAL');assert.ok(good.netlist);assert.equal(bad.netlist,null);
 await login('viewer');
 const before=await (await context.request.get(`${base}/api/runs/${good.run_id}/evidence`)).json();
 const page=await context.newPage();page.setDefaultTimeout(10000);
 await page.route('**/api/agents/review/gate',route=>route.fulfill({json:{a5:{triggered:false,available:null},v:null}}));
 await page.goto(`${base}/projects/${fixture.project}`);
 await page.getByRole('listitem',{name:`런 #${good.run_id}`,exact:true}).getByRole('button',{name:'실행 근거 보기',exact:true}).click();
 const panel=page.getByRole('region',{name:`런 #${good.run_id} 실행 근거`,exact:true}).getByRole('region',{name:'합성 넷리스트',exact:true});
 await panel.getByText(`SHA-256: ${good.netlist.sha256}`,{exact:true}).waitFor();
 const writes=[];page.on('request',request=>{if(request.method()!=='GET')writes.push(request.url());});
 await page.route(`**/api/runs/${good.run_id}/evidence/netlist`,route=>route.fulfill({status:409,json:{detail:'QA netlist integrity failure'}}));
 await panel.getByRole('button',{name:'합성 넷리스트 다운로드',exact:true}).click();
 await panel.getByRole('alert').filter({hasText:'QA netlist integrity failure'}).waitFor();
 await page.unroute(`**/api/runs/${good.run_id}/evidence/netlist`);
 const event=page.waitForEvent('download');
 await panel.getByRole('button',{name:'합성 넷리스트 다운로드',exact:true}).click();
 const download=await event;
 assert.equal(download.suggestedFilename(),`run-${good.run_id}-netlist.v`);
 const bytes=await readFile(await download.path());
 assert.deepEqual(bytes,Buffer.from(good.netlist.text));
 assert.equal(createHash('sha256').update(bytes).digest('hex'),good.netlist.sha256);
 assert.equal(bytes.length,good.netlist.byte_length);
 await panel.getByText('넷리스트 일치 확인 · 다운로드를 시작했습니다.',{exact:true}).waitFor();
 await mkdir('/private/tmp/signoff-rtl-netlist-check',{recursive:true});
 for(const width of [320,390,1440]){
  await page.setViewportSize({width,height:900});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  if(width===390)await panel.screenshot({path:'/private/tmp/signoff-rtl-netlist-check/netlist.png'});
 }
 assert.deepEqual(writes,[]);
 assert.deepEqual(await (await context.request.get(`${base}/api/runs/${good.run_id}/evidence`)).json(),before);
 await page.getByRole('listitem',{name:`런 #${bad.run_id}`,exact:true}).getByRole('button',{name:'실행 근거 보기',exact:true}).click();
 const failed=page.getByRole('region',{name:`런 #${bad.run_id} 실행 근거`,exact:true}).getByRole('region',{name:'합성 넷리스트',exact:true});
 await failed.getByText('넷리스트 미보관 · 합성 미완료 또는 이전 실행입니다.',{exact:true}).waitFor();
 assert.equal(await failed.getByRole('button',{name:'합성 넷리스트 다운로드',exact:true}).count(),0);
 console.log('PASS: actual worker netlist, viewer download exact bytes/hash, integrity failure/retry, failed synthesis absence, no writes, immutable evidence, responsive scope notice');
}finally{await browser.close();}
