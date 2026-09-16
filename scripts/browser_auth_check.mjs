// Disposable local auth fixture only. See docs/authentication.md.
import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE ?? process.argv[2] ?? 'playwright');
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI ?? 'http://127.0.0.1:15173';
assert.equal(new URL(base).hostname, '127.0.0.1');
const output = '/private/tmp/signoff-auth-check';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
const page = await context.newPage();
page.setDefaultTimeout(10000);
const errors = [];
page.on('pageerror', e => errors.push(e.message));
async function login(username) {
  await page.getByRole('textbox', { name: '사용자 이름', exact: true }).fill(username);
  await page.getByLabel('비밀번호', { exact: true }).fill(fixture.password);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByText(`로그인: ${username}`, { exact: true }).waitFor();
}
async function api(path, method = 'GET', body) {
  const session = await context.request.get(`${base}/api/auth/session`);
  const csrf = (await session.json()).csrf_token;
  return context.request.fetch(`${base}/api${path}`, { method, headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' }, data: body });
}
async function logout() {
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await page.getByRole('heading', { name: 'Sign-off Hub 로그인' }).waitFor();
}
try {
  await page.goto(`${base}/projects/${fixture.project}/violations?selected=${fixture.violation}`);
  await page.getByRole('heading', { name: 'Sign-off Hub 로그인' }).waitFor();
  assert.equal((await context.request.get(`${base}/api/projects`)).status(), 401);
  await page.screenshot({ path: `${output}/login-desktop.png` });
  await login('qa-editor');
  await page.getByRole('button', { name: '수정 완료 처리', exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: '웨이버 검토', exact: true }).isEnabled(), false);
  await page.getByRole('button', { name: '수정 완료 처리', exact: true }).click();
  await page.getByText('처리 계정: qa-editor', { exact: true }).waitFor();
  assert.equal(await page.getByRole('textbox', { name: '처리자 이름 (직접 입력)', exact: true }).count(), 0);
  await page.getByRole('textbox', { name: '수정 근거 · 검증 결과', exact: true }).fill('private draft from editor');
  await logout();
  await login('qa-approver');
  assert.equal(await page.getByRole('textbox', { name: '수정 근거 · 검증 결과', exact: true }).count(), 0, 'Editor draft must be discarded');
  await page.getByRole('button', { name: '웨이버 검토', exact: true }).click();
  await page.getByRole('textbox', { name: '처리 사유', exact: true }).fill('QA approval by authenticated account');
  await page.getByRole('button', { name: '변경 저장', exact: true }).click();
  await page.getByText('qa-approver · QA approval by authenticated account', { exact: true }).waitFor();
  await page.getByRole('button', { name: '변경 이력', exact: true }).click();
  await page.getByText(/qa-approver \(로그인 계정\)/).waitFor();
  const history = await (await api(`/violations/${fixture.violation}/history`)).json();
  assert.equal(history.at(-1).actor_user_id, fixture.approver);
  await page.screenshot({ path: `${output}/account-review.png` });
  await logout();
  await login('qa-viewer');
  assert.equal(await page.getByRole('button', { name: '재오픈', exact: true }).isEnabled(), false);
  assert.equal((await api(`/projects/${fixture.hidden}`)).status(), 404);
  assert.equal((await api(`/violations/${fixture.violation}`, 'PATCH', { expected_status: 'waived', expected_version: 2, status: 'open', actor: 'qa-owner', reason: 'forged' })).status(), 403);
  const visible = await (await api('/projects')).json();
  assert.deepEqual(visible.map(p => p.id), [fixture.project]);
  await logout();
  await login('qa-owner');
  await page.goto(`${base}/projects/${fixture.project}/members`);
  await page.getByRole('heading', { name: '프로젝트 접근 권한' }).waitFor();
  await page.getByRole('textbox', { name: '계정 이름', exact: true }).fill('qa-editor');
  await page.getByRole('combobox', { name: '프로젝트 역할', exact: true }).selectOption('viewer');
  await page.getByRole('button', { name: '권한 저장', exact: true }).click();
  await page.getByText('qa-editor · 열람자', { exact: true }).waitFor();
  const audit = page.getByRole('region', { name: '권한 변경 이력', exact: true });
  await audit.getByText('qa-editor · 편집자 → 열람자', { exact: true }).waitFor();
  await audit.getByText(/qa-owner · 로그인 계정/).waitFor();
  const accessHistory = await (await api(`/projects/${fixture.project}/members/history`)).json();
  assert.equal(accessHistory.items[0].subject_username, 'qa-editor');
  assert.equal(accessHistory.items[0].actor, 'qa-owner');
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: `${output}/members-mobile.png`, fullPage: true });
  await page.getByRole('button', { name: '메뉴', exact: true }).click();
  await logout();
  await page.screenshot({ path: `${output}/login-mobile.png` });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ result: 'PASS', checks: ['login', 'viewer restrictions', 'direct ID isolation', 'account attribution', 'account switch clears drafts/cache', 'membership change and audit history', 'mobile', 'logout'], output }));
} catch (error) {
  console.error(await page.locator('body').ariaSnapshot());
  throw error;
} finally { await browser.close(); }
