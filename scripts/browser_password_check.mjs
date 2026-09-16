// Use a fresh disposable fixture from seed_auth_check.py. Never log credentials.
import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
import { randomBytes } from 'node:crypto';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE ?? process.argv[2] ?? 'playwright');
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(new URL(base).hostname, '127.0.0.1');
const replacement = randomBytes(24).toString('hex');
const browser = await chromium.launch({ headless: true });
const output = '/private/tmp/signoff-password-check';
await mkdir(output, { recursive: true });
const errors = [];
try {
  const current = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const other = await browser.newContext();
  const page = await current.newPage();
  const otherPage = await other.newPage();
  for (const p of [page, otherPage]) {
    p.setDefaultTimeout(10000);
    p.on('pageerror', error => errors.push(error.name));
    await p.goto(`${base}/account`);
    await p.getByRole('textbox', { name: '사용자 이름', exact: true }).fill('qa-editor');
    await p.getByLabel('비밀번호', { exact: true }).fill(fixture.password);
    await p.getByRole('button', { name: '로그인', exact: true }).click();
    await p.getByRole('heading', { name: '계정 설정', exact: true }).waitFor();
  }
  const submit = page.getByRole('button', { name: '비밀번호 변경', exact: true });
  const currentInput = page.getByLabel('현재 비밀번호', { exact: true });
  const newInput = page.getByLabel('새 비밀번호', { exact: true });
  const confirmInput = page.getByLabel('새 비밀번호 확인', { exact: true });
  await currentInput.fill(fixture.password);
  await newInput.fill(replacement);
  await confirmInput.fill(replacement + 'mismatch');
  await submit.click();
  await page.getByRole('alert').filter({ hasText: '새 비밀번호 확인이 일치하지 않습니다.' }).waitFor();
  await currentInput.fill('wrong-password');
  await confirmInput.fill(replacement);
  await submit.click();
  await page.getByRole('alert').filter({ hasText: '현재 비밀번호가 일치하지 않습니다.' }).waitFor();
  await currentInput.fill(fixture.password);
  await submit.click();
  await page.getByRole('status').filter({ hasText: '비밀번호를 변경했습니다.' }).waitFor();
  for (const input of [currentInput, newInput, confirmInput]) assert.equal(await input.inputValue(), '');
  assert.equal((await current.request.get(`${base}/api/projects`)).status(), 200);
  assert.equal((await other.request.get(`${base}/api/projects`)).status(), 401);
  await otherPage.reload();
  await otherPage.getByRole('heading', { name: 'Sign-off Hub 로그인' }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: `${output}/account-mobile.png`, fullPage: true });
  // Logout must use the newly rotated CSRF token held by AuthProvider.
  await page.getByRole('button', { name: '메뉴', exact: true }).click();
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await page.getByRole('heading', { name: 'Sign-off Hub 로그인' }).waitFor();
  await page.getByRole('textbox', { name: '사용자 이름', exact: true }).fill('qa-editor');
  await page.getByLabel('비밀번호', { exact: true }).fill(replacement);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('heading', { name: '계정 설정', exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ result: 'PASS', checks: ['mismatch', 'incorrect password', 'change', 'clear fields', 'revoke second browser', 'rotate CSRF', 'new password login', 'mobile'], output }));
} finally {
  await browser.close();
}
