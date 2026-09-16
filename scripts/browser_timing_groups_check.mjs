import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
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
  const session = await login('editor');
  const names = ['clk', 'clk_aux', 'CLK', '%_한글', ...Array.from({ length: 10 }, (_, i) => `z${i}`)];
  const checks = names.flatMap(path_group => ['min', 'max'].map(path_type => ({
    type: 'check', path_group, path_type, startpoint: 'a/Q', endpoint: 'b/D', slack: path_type === 'max' ? -10e-12 : 20e-12,
    source_path: [{ pin: 'a/Q' }, { pin: 'b/D' }],
  })));
  const created = await context.request.post(`${base}/api/projects/${fixture.project}/imports/opensta`, { headers: { 'X-CSRF-Token': session.csrf_token }, data: {
    import_id: randomUUID(), stage: 'placement', filename: 'groups.json', tool_version: 'synthetic QA', design_revision: 'groups', scenario: 'groups', source_text: JSON.stringify({ checks }),
  } });
  assert.equal(created.status(), 201); const run = await created.json();
  await login('viewer');
  const page = await context.newPage(); page.setDefaultTimeout(10000);
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  await page.goto(`${base}/runs/${run.id}/paths?q=absent&offset=25`);
  const groups = page.getByRole('region', { name: '보고서 경로 그룹', exact: true });
  await groups.getByRole('button', { name: 'clk max 그룹 보기', exact: true }).click();
  await page.getByRole('heading', { name: '검색 결과 1개 / 보고된 전체 28개', exact: true }).waitFor();
  assert.equal(new URL(page.url()).searchParams.get('path_group'), 'clk');
  assert.equal(new URL(page.url()).searchParams.has('q'), false);
  assert.equal(new URL(page.url()).searchParams.has('offset'), false);
  await page.reload();
  await page.getByRole('heading', { name: '검색 결과 1개 / 보고된 전체 28개', exact: true }).waitFor();
  await page.getByLabel('정확한 경로 그룹', { exact: true }).selectOption(JSON.stringify('clk_aux'));
  const listing = page.getByRole('region', { name: '타이밍 경로 목록', exact: true });
  await listing.getByRole('button', { name: /경로 #4 ·/ }).waitFor();
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', { name: '검색 결과 JSON 내보내기', exact: true }).click();
  const bundle = JSON.parse(await readFile(await (await downloaded).path(), 'utf8'));
  assert.equal(bundle.total, 1); assert.equal(bundle.filters.path_group, 'clk_aux');
  assert.equal(bundle.items[0].path_group, 'clk_aux');
  await page.getByLabel('정확한 경로 그룹', { exact: true }).selectOption(JSON.stringify('%_한글'));
  await listing.getByRole('button', { name: /경로 #8 ·/ }).waitFor();
  await groups.getByRole('button', { name: '다음 그룹', exact: true }).click();
  await groups.getByRole('button', { name: 'z1 max 그룹 보기', exact: true }).waitFor();
  assert.equal(await groups.getByRole('button', { name: 'clk max 그룹 보기', exact: true }).count(), 0);
  await page.getByRole('button', { name: '검색 초기화', exact: true }).click();
  await page.getByRole('heading', { name: '검색 결과 28개 / 보고된 전체 28개', exact: true }).waitFor();
  await mkdir('/private/tmp/signoff-timing-groups-check', { recursive: true });
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (width === 390) await groups.screenshot({ path: '/private/tmp/signoff-timing-groups-check/groups.png' });
  }
  assert.deepEqual(errors, []);
  console.log('PASS: exact group, min/max drilldown, search reset, URL reload, filtered export, literal Unicode, group pagination, viewer and responsive UI');
} finally { await browser.close(); }
