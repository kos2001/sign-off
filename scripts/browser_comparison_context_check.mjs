// Use only a disposable seed_auth_check.py fixture.
import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE ?? process.argv[2] ?? 'playwright');
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(new URL(base).hostname, '127.0.0.1');
const output = '/private/tmp/signoff-comparison-context-check';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const login = await context.request.post(`${base}/api/auth/login`, { headers: { 'X-Signoff-Client': '1' }, data: { username: 'qa-editor', password: fixture.password } });
  assert.equal(login.status(), 200);
  const headers = { 'X-CSRF-Token': (await login.json()).csrf_token };
  const source_text = JSON.stringify({ checks: [{ type: 'check', path_type: 'max', path_group: 'clk', startpoint: 'a/Q', endpoint: 'b/D', source_path: [{ pin: 'a/Q' }, { pin: 'b/D' }], slack: -2e-11 }] });
  const ids = [];
  for (const scenario of ['slow', 'fast']) {
    const response = await context.request.post(`${base}/api/projects/${fixture.project}/imports/opensta`, { headers, data: {
      import_id: randomUUID(), stage: 'placement', filename: `${scenario}.json`, tool_version: `QA ${scenario}`, design_revision: `rev-${scenario}`, scenario, source_text,
    } });
    assert.equal(response.status(), 201);
    ids.push((await response.json()).id);
  }
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`${base}/projects/${fixture.project}/compare?baseline=${ids[0]}&candidate=${ids[1]}`);
  const conditions = page.getByRole('region', { name: '분석 조건 비교', exact: true });
  const scenario = conditions.getByRole('group', { name: '시나리오', exact: true });
  await scenario.getByText('서로 다름', { exact: true }).waitFor();
  assert.deepEqual(await scenario.locator('p').allTextContents(), ['기준', 'slow', '비교 대상', 'fast']);
  await conditions.getByRole('group', { name: '원본 SHA-256', exact: true }).getByText('동일 기록', { exact: true }).waitFor();
  await conditions.getByRole('group', { name: '검증 범위', exact: true }).getByText('동일 기록', { exact: true }).waitFor();
  await page.getByRole('button', { name: '실행 근거 보기', exact: true }).first().click();
  const evidence = page.getByRole('region', { name: `런 #${ids[0]} 실행 근거`, exact: true });
  await evidence.getByText('OpenSTA 보고서 · slow.json', { exact: true }).waitFor();
  await evidence.getByText('원본 보고서', { exact: true }).click();
  assert.equal(await evidence.getByLabel('OpenSTA 원본 보고서', { exact: true }).textContent(), source_text);
  await page.getByRole('button', { name: '기준과 대상 바꾸기', exact: true }).click();
  await page.waitForURL(url => url.searchParams.get('baseline') === String(ids[1]));
  await scenario.locator('p').nth(1).filter({ hasText: /^fast$/ }).waitFor();
  assert.deepEqual(await scenario.locator('p').allTextContents(), ['기준', 'fast', '비교 대상', 'slow']);
  await page.reload();
  await scenario.getByText('서로 다름', { exact: true }).waitFor();
  assert.deepEqual(await scenario.locator('p').allTextContents(), ['기준', 'fast', '비교 대상', 'slow']);
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  }
  await page.setViewportSize({ width: 390, height: 1000 });
  await conditions.screenshot({ path: `${output}/conditions-mobile.png` });
  const manual = await context.request.post(`${base}/api/projects/${fixture.project}/runs`, { headers, data: { domain: 'sta', stage: 'placement', tool: 'QA manual' } });
  assert.equal(manual.status(), 201);
  await page.goto(`${base}/projects/${fixture.project}/compare?baseline=${(await manual.json()).id}&candidate=${ids[1]}`);
  await scenario.getByText('정보 부족', { exact: true }).waitFor();
  await scenario.getByText('미등록', { exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ result: 'PASS', checks: ['submitted context differences', 'same source hash', 'source evidence', 'swap and reload', 'missing context', '320/390/1440 widths'], output }));
} finally { await browser.close(); }
