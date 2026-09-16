// Uses a disposable DB and real Hermes calls. Requires a running review provider.
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE);
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(new URL(base).hostname, '127.0.0.1');
assert.equal(new URL(base).port, '15174');
const output = '/private/tmp/signoff-saved-reviews-check';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  async function login(role) {
    const r = await context.request.post(`${base}/api/auth/login`, { headers: { 'X-Signoff-Client': '1' }, data: { username: `qa-${role}`, password: fixture.password } });
    assert.equal(r.status(), 200);
    return (await context.request.get(`${base}/api/auth/session`)).json();
  }
  const session = await login('editor');
  const created = await context.request.post(`${base}/api/projects/${fixture.project}/imports/opensta`, { headers: { 'X-CSRF-Token': session.csrf_token }, data: { import_id: randomUUID(), stage: 'placement', filename: 'review.json', tool_version: 'QA', design_revision: 'saved-review', scenario: 'test', source_text: '{"checks": []}' } });
  assert.equal(created.status(), 201);
  const run = await created.json();
  const page = await context.newPage();
  page.setDefaultTimeout(12000);
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(`${base}/runs/${run.id}/paths`);
  await page.getByRole('button', { name: '실행 근거 보기', exact: true }).click();
  const panel = page.getByRole('region', { name: `런 #${run.id} 저장된 AI 검토`, exact: true });
  await panel.getByText('아직 저장된 AI 검토가 없습니다.', { exact: true }).waitFor();
  const resultEvent = page.waitForResponse(r => r.url().endsWith(`/runs/${run.id}/agent-reviews`) && r.request().method() === 'POST', { timeout: 60000 });
  await panel.getByRole('button', { name: 'AI 검토 요청 · 기록 저장', exact: true }).click();
  const response = await resultEvent;
  assert.equal(response.status(), 201);
  const review = await response.json();
  assert.equal(review.status, 'completed');
  assert.equal(review.requester, 'qa-editor');
  assert.equal(review.input_snapshot.run_id, run.id);
  const detail = panel.getByRole('region', { name: '저장된 검토 상세' });
  await detail.getByRole('heading', { name: `검토 #${review.id} · 검토 완료`, exact: true }).waitFor();
  assert.ok((await detail.innerText()).includes(review.outcome.review));
  await page.reload();
  await page.getByRole('button', { name: '실행 근거 보기', exact: true }).click();
  await panel.getByRole('button', { name: new RegExp(`검토 #${review.id} · 검토 완료`) }).click();
  await detail.getByText('실제 전달한 근거와 검토 지침', { exact: true }).click();
  assert.ok((await detail.innerText()).includes(review.input_snapshot.source_sha256));
  const again = await context.request.post(`${base}/api/runs/${run.id}/agent-reviews`, { headers: { 'X-CSRF-Token': session.csrf_token }, data: { request_key: review.request_key } });
  assert.equal(again.status(), 200);
  assert.deepEqual(await again.json(), review);
  await login('viewer');
  await page.reload();
  await page.getByRole('button', { name: '실행 근거 보기', exact: true }).click();
  await panel.getByRole('button', { name: new RegExp(`검토 #${review.id} · 검토 완료`) }).click();
  assert.equal(await panel.getByRole('button', { name: 'AI 검토 요청 · 기록 저장', exact: true }).count(), 0);
  await detail.getByRole('heading', { name: `검토 #${review.id} · 검토 완료`, exact: true }).waitFor();
  for (const width of [390, 320, 1440]) {
    await page.setViewportSize({ width, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (width === 390) await panel.screenshot({ path: `${output}/saved-review-mobile.png` });
  }
  let downloads = 0;
  page.on('download', () => downloads++);
  const exportUrl = `/runs/${run.id}/agent-reviews/${review.id}/export`;
  let capturedExport;
  await page.route(`**/api${exportUrl}`, async route => {
    const upstream = await route.fetch();
    capturedExport = await upstream.body();
    await route.fulfill({ response: upstream });
  });
  const exportButton = detail.getByRole('button', { name: '검토·근거 JSON 다운로드', exact: true });
  async function exportReview() {
    capturedExport = null;
    const responseEvent = page.waitForResponse(r => r.url().endsWith(exportUrl));
    const downloadEvent = page.waitForEvent('download');
    await exportButton.click();
    const [response, file] = await Promise.all([responseEvent, downloadEvent]);
    assert.equal(response.status(), 200);
    const bytes = await readFile(await file.path());
    assert.ok(capturedExport && bytes.equals(capturedExport), 'download must match upstream bytes');
    assert.equal(file.suggestedFilename(), `run-${run.id}-review-${review.id}.json`);
    const bundle = JSON.parse(bytes.toString('utf8'));
    assert.equal(bundle.format, 'signoff/run-agent-review-export/v1');
    assert.deepEqual(bundle.review, review);
    await detail.getByRole('status').filter({ hasText: '검토 파일 다운로드를 시작했습니다.' }).waitFor();
  }
  await exportReview();
  await page.route(`**/api${exportUrl}`, route => route.fulfill({ status: 503, json: { detail: 'private provider failure' } }), { times: 1 });
  const downloadsBeforeFailure = downloads;
  await exportButton.click();
  await detail.getByRole('alert').waitFor();
  assert.equal(downloads, downloadsBeforeFailure);
  assert.ok(!(await detail.innerText()).includes('private provider'));
  await exportReview();
  // An overdue receipt is not a proven failure. Server flag controls polling.
  const overdue = { ...review, status: 'running', completion_overdue: true, outcome: {} };
  let overdueGets = 0;
  await page.route(`**/api/runs/${run.id}/agent-reviews`, route => route.fulfill({ json: { items: [overdue], next_before_id: null } }));
  await page.route(`**/api/runs/${run.id}/agent-reviews/${review.id}`, route => {
    overdueGets++;
    return route.fulfill({ json: overdue });
  });
  await page.reload();
  await page.getByRole('button', { name: '실행 근거 보기', exact: true }).click();
  await panel.getByRole('button', { name: new RegExp(`검토 #${review.id} · 완료 확인 필요`) }).click();
  await detail.getByRole('status').filter({ hasText: '실행이 중단됐다는 뜻은 아닙니다.' }).waitFor();
  const beforeWait = overdueGets;
  await page.waitForTimeout(3500);
  assert.equal(overdueGets, beforeWait);
  const refreshed = page.waitForResponse(r => r.url().endsWith(`/agent-reviews/${review.id}`));
  await panel.getByRole('button', { name: '검토 이력 새로고침', exact: true }).click();
  await refreshed;
  assert.ok(overdueGets > beforeWait);
  await panel.screenshot({ path: `${output}/overdue-review.png` });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ result: 'PASS', output, checks: ['real Hermes review saved', 'requester and run snapshot', 'reload preserves result', 'same request does not rerun', 'viewer read-only', 'export bytes and snapshot', 'export failure and retry', 'overdue is unconfirmed', 'overdue stops polling', 'manual refresh remains available', '320/390/1440 layout'] }));
} finally { await browser.close(); }
