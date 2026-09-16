import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE);
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(base, 'http://127.0.0.1:15174');
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext();
  async function login(role) {
    const response = await context.request.post(`${base}/api/auth/login`, {headers:{'X-Signoff-Client':'1'},data:{username:`qa-${role}`,password:fixture.password}});
    assert.equal(response.status(),200); return response.json();
  }
  const editor = await login('editor');
  const code = ['module top(input logic a,output logic y);', '  assign y = missing;', 'endmodule', ...Array.from({length:147},(_,i)=>`// source line ${i+4}`), '// <img src=x onerror="window.sourceInjected=true">'].join('\n');
  async function create(source) {
    const response = await context.request.post(`${base}/api/analysis/rtl-signoff`, {headers:{'X-CSRF-Token':editor.csrf_token},timeout:90000,data:{project_id:fixture.project,code:source,top_module:'top'}});
    assert.equal(response.status(),200); const result=await response.json();
    assert.equal(result.execution.backend,'container'); assert.equal(result.verdict,'REJECTED'); return result;
  }
  const normal = await create(code);
  const remapped = await create(code.replace('  assign y', '`line 40 "design.sv" 0\n  assign y'));
  await login('viewer');
  const before = await (await context.request.get(`${base}/api/runs/${normal.run_id}/evidence`)).json();
  const page = await context.newPage(); page.setDefaultTimeout(10000);
  const errors=[]; page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/api/agents/review/gate',route=>route.fulfill({json:{a5:{role:'a5_synth',triggered:false,available:null},v:null}}));
  await page.goto(`${base}/projects/${fixture.project}`);
  await page.getByRole('listitem',{name:`런 #${normal.run_id}`,exact:true}).getByRole('button',{name:'실행 근거 보기',exact:true}).click();
  const evidence=page.getByRole('region',{name:`런 #${normal.run_id} 실행 근거`,exact:true});
  const inspector=evidence.getByRole('region',{name:'RTL 진단과 소스 탐색',exact:true});
  await inspector.getByRole('button',{name:'design.sv:2:14 줄 보기',exact:true}).first().waitFor();
  const writes=[]; page.on('request',req=>{if(req.method()!=='GET')writes.push(req.url());});
  // Integrity failure must not reveal an apparently verified source panel.
  await page.route(`**/api/runs/${normal.run_id}/evidence/source`,route=>route.fulfill({status:409,json:{detail:'QA source integrity failure'}}));
  await inspector.getByRole('button',{name:'design.sv:2:14 줄 보기',exact:true}).first().click();
  await inspector.getByRole('alert').filter({hasText:'QA source integrity failure'}).waitFor();
  assert.equal(await inspector.locator('pre').count(),0);
  await page.unroute(`**/api/runs/${normal.run_id}/evidence/source`);
  await page.route(`**/api/runs/${normal.run_id}/evidence/source`,route=>route.fulfill({body:'different source',contentType:'application/octet-stream'}));
  await inspector.getByRole('button',{name:'원본 다시 확인',exact:true}).click();
  await inspector.getByRole('alert').filter({hasText:'실행 근거와 다운로드한 소스가 다릅니다.'}).waitFor();
  assert.equal(await inspector.locator('pre').count(),0);
  await page.unroute(`**/api/runs/${normal.run_id}/evidence/source`);
  await inspector.getByRole('button',{name:'원본 다시 확인',exact:true}).click();
  const source=inspector.getByLabel('RTL 소스 · 선택 2줄',{exact:true});
  await source.waitFor();
  assert.equal(await source.locator('[aria-current="location"]').getAttribute('data-line'),'2');
  assert.ok((await source.locator('[data-line="2"]').textContent()).includes('assign y = missing;'));
  assert.ok(await source.evaluate(element=>document.activeElement===element));
  await inspector.getByLabel('줄 번호',{exact:true}).fill('99999999999999999999');
  assert.ok(await inspector.getByRole('button',{name:'줄로 이동',exact:true}).isDisabled());
  await inspector.getByLabel('줄 번호',{exact:true}).fill('151');
  await inspector.getByRole('button',{name:'줄로 이동',exact:true}).click();
  const last=inspector.getByLabel('RTL 소스 · 선택 151줄',{exact:true}); await last.waitFor();
  assert.ok((await last.textContent()).includes('<img src=x'));
  assert.equal(await last.locator('img').count(),0);
  assert.equal(await page.evaluate(()=>window.sourceInjected),undefined);
  assert.ok(await inspector.getByRole('button',{name:'다음 소스',exact:true}).isDisabled());
  await inspector.getByRole('button',{name:'이전 소스',exact:true}).click();
  await inspector.getByLabel('RTL 소스 · 선택 121줄',{exact:true}).waitFor();
  await mkdir('/private/tmp/signoff-rtl-diagnostics-check',{recursive:true});
  for(const width of [320,390,1440]){
    await page.setViewportSize({width,height:900});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    if(width===390) await inspector.screenshot({path:'/private/tmp/signoff-rtl-diagnostics-check/inspector.png'});
  }
  assert.deepEqual(writes,[]);
  const after=await (await context.request.get(`${base}/api/runs/${normal.run_id}/evidence`)).json();
  assert.deepEqual(after,before);
  await page.getByRole('listitem',{name:`런 #${remapped.run_id}`,exact:true}).getByRole('button',{name:'실행 근거 보기',exact:true}).click();
  const remapInspector=page.getByRole('region',{name:`런 #${remapped.run_id} 실행 근거`,exact:true}).getByRole('region',{name:'RTL 진단과 소스 탐색',exact:true});
  await remapInspector.getByText('`line 지시문으로 위치가 변경될 수 있음',{exact:true}).first().waitFor();
  for(const button of await remapInspector.getByRole('button',{name:/줄 보기$/}).all()) assert.ok(await button.isDisabled());
  assert.deepEqual(errors,[]);
  console.log('PASS: real container diagnostics, viewer jump/focus, source integrity failure/retry, line limits/navigation, escaped source, remap guard, immutable evidence, no writes and responsive layout');
} finally { await browser.close(); }
