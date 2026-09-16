// Only run with the disposable authentication fixture and test UI server.
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE ?? 'playwright');
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(new URL(base).hostname, '127.0.0.1');
assert.equal(new URL(base).port, '15174');
const output = '/private/tmp/signoff-violation-export-check';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  async function login(role) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const response = await context.request.post(`${base}/api/auth/login`, {
      headers: { 'X-Signoff-Client': '1' }, data: { username: `qa-${role}`, password: fixture.password },
    });
    assert.equal(response.status(), 200);
    return { context, headers: { 'X-CSRF-Token': (await response.json()).csrf_token } };
  }
  const editor = await login('editor');
  const previous = await editor.context.request.get(`${base}/api/projects/${fixture.project}/violations?stage=placement&latest_only=false`);
  assert.equal(previous.status(), 200);
  const historicalTotal = (await previous.json()).total + 31;
  async function post(path, data, account = editor) {
    const response = await account.context.request.post(`${base}/api${path}`, { headers: account.headers, data });
    assert.ok(response.ok(), await response.text());
    return response.json();
  }
  const old = await post(`/projects/${fixture.project}/runs`, { domain: 'sta', stage: 'placement', tool: 'Export QA old' });
  await post(`/runs/${old.id}/violations`, [{ check_name: 'historical', severity: 'error' }]);
  const run = await post(`/projects/${fixture.project}/runs`, { domain: 'sta', stage: 'placement', tool: 'Export QA' });
  const violations = await post(`/runs/${run.id}/violations`, Array.from({ length: 30 }, (_, i) => ({
    check_name: `Export issue ${i}`, severity: 'error', location: `u_core/${i}`, description: 'Synthetic review evidence',
  })));
  const approver = await login('approver');
  await post(`/violations/${violations[0].id}/waiver`, { expected_version: 1, approved_by: 'QA', reason: 'Export exception' }, approver);
  for (const [version, before, after, account] of [
    [2, 'waived', 'open', approver], [3, 'open', 'fixed', editor],
    [4, 'fixed', 'open', editor], [5, 'open', 'waived', approver],
  ]) {
    const result = await account.context.request.patch(`${base}/api/violations/${violations[0].id}`, {
      headers: account.headers, data: { expected_version: version, expected_status: before,
        status: after, actor: 'ignored', reason: 'Export exception' },
    });
    assert.equal(result.status(), 200);
  }
  async function pageTransition(version, reason) {
    const result = await editor.context.request.patch(`${base}/api/violations/${violations[1].id}`, {
      headers: editor.headers, data: { expected_version: version,
        expected_status: version % 2 ? 'open' : 'fixed', status: version % 2 ? 'fixed' : 'open',
        actor: 'ignored', reason },
    });
    assert.equal(result.status(), 200);
  }
  for (let version = 1; version <= 30; version++) await pageTransition(version, `Pagination event ${version}`);
  const { context } = await login('viewer');
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.setDefaultTimeout(10000);
  await page.goto(`${base}/projects/${fixture.project}/violations?stage=placement`);
  const button = page.getByRole('button', { name: '검색 결과 JSON 내보내기', exact: true });
  await button.waitFor();
  await page.goto(`${base}/projects/${fixture.project}/violations?stage=placement&offset=25&selected=${violations[0].id}`);
  await page.getByRole('button', { name: '변경 이력', exact: true }).click();
  const historyButton = page.getByRole('button', { name: '변경 이력 JSON 내보내기', exact: true });
  async function historyDownload() {
    const response = page.waitForResponse(r => r.url().endsWith('/history/export') && r.status() === 200);
    const event = page.waitForEvent('download');
    await historyButton.click();
    const file = await event;
    assert.equal(file.suggestedFilename(), `violation-${violations[0].id}-history.json`);
    const bytes = await readFile(await file.path());
    assert.deepEqual(bytes, await (await response).body());
    return JSON.parse(bytes.toString('utf8'));
  }
  const history = await historyDownload();
  assert.equal(history.total, 5);
  assert.equal(history.violation.version, 6);
  assert.equal(history.violation.status, 'waived');
  assert.deepEqual(history.events.map(e => e.to_status), ['waived', 'open', 'fixed', 'open', 'waived']);
  assert.equal(history.events[0].actor, 'qa-approver');
  assert.equal(history.events[2].actor, 'qa-editor');
  await page.route('**/api/violations/*/history/export', route => route.fulfill({ status: 503, json: { detail: 'temporary' } }), { times: 1 });
  await historyButton.click();
  await page.getByRole('alert').filter({ hasText: '이력을 내보내지 못했습니다' }).waitFor();
  assert.equal((await historyDownload()).total, 5);
  await historyButton.locator('..').screenshot({ path: `${output}/history-export-mobile.png` });
  await page.goto(`${base}/projects/${fixture.project}/violations?stage=placement&offset=25&selected=${violations[1].id}`);
  await page.getByRole('button', { name: '변경 이력', exact: true }).click();
  const historyRegion = page.locator('[aria-label="변경 이력"]');
  await historyRegion.getByText('조회한 이력 25 / 30건', { exact: true }).waitFor();
  assert.equal(await historyRegion.locator('ol > li').count(), 25);
  assert.ok((await historyRegion.locator('ol > li').first().innerText()).includes('Pagination event 30'));
  await pageTransition(31, 'Pagination appended 31');
  await pageTransition(32, 'Pagination appended 32');
  await page.route('**/api/violations/*/history/page?before_id=*', route => route.fulfill({ status: 503, json: { detail: 'temporary' } }), { times: 2 });
  await page.getByRole('button', { name: '이전 변경 더 보기', exact: true }).click();
  await historyRegion.getByRole('alert').filter({ hasText: '이력을 불러오지 못했습니다' }).waitFor();
  assert.equal(await historyRegion.locator('ol > li').count(), 25);
  await page.getByRole('button', { name: '이전 변경 더 보기', exact: true }).click();
  await historyRegion.getByText('조회한 이력 30 / 30건', { exact: true }).waitFor();
  assert.equal(await historyRegion.getByText('Pagination appended 31', { exact: true }).count(), 0);
  await page.getByRole('button', { name: '이력 새로고침', exact: true }).click();
  await historyRegion.getByText('조회한 이력 32 / 32건', { exact: true }).waitFor();
  assert.equal(await historyRegion.locator('ol > li').count(), 32);
  assert.ok((await historyRegion.locator('ol > li').first().innerText()).includes('Pagination appended 32'));
  await historyRegion.screenshot({ path: `${output}/history-pages-mobile.png` });
  await page.goto(`${base}/projects/${fixture.project}/violations?stage=placement`);
  async function download() {
    const responseEvent = page.waitForResponse(response => response.url().includes('/violations/export?') && response.status() === 200);
    const event = page.waitForEvent('download');
    await button.click();
    const file = await event;
    assert.equal(file.suggestedFilename(), `project-${fixture.project}-violations.json`);
    const bytes = await readFile(await file.path());
    assert.deepEqual(bytes, await (await responseEvent).body());
    return JSON.parse(bytes.toString('utf8'));
  }
  let bundle = await download();
  assert.equal(bundle.total, 30);
  assert.equal(bundle.items.length, 30);
  assert.equal(bundle.open_blocking, 29);
  const waived = bundle.items.find(item => item.id === violations[0].id);
  assert.equal(waived.waiver.reason, 'Export exception');
  assert.equal(waived.waiver.approved_by, 'qa-approver');
  await page.getByRole('button', { name: '다음', exact: true }).click();
  await page.waitForURL(/offset=25/);
  const search = page.getByRole('textbox', { name: '체크 이름 · 위치 · 설명 · 툴 검색', exact: true });
  await search.fill('not-yet-applied');
  bundle = await download();
  assert.equal(bundle.total, 30);
  assert.equal(bundle.filters.q, '');
  assert.equal(bundle.filters.offset, undefined);
  await page.getByRole('combobox', { name: '실행 범위', exact: true }).selectOption('false');
  await page.waitForURL(/latest_only=false/);
  bundle = await download();
  assert.equal(bundle.total, historicalTotal);
  let downloads = 0;
  page.on('download', () => downloads++);
  await page.route('**/api/projects/*/violations/export?*', route => route.fulfill({ status: 503, json: { detail: 'temporary' } }), { times: 1 });
  await button.click();
  await page.getByRole('alert').filter({ hasText: '내보내지 못했습니다' }).waitFor();
  assert.equal(downloads, 0);
  assert.equal((await download()).total, historicalTotal);
  await page.getByRole('region', { name: '위반 내보내기', exact: true }).screenshot({ path: `${output}/export-mobile.png` });
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  }
  // Exceed the actual production byte cap, not a reduced test constant.
  await post(`/runs/${run.id}/violations`, [{ check_name: 'oversized-export', severity: 'error', description: '한'.repeat(3000000) }]);
  const beforeOversized = downloads;
  const rejected = page.waitForResponse(response => response.url().includes('/violations/export?') && response.status() === 413);
  await button.click();
  await rejected;
  await page.getByRole('alert').filter({ hasText: 'exceeds 8 MiB' }).waitFor();
  assert.equal(downloads, beforeOversized);
  await search.fill('no-such-issue');
  await page.getByRole('button', { name: '검색', exact: true }).click();
  await page.getByText('조건에 맞는 위반이 없습니다. 검색 조건이나 실행 범위를 변경해 보세요.', { exact: true }).waitFor();
  bundle = await download();
  assert.deepEqual(bundle.items, []);
  assert.equal(bundle.total, 0);
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ result: 'PASS', checks: ['viewer download', 'all pages', 'applied filters only',
    'latest and historical scope', 'waiver context', 'failure and retry', 'actual 8 MiB cap without partial file',
    'response bytes preserved', 'history with revoked waiver and actor IDs', 'history retry',
    'history pagination retains rows on failure', 'history snapshot excludes new events until refresh',
    'empty result', '320/390/1440 widths'], output }));
} finally {
  await browser.close();
}
