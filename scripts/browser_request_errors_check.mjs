// Read-only UI verification with mocked API failures. No project mutations.
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE ?? process.argv[2] ?? 'playwright');
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(new URL(base).hostname, '127.0.0.1');
const output = '/private/tmp/signoff-request-errors-check';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  page.setDefaultTimeout(10000);
  const requestId = 'b'.repeat(32);
  let fail = true;
  await page.route('**/api/auth/session', route => fail ? route.fulfill({ status: 500, headers: { 'X-Request-ID': requestId }, json: { detail: 'private database secret' } }) : route.fulfill({ json: { mode: 'local', user: null, csrf_token: null, memberships: {} } }));
  await page.route('**/api/projects', route => route.fulfill({ json: [] }));
  await page.goto(`${base}/`);
  await page.getByRole('alert').filter({ hasText: requestId }).waitFor();
  assert.ok(!(await page.locator('body').innerText()).includes('private database'));
  await page.screenshot({ path: `${output}/connection-error-mobile.png` });
  fail = false;
  await page.getByRole('button', { name: '다시 시도', exact: true }).click();
  await page.getByRole('heading', { name: 'Sign-off Hub', exact: true }).waitFor();
  assert.equal(await page.getByRole('alert').count(), 0);
  await page.route('**/api/analysis/rtl-signoff/stream', route => route.fulfill({ status: 500, headers: { 'X-Request-ID': requestId }, json: { detail: 'private compiler credentials' } }));
  await page.goto(`${base}/analysis#rtl-signoff`);
  const ladder = page.locator('#rtl-signoff');
  const source = await ladder.getByRole('textbox', { name: 'SystemVerilog 소스', exact: true }).inputValue();
  await ladder.getByRole('button', { name: '사인오프 래더 실행', exact: true }).click();
  await ladder.getByText(`서버가 요청을 처리하지 못했습니다. 문의 번호: ${requestId}`, { exact: true }).waitFor();
  assert.equal(await ladder.getByRole('textbox', { name: 'SystemVerilog 소스', exact: true }).inputValue(), source);
  assert.ok(!(await page.locator('body').innerText()).includes('private compiler'));
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await ladder.screenshot({ path: `${output}/analysis-error-mobile.png` });
  await page.unroute('**/api/analysis/rtl-signoff/stream');
  await page.route('**/api/analysis/rtl-signoff/stream', route => route.fulfill({ status: 422, json: { detail: [
    { loc: ['body', 'testbench_top'], msg: 'Invalid module name', input: 'do-not-echo-input' },
    { loc: ['body', 'code'], msg: 'Source is required' },
  ] } }));
  await ladder.getByRole('button', { name: '사인오프 래더 실행', exact: true }).click();
  await ladder.getByText('testbench_top: Invalid module name · code: Source is required', { exact: true }).waitFor();
  assert.ok(!(await page.locator('body').innerText()).includes('do-not-echo-input'));
  assert.equal(await ladder.getByRole('textbox', { name: 'SystemVerilog 소스', exact: true }).inputValue(), source);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  console.log(JSON.stringify({ result: 'PASS', checks: ['request reference', 'safe server error', 'connection retry', 'stream failure', 'retained input', 'field validation errors', 'mobile'], output }));
} finally { await browser.close(); }
