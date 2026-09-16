import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE);
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(base, 'http://127.0.0.1:15174');
const code = `module helper(input logic a, output logic y); assign y=~a; endmodule
module chip_top(input logic a, output logic y); helper u_helper(.a(a),.y(y)); endmodule`;
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext();
  const login = await context.request.post(`${base}/api/auth/login`, { headers: { 'X-Signoff-Client': '1' }, data: { username: 'qa-editor', password: fixture.password } });
  assert.equal(login.status(), 200); const session = await login.json();
  const page = await context.newPage(); page.setDefaultTimeout(10000);
  await page.route('**/api/agents/review/**', route => route.fulfill({ json: { role: 'a1_rtl', triggered: false, available: null, a5: { role: 'a5_synth', triggered: false, available: null }, v: null } }));
  await page.goto(`${base}/analysis#rtl`);
  const top = page.getByRole('textbox', { name: '린트·합성 최상위 모듈 (선택)', exact: true });
  await top.fill('chip; exec');
  assert.ok(await page.getByRole('button', { name: '사인오프 래더 실행', exact: true }).isDisabled());
  await top.fill('chip_top');
  await page.getByRole('textbox', { name: 'SystemVerilog 소스', exact: true }).fill(code);
  await page.getByLabel('프로젝트에 기록 (선택)', { exact: true }).selectOption(String(fixture.project));
  assert.ok(await page.locator('a[href="/agents#a1_rtl"]').filter({ hasText: '자세히 보기' }).isVisible());
  let captured = '';
  await page.route('**/api/analysis/rtl-signoff/stream', async route => {
    assert.equal(route.request().postDataJSON().top_module, 'chip_top');
    const response = await route.fetch({ timeout: 90000 });
    captured = await response.text();
    await route.fulfill({ response, body: captured });
  });
  await page.getByRole('button', { name: '사인오프 래더 실행', exact: true }).click();
  await page.getByText(/모듈 chip_top/).waitFor({ timeout: 90000 });
  const rows = captured.trim().split('\n').map(line => JSON.parse(line));
  const result = rows.at(-1).result;
  assert.equal(result.module, 'chip_top'); assert.equal(result.top_module_requested, 'chip_top');
  assert.equal(result.verdict, 'CONDITIONAL');
  for (const kind of ['lint', 'width']) assert.deepEqual(result.tool_runs[kind].command.slice(-2), ['--top-module', 'chip_top']);
  assert.ok(result.tool_runs.synthesize.command.at(-1).includes('hierarchy -simcheck -top chip_top;'));
  assert.equal(result.execution.backend, 'container');
  const stored = await (await context.request.get(`${base}/api/runs/${result.run_id}/evidence`)).json();
  assert.equal(stored.result.top_module_requested, 'chip_top');
  const bad = await context.request.post(`${base}/api/analysis/rtl-signoff`, { headers: { 'X-CSRF-Token': session.csrf_token }, data: { code, top_module: 'absent' }, timeout: 90000 });
  assert.equal(bad.status(), 200); assert.equal((await bad.json()).verdict, 'REJECTED');
  await page.goto(`${base}/projects/${fixture.project}`);
  await page.getByRole('listitem', { name: `런 #${result.run_id}`, exact: true }).getByRole('button', { name: '실행 근거 보기', exact: true }).click();
  const panel = page.getByRole('region', { name: `런 #${result.run_id} 실행 근거`, exact: true });
  await panel.getByText('린트·합성 최상위: chip_top · 사용자 지정', { exact: true }).waitFor();
  await mkdir('/private/tmp/signoff-rtl-top-check', { recursive: true });
  for (const width of [320,390,1440]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (width===390) await panel.screenshot({ path: '/private/tmp/signoff-rtl-top-check/evidence.png' });
  }
  console.log('PASS: actual container explicit top via UI, invalid name blocked, primary/width/synthesis match, missing top rejected, saved selection and responsive evidence');
} finally { await browser.close(); }
