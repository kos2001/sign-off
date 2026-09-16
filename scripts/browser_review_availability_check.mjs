// Mock the review provider only; use a disposable authenticated project DB.
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE ?? process.argv[2] ?? 'playwright');
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(new URL(base).hostname, '127.0.0.1');
const browser = await chromium.launch({ headless: true });
const output = '/private/tmp/signoff-review-availability-check';
await mkdir(output, { recursive: true });
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  let mode = 'unavailable';
  const calls = [];
  const errors = [];
  page.on('pageerror', error => errors.push(error.name));
  await page.route('**/api/agents/review/gate', async route => {
    calls.push(route.request().postDataJSON());
    if (mode === 'http-error') return route.fulfill({ status: 503, json: { detail: 'private provider failure' } });
    await route.fulfill({ json: { a5: { role: 'a5_synth', role_name: '사인오프 종합 판정관', triggered: true, trigger: 'private endpoint /setup command', available: mode === 'success', review: mode === 'success' ? '새 근거를 검토한 참고 의견입니다.' : null, error: mode === 'success' ? null : 'private upstream URL and token', error_id: mode === 'success' ? undefined : 'a'.repeat(32) }, v: null } });
  });
  await page.goto(`${base}/projects/${fixture.project}`);
  await page.getByRole('textbox', { name: '사용자 이름', exact: true }).fill('qa-editor');
  await page.getByLabel('비밀번호', { exact: true }).fill(fixture.password);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  const unavailable = page.getByRole('region', { name: '검토 서비스 상태' });
  await unavailable.waitFor();
  assert.ok(!(await page.locator('body').innerText()).includes('private'));
  await page.screenshot({ path: `${output}/unavailable-mobile.png`, fullPage: true });
  mode = 'success';
  await page.getByRole('button', { name: '종합·검증 다시 시도', exact: true }).click();
  await page.getByText('새 근거를 검토한 참고 의견입니다.', { exact: true }).waitFor();
  const reviewedCalls = calls.length;
  // A focus event must not silently restart completed LLM reviews.
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  const session = await (await context.request.get(`${base}/api/auth/session`)).json();
  mode = 'http-error';
  const run = await context.request.post(`${base}/api/projects/${fixture.project}/runs`, { headers: { 'X-CSRF-Token': session.csrf_token }, data: { domain: 'sta', stage: 'placement', tool: 'QA new evidence' } });
  assert.equal(run.status(), 201);
  const created = await run.json();
  await unavailable.waitFor();
  assert.equal(await page.getByText('새 근거를 검토한 참고 의견입니다.', { exact: true }).count(), 0);
  assert.ok(calls.length > reviewedCalls);
  assert.ok(calls.at(-1).gate_status.domains.some(domain => domain.run_id === created.id));
  assert.ok(!(await page.locator('body').innerText()).includes('private provider'));
  mode = 'success';
  await page.getByRole('button', { name: '종합·검증 다시 시도', exact: true }).click();
  await page.getByText('새 근거를 검토한 참고 의견입니다.', { exact: true }).waitFor();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: `${output}/recovered-mobile.png`, fullPage: true });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ result: 'PASS', checks: ['unavailable is incomplete', 'no provider internals', 'retry recovery', 'new run invalidates old review', 'HTTP failure state', 'mobile'], output }));
} finally { await browser.close(); }
