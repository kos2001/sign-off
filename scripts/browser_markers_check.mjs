// Real isolated API; generated KLayout geometry plus synthetic paging/text fixtures.
import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE);
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(base, 'http://127.0.0.1:15174');
const output = '/private/tmp/signoff-markers-check';
await mkdir(output, { recursive: true });
let source = await readFile(new URL('../backend/tests/fixtures/klayout-width.lyrdb', import.meta.url), 'utf8');
const extra = Array.from({ length: 25 }, (_, i) => `<item><category>Notes</category><cell>TOP</cell><multiplicity>1</multiplicity><values><value>${i === 0 ? 'polygon: (0,0;4,0;4,4;0,4/1,1;3,1;3,3;1,3)' : "text: 'review marker'"}</value></values></item>`).join('');
source = source.replace('</items>', extra+'</items>').replace('<categories>', '<categories><category><name>Notes</name><description>UI fixture</description></category>');
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  async function login(role) {
    const r = await context.request.post(`${base}/api/auth/login`, { headers: { 'X-Signoff-Client': '1' }, data: { username: `qa-${role}`, password: fixture.password } });
    assert.equal(r.status(), 200); return r.json();
  }
  const session = await login('editor');
  const r = await context.request.post(`${base}/api/projects/${fixture.project}/imports/klayout`, { headers: { 'X-CSRF-Token': session.csrf_token }, data: { import_id: randomUUID(), stage: 'placement', filename: 'markers.lyrdb', tool_version: '0.30.12 + UI fixture', design_revision: 'qa', scenario: 'marker browser fixture', source_text: source } });
  assert.equal(r.status(), 201);
  const run = await r.json();
  await login('viewer');
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(`${base}/runs/${run.id}/markers`);
  await page.getByText('검색 결과 27 / 보고된 마커 27개', { exact: false }).waitFor();
  await page.getByRole('button', { name: '다음 마커', exact: true }).click();
  await page.getByRole('button', { name: /마커 #26 ·/ }).waitFor();
  assert.equal(await page.getByRole('button', { name: /마커 #1 ·/ }).count(), 0);
  await page.getByRole('button', { name: /마커 #26 ·/ }).click();
  const detail = page.getByRole('region', { name: 'DRC 마커 상세', exact: true });
  await detail.getByText('표시 가능한 기하 값이 없습니다.', { exact: false }).waitFor();
  assert.equal(await detail.getByRole('img').count(), 0);
  await page.getByRole('textbox', { name: '마커 검색', exact: true }).fill('absent');
  await page.getByRole('button', { name: '검색', exact: true }).click();
  await page.getByText('조건에 맞는 마커가 없습니다.', { exact: false }).waitFor();
  await page.goto(`${base}/runs/${run.id}/markers?selected=1`);
  await detail.getByRole('img', { name: '마커 #1 셀 좌표 미리보기', exact: true }).waitFor();
  assert.equal(await detail.locator('svg path').getAttribute('d'), 'M 10 190 L 10 10 M 190 10 L 190 190');
  await page.reload();
  await detail.getByRole('img').waitFor();
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (width === 390) await detail.screenshot({ path: `${output}/edge-pair.png` });
  }
  await page.goto(`${base}/runs/${run.id}/markers?selected=3`);
  await detail.getByRole('img').waitFor();
  assert.equal(await detail.locator('svg path').getAttribute('fill-rule'), 'evenodd');
  assert.equal(((await detail.locator('svg path').getAttribute('d')).match(/ Z/g) ?? []).length, 2);
  await detail.screenshot({ path: `${output}/polygon-holes.png` });
  await page.getByLabel('규칙 분류', { exact: true }).selectOption(JSON.stringify('Notes'));
  await page.getByText('검색 결과 25 / 보고된 마커 27개', { exact: false }).waitFor();
  assert.equal(new URL(page.url()).searchParams.has('selected'), false);
  assert.deepEqual(errors, []);
  console.log('PASS: viewer browsing, paging/search/category, no-geometry fallback, exact edge-pair plot, polygon holes, shared selection, responsive layout');
} finally { await browser.close(); }
