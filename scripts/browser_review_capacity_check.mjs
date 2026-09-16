// Real isolated API with its single review slot held; no LLM calls or response mocks.
import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE);
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(base, 'http://127.0.0.1:15174');
const output = '/private/tmp/signoff-review-capacity-check';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const login = await context.request.post(`${base}/api/auth/login`, { headers: { 'X-Signoff-Client': '1' }, data: { username: 'qa-editor', password: fixture.password } });
  assert.equal(login.status(), 200);
  const session = await login.json();
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(`${base}/projects/${fixture.project}`);
  await page.getByText('검토 처리 한도 도달', { exact: false }).waitFor();
  await page.getByText('동시 AI 검토 처리 한도에 도달해', { exact: false }).waitFor();
  await page.getByText('선행 검토 미완료 · A5 의견이 없어 V는 실행되지 않았습니다.', { exact: true }).waitFor();
  await page.screenshot({ path: `${output}/automatic-capacity.png`, fullPage: true });
  const response = await context.request.post(`${base}/api/projects/${fixture.project}/imports/opensta`, { headers: { 'X-CSRF-Token': session.csrf_token }, data: { import_id: randomUUID(), stage: 'placement', filename: 'capacity.json', tool_version: 'QA', design_revision: 'qa', scenario: 'test', source_text: '{"checks": []}' } });
  assert.equal(response.status(), 201);
  const run = await response.json();
  await page.goto(`${base}/runs/${run.id}/paths`);
  await page.getByRole('button', { name: '실행 근거 보기', exact: true }).click();
  await page.getByRole('button', { name: 'AI 검토 요청 · 기록 저장', exact: true }).click();
  const detail = page.getByRole('region', { name: '저장된 검토 상세', exact: true });
  await detail.getByText('동시 AI 검토 처리 한도로 모델 호출을 시작하지 못했습니다.', { exact: false }).waitFor();
  await page.reload();
  await page.getByRole('button', { name: '실행 근거 보기', exact: true }).click();
  await page.getByRole('button', { name: /검토 #\d+ · 검토 실패/ }).click();
  await detail.getByText('동시 AI 검토 처리 한도로 모델 호출을 시작하지 못했습니다.', { exact: false }).waitFor();
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (width === 390) await detail.screenshot({ path: `${output}/saved-capacity.png` });
  }
  assert.deepEqual(errors, []);
  console.log('PASS: actual capacity denial, A5/V semantics, saved failure persists, 320/390/1440 layout');
} finally { await browser.close(); }
