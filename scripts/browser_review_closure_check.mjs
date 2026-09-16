// Disposable auth fixture containing one overdue saved review; no provider calls.
import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE);
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(base, 'http://127.0.0.1:15174');
const output = '/private/tmp/signoff-review-closure-check';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  async function login(role) {
    const response = await context.request.post(`${base}/api/auth/login`, { headers: { 'X-Signoff-Client': '1' }, data: { username: `qa-${role}`, password: fixture.password } });
    assert.equal(response.status(), 200);
    await page.goto(`${base}/runs/${fixture.run}/paths`);
    await page.getByRole('button', { name: '실행 근거 보기', exact: true }).click();
    await page.getByRole('button', { name: new RegExp(`검토 #${fixture.review} ·`) }).click();
  }
  await login('editor');
  assert.equal(await page.getByRole('button', { name: '미완료 검토 종결', exact: true }).count(), 0);
  await login('owner');
  const detail = page.getByRole('region', { name: '저장된 검토 상세', exact: true });
  const submit = detail.getByRole('button', { name: '미완료 검토 종결', exact: true });
  assert.ok(await submit.isDisabled());
  const reason = detail.getByRole('textbox', { name: '미완료 종결 사유', exact: true });
  await reason.fill('서버 재시작 후 운영자가 확인한 미완료 요청');
  const endpoint = `**/runs/${fixture.run}/agent-reviews/${fixture.review}/close`;
  await page.route(endpoint, route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '일시 오류, 다시 시도하세요.' }) }), { times: 1 });
  await submit.click();
  await detail.getByRole('alert').waitFor();
  assert.equal(await reason.inputValue(), '서버 재시작 후 운영자가 확인한 미완료 요청');
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (width === 390) await detail.screenshot({ path: `${output}/closure-form.png` });
  }
  const responseEvent = page.waitForResponse(r => r.url().endsWith(`/agent-reviews/${fixture.review}/close`) && r.request().method() === 'POST');
  await submit.click();
  const response = await responseEvent;
  assert.equal(response.status(), 200);
  const record = await response.json();
  assert.equal(record.outcome.closure.actor, 'qa-owner');
  await detail.getByText(/운영자 미완료 종결 · qa-owner/).waitFor();
  await login('viewer');
  await detail.getByText(/운영자 미완료 종결 · qa-owner/).waitFor();
  assert.equal(await submit.count(), 0);
  const saved = await context.request.get(`${base}/api/runs/${fixture.run}/agent-reviews/${fixture.review}/export`);
  assert.deepEqual((await saved.json()).review, record);
  await page.setViewportSize({ width: 390, height: 844 });
  await detail.screenshot({ path: `${output}/closed-review.png` });
  assert.deepEqual(errors, []);
  console.log('PASS: owner closure, editor restriction, error/retry, viewer persistence, export, responsive layout');
} finally { await browser.close(); }
