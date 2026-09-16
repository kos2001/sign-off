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
  const login = await context.request.post(`${base}/api/auth/login`, { headers: { 'X-Signoff-Client': '1' }, data: { username: 'qa-editor', password: fixture.password } });
  assert.equal(login.status(), 200);
  const source = await readFile(new URL('../backend/tests/fixtures/klayout-width.lyrdb', import.meta.url), 'utf8');
  const imported = await context.request.post(`${base}/api/projects/${fixture.project}/imports/klayout`, { headers: { 'X-CSRF-Token': (await login.json()).csrf_token }, data: {
    import_id: randomUUID(), stage: 'placement', filename: 'recovery.lyrdb', tool_version: 'fixture', design_revision: 'qa', scenario: 'recovery', source_text: source,
  } });
  assert.equal(imported.status(), 201); const run = await imported.json();
  const page = await context.newPage(); page.setDefaultTimeout(10000);
  const writes = [];
  page.on('request', request => { if (request.method() !== 'GET') writes.push(request.url()); });
  await page.goto(`${base}/unknown-page?private=do-not-display`);
  await page.getByRole('heading', { name: '페이지를 찾을 수 없습니다', exact: true }).waitFor();
  assert.equal(await page.locator('body').innerText().then(text => text.includes('do-not-display')), false);
  await page.getByRole('link', { name: '대시보드로 이동', exact: true }).click();
  await page.getByRole('main').getByRole('heading', { name: '프로젝트', exact: true }).waitFor();
  const markerRoute = `**/api/runs/${run.id}/markers?*`;
  await page.route(markerRoute, route => route.fulfill({ json: { secret: 'private-internal-value' } }), { times: 1 });
  await page.goto(`${base}/runs/${run.id}/markers`);
  await page.getByRole('heading', { name: '화면을 표시하지 못했습니다', exact: true }).waitFor();
  assert.equal(await page.getByRole('complementary').count(), 1, 'route failure preserves sidebar');
  assert.equal((await page.locator('body').innerText()).includes('private-internal-value'), false);
  await mkdir('/private/tmp/signoff-screen-recovery-check', { recursive: true });
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (width === 390) await page.screenshot({ path: '/private/tmp/signoff-screen-recovery-check/recovery.png', fullPage: true });
  }
  await page.getByRole('button', { name: '페이지 새로 고침', exact: true }).click();
  await page.getByRole('heading', { name: `DRC 마커 탐색 · 런 #${run.id}`, exact: true }).waitFor();
  // Unsaved review reasons live above the route boundary and survive its failure.
  await page.getByRole('button', { name: /^마커 #1 ·/ }).click();
  await page.getByRole('button', { name: '수정 완료 처리', exact: true }).click();
  await page.getByRole('textbox', { name: '수정 근거 · 검증 결과', exact: true }).fill('화면 오류 이후에도 보존할 검토 사유');
  await page.route(markerRoute, route => route.fulfill({ json: {} }), { times: 1 });
  await page.getByRole('textbox', { name: '마커 검색', exact: true }).fill('trigger-render-failure');
  await page.getByRole('button', { name: '검색', exact: true }).click();
  await page.getByRole('heading', { name: '화면을 표시하지 못했습니다', exact: true }).waitFor();
  await page.goBack();
  const draft = page.getByRole('textbox', { name: '수정 근거 · 검증 결과', exact: true });
  await draft.waitFor();
  assert.equal(await draft.inputValue(), '화면 오류 이후에도 보존할 검토 사유');
  // A new navigation must clear a route boundary without a full browser reload.
  await page.route(markerRoute, route => route.fulfill({ json: {} }), { times: 1 });
  await page.goto(`${base}/runs/${run.id}/markers`);
  await page.getByRole('heading', { name: '화면을 표시하지 못했습니다', exact: true }).waitFor();
  await page.getByRole('link', { name: '대시보드로 이동', exact: true }).click();
  await page.getByRole('main').getByRole('heading', { name: '프로젝트', exact: true }).waitFor();
  // Shell failures require the outer boundary, independent of router/auth providers.
  await page.route('**/api/projects', route => route.fulfill({ json: {} }), { times: 1 });
  await page.goto(`${base}/agents`);
  await page.getByRole('heading', { name: '화면을 표시하지 못했습니다', exact: true }).waitFor();
  assert.equal(await page.getByRole('complementary').count(), 0);
  await page.getByRole('link', { name: '대시보드로 이동', exact: true }).click();
  await page.getByRole('main').getByRole('heading', { name: '프로젝트', exact: true }).waitFor();
  assert.deepEqual(writes, [], 'recovery controls must not submit mutations');
  console.log('PASS: unknown route, isolated route failure, sanitized fallback, reload/navigation recovery, shell failure recovery, review draft preserved, no writes, responsive UI');
} finally { await browser.close(); }
