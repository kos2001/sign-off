import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';

const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE ?? 'playwright');
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(new URL(base).hostname, '127.0.0.1');
const output = '/private/tmp/signoff-run-workspace-check';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
let page;
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 900 } });
  const login = await context.request.post(`${base}/api/auth/login`, { data: { username: 'qa-editor', password: fixture.password }, headers: { 'X-Signoff-Client': '1' } });
  assert.equal(login.status(), 200);
  const csrf = (await login.json()).csrf_token;
  const created = await context.request.post(`${base}/api/projects/${fixture.project}/runs`, { headers: { 'X-CSRF-Token': csrf }, data: { domain: 'sta', stage: 'placement', tool: 'OpenSTA', metrics: { wns_ps: -12.5, corner: 'ss_0p72v_125c' } } });
  assert.equal(created.status(), 201);
  const run = await created.json();
  const findings = Array.from({ length: 30 }, (_, index) => ({ check_name: index === 0 ? 'setup%_literal' : `setup_${index}`, severity: ['info', 'warning', 'error', 'critical'][index % 4], location: `u_core/reg_${index}`, description: `path ${index}` }));
  const added = await context.request.post(`${base}/api/runs/${run.id}/violations`, { headers: { 'X-CSRF-Token': csrf }, data: findings });
  assert.equal(added.status(), 201);

  page = await context.newPage();
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  let agentCalls = 0;
  await page.route('**/api/agents/review/gate', route => { agentCalls++; return route.fulfill({ json: { a5: { role: 'a5_synth', triggered: false, available: null }, v: null } }); });
  await page.goto(`${base}/projects/${fixture.project}`);
  const row = page.getByRole('listitem', { name: `런 #${run.id}`, exact: true });
  await row.getByRole('link', { name: '런 워크스페이스', exact: true }).click();
  await page.getByRole('heading', { name: `사인오프 런 #${run.id}`, exact: true }).waitFor();
  const callsAtWorkspace = agentCalls;
  assert.equal(new URL(page.url()).pathname, `/runs/${run.id}`);
  await page.getByText('-12.5', { exact: true }).waitFor();
  await page.getByText('ss_0p72v_125c', { exact: true }).waitFor();
  const summary = page.locator('[aria-label="런 위반 요약"]');
  for (const [label, value] of [['전체', '30'], ['미해결', '30'], ['수정 완료', '0'], ['웨이버', '0']]) {
    const card = summary.locator(':scope > div').filter({ has: page.getByText(label, { exact: true }) });
    assert.equal(await card.locator('dd').innerText(), value);
  }
  await page.getByRole('button', { name: '다음', exact: true }).click();
  await page.getByText('26–30 / 30', { exact: true }).waitFor();
  assert.equal(new URL(page.url()).searchParams.get('offset'), '25');
  await page.reload();
  await page.getByText('26–30 / 30', { exact: true }).waitFor();
  await page.getByLabel('체크·위치·설명 검색', { exact: true }).fill('%_');
  await page.getByRole('button', { name: '검색', exact: true }).click();
  await page.getByText('검색 결과 1 / 전체 30건', { exact: true }).waitFor();
  await page.getByText('setup%_literal', { exact: true }).waitFor();
  assert.equal(new URL(page.url()).searchParams.has('offset'), false);
  await page.getByRole('combobox', { name: '심각도', exact: true }).selectOption('critical');
  await page.getByText('조건에 맞는 위반이 없습니다.', { exact: true }).waitFor();
  await page.getByRole('button', { name: '초기화', exact: true }).click();
  await page.getByText('검색 결과 30 / 전체 30건', { exact: true }).waitFor();
  const statusResponse = page.waitForResponse(response => response.url().endsWith(`/api/runs/${run.id}`) && response.request().method() === 'PATCH');
  await page.getByRole('button', { name: 'Pass', exact: true }).click();
  assert.equal((await (await statusResponse).json()).status, 'passed');
  await page.getByRole('button', { name: '실행 근거 보기', exact: true }).click();
  await page.getByText('수동으로 등록한 런입니다.', { exact: false }).waitFor();
  assert.equal(agentCalls, callsAtWorkspace);
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `overflow at ${width}`);
  }
  await page.setViewportSize({ width: 390, height: 900 });
  await page.screenshot({ path: `${output}/workspace-mobile.png`, fullPage: true });

  const viewer = await browser.newContext();
  const viewerLogin = await viewer.request.post(`${base}/api/auth/login`, { data: { username: 'qa-viewer', password: fixture.password }, headers: { 'X-Signoff-Client': '1' } });
  assert.equal(viewerLogin.status(), 200);
  assert.equal((await viewer.request.get(`${base}/api/runs/${run.id}`)).status(), 200);
  assert.equal((await viewer.request.get(`${base}/api/runs/${run.id}/violations/page`)).status(), 200);
  await viewer.close();
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ result: 'PASS', checks: ['project deep link', 'run identity and metrics', 'summary', 'pagination and URL reload', 'literal search', 'combined filter empty state', 'manual status and evidence boundary', 'no AI call', 'viewer access', '320/390/1440 layout'], output }));
} catch (error) {
  console.error(page?.url(), await page?.locator('body').innerText());
  throw error;
} finally {
  await browser.close();
}
