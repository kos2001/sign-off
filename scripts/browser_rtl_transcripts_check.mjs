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
    const response = await context.request.post(`${base}/api/auth/login`, { headers: { 'X-Signoff-Client': '1' }, data: { username: `qa-${role}`, password: fixture.password } });
    assert.equal(response.status(), 200); return response.json();
  }
  const editor = await login('editor');
  const created = await context.request.post(`${base}/api/analysis/rtl-signoff`, { headers: { 'X-CSRF-Token': editor.csrf_token }, timeout: 90000, data: {
    project_id: fixture.project, design_revision: 'qa-transcripts', code: 'module pass_through(input logic a, output logic y); assign y = a; endmodule',
  } });
  assert.equal(created.status(), 200); const result = await created.json();
  assert.equal(result.execution.backend, 'container');
  assert.equal(result.verdict, 'CONDITIONAL'); // No testbench: never imply full pass.
  for (const name of ['lint', 'width', 'synthesize']) assert.equal(result.tool_runs[name].exit_code, 0);
  await login('viewer');
  const page = await context.newPage(); page.setDefaultTimeout(10000);
  await page.route('**/api/agents/review/gate', route => route.fulfill({ json: { a5: { role: 'a5_synth', triggered: false, available: null }, v: null } }));
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(`${base}/projects/${fixture.project}`);
  await page.getByRole('listitem', { name: `런 #${result.run_id}`, exact: true }).getByRole('button', { name: '실행 근거 보기', exact: true }).click();
  const evidence = page.getByRole('region', { name: `런 #${result.run_id} 실행 근거`, exact: true });
  const transcripts = evidence.getByRole('region', { name: 'RTL 도구 실행 로그', exact: true });
  await transcripts.getByText('합성 · 종료 코드 0', { exact: true }).click();
  assert.equal(await transcripts.getByLabel('합성 실행 로그', { exact: true }).innerText(), result.tool_runs.synthesize.log);
  await transcripts.getByText('폭 검사 린트 · 종료 코드 0', { exact: true }).click();
  assert.ok((await transcripts.innerText()).includes('design.sv'));
  const event = page.waitForEvent('download');
  await evidence.getByRole('button', { name: '근거 JSON 다운로드', exact: true }).click();
  const bundle = JSON.parse(await readFile(await (await event).path(), 'utf8'));
  assert.deepEqual(bundle.result.tool_runs, result.tool_runs);
  await mkdir('/private/tmp/signoff-rtl-transcripts-check', { recursive: true });
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (width === 390) await transcripts.screenshot({ path: '/private/tmp/signoff-rtl-transcripts-check/logs.png' });
  }
  assert.deepEqual(errors, []);
  console.log('PASS: actual container lint/width/synthesis, conditional without testbench, viewer log display, exact evidence export and responsive layout');
} finally { await browser.close(); }
