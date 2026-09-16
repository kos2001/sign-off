// Uses a fresh disposable authenticated DB; never run against user accounts.
import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE ?? process.argv[2] ?? 'playwright');
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(new URL(base).hostname, '127.0.0.1');
const output = '/private/tmp/signoff-sessions-check';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const remote = await browser.newContext();
  const unrelated = await browser.newContext();
  for (const [client, username] of [[remote, 'qa-editor'], [unrelated, 'qa-viewer']]) {
    const response = await client.request.post(`${base}/api/auth/login`, { headers: { 'X-Signoff-Client': '1' }, data: { username, password: fixture.password } });
    assert.equal(response.status(), 200);
  }
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.name));
  await page.goto(`${base}/account`);
  await page.getByRole('textbox', { name: '사용자 이름', exact: true }).fill('qa-editor');
  await page.getByLabel('비밀번호', { exact: true }).fill(fixture.password);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  const panel = page.getByRole('region', { name: '로그인 세션', exact: true });
  await panel.getByText('활성 세션 2개', { exact: true }).waitFor();
  await panel.getByText('현재 세션', { exact: true }).waitFor();
  const history = page.getByRole('region', { name: '계정 보안 이력', exact: true });
  await history.getByRole('listitem').first().getByText('로그인', { exact: true }).waitFor();
  assert.equal(await history.getByRole('listitem').count(), 2);
  const before = await (await context.request.get(`${base}/api/auth/session`)).json();
  await page.route('**/api/auth/sessions/revoke-others', route => route.fulfill({ status: 503, json: { detail: 'temporary' } }), { times: 1 });
  const button = panel.getByRole('button', { name: '다른 세션 모두 종료', exact: true });
  await button.click();
  await panel.getByRole('alert').filter({ hasText: '세션을 종료하지 못했습니다' }).waitFor();
  assert.ok((await (await remote.request.get(`${base}/api/auth/session`)).json()).user);
  await button.click();
  await panel.getByRole('status').getByText('다른 활성 세션 1개를 종료했습니다.', { exact: true }).waitFor();
  await panel.getByText('활성 세션 1개', { exact: true }).waitFor();
  await history.getByRole('listitem').first().getByText('다른 세션 종료', { exact: true }).waitFor();
  await history.getByRole('listitem').first().getByText('종료한 세션 기록: 1개', { exact: true }).waitFor();
  assert.equal(await history.getByRole('listitem').count(), 3);
  assert.equal(await button.isEnabled(), false);
  const after = await (await context.request.get(`${base}/api/auth/session`)).json();
  assert.equal(after.user.id, before.user.id);
  assert.equal(after.csrf_token, before.csrf_token);
  assert.equal((await (await remote.request.get(`${base}/api/auth/session`)).json()).user, null);
  assert.ok((await (await unrelated.request.get(`${base}/api/auth/session`)).json()).user);
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  }
  await page.setViewportSize({ width: 320, height: 900 });
  await panel.screenshot({ path: `${output}/sessions-mobile.png` });
  await history.screenshot({ path: `${output}/security-history-mobile.png` });
  await page.reload();
  await panel.getByText('활성 세션 1개', { exact: true }).waitFor();
  await history.getByRole('listitem').first().getByText('다른 세션 종료', { exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ result: 'PASS', checks: ['self-scoped active sessions', 'current session label', 'failure and retry', 'other session revoked', 'current and unrelated accounts preserved', 'security history login and revoke', 'no success event on failure', 'history refresh and reload', '320/390/1440 width'], output }));
} finally { await browser.close(); }
