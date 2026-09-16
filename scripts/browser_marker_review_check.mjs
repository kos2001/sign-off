// Disposable authenticated API. No model calls; state mutations stay in the QA database.
import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE);
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(base, 'http://127.0.0.1:15174');
const output = '/private/tmp/signoff-marker-review-check';
await mkdir(output, { recursive: true });
let source = await readFile(new URL('../backend/tests/fixtures/drc.lyrdb', import.meta.url), 'utf8');
const item = source.split('<item>')[1].split('</item>')[0];
source = source.replace('</items>', `<item>${item}</item><item>${item}</item></items>`);
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  async function login(target, role) {
    const r = await target.request.post(`${base}/api/auth/login`, { headers: { 'X-Signoff-Client': '1' }, data: { username: `qa-${role}`, password: fixture.password } });
    assert.equal(r.status(), 200); return r.json();
  }
  const session = await login(context, 'editor');
  const imported = await context.request.post(`${base}/api/projects/${fixture.project}/imports/klayout`, { headers: { 'X-CSRF-Token': session.csrf_token }, data: { import_id: randomUUID(), stage: 'placement', filename: 'duplicates.lyrdb', tool_version: 'QA', design_revision: 'qa', scenario: 'review fixture', source_text: source } });
  assert.equal(imported.status(), 201);
  const run = await imported.json();
  const original = await (await context.request.get(`${base}/api/runs/${run.id}/markers/1`)).json();
  const ids = original.violation_matches.items.map(item => item.id);
  assert.equal(ids.length, 3);
  await login(context, 'viewer');
  const page = await context.newPage();
  page.setDefaultTimeout(12000);
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(`${base}/runs/${run.id}/markers?selected=1`);
  const panel = page.getByRole('region', { name: '마커에 연결된 위반 검토', exact: true });
  await panel.getByText('일대일 대응을 확정할 수 없습니다.', { exact: false }).waitFor();
  assert.equal(await panel.getByRole('button', { name: '수정 완료 처리', exact: true }).count(), 0);
  await panel.getByRole('button', { name: new RegExp(`^위반 #${ids[0]} ·`) }).click();
  assert.ok(await panel.getByRole('button', { name: '수정 완료 처리', exact: true }).isDisabled());
  await login(context, 'editor');
  await page.reload();
  await panel.getByRole('button', { name: new RegExp(`^위반 #${ids[0]} ·`) }).click();
  assert.ok(await panel.getByRole('button', { name: '웨이버 검토', exact: true }).isDisabled());
  await panel.getByRole('button', { name: '수정 완료 처리', exact: true }).click();
  await panel.getByRole('textbox', { name: '수정 근거 · 검증 결과', exact: true }).fill('검토 중인 사유는 충돌 후에도 보존');
  const other = await browser.newContext();
  const approver = await login(other, 'approver');
  assert.equal((await other.request.post(`${base}/api/violations/${ids[0]}/waiver`, { headers: { 'X-CSRF-Token': approver.csrf_token }, data: { expected_version: 1, reason: '다른 검토자의 승인', approved_by: 'ignored' } })).status(), 201);
  await panel.getByRole('button', { name: '위반 상태 새로고침', exact: true }).click();
  await panel.getByText('다른 검토자가 이 항목을 변경했습니다.', { exact: false }).waitFor();
  assert.equal(await panel.getByRole('textbox', { name: '수정 근거 · 검증 결과', exact: true }).inputValue(), '검토 중인 사유는 충돌 후에도 보존');
  assert.ok(await panel.getByRole('button', { name: '변경 저장', exact: true }).isDisabled());
  await panel.screenshot({ path: `${output}/stale-review.png` });
  await login(context, 'approver');
  await page.reload();
  await panel.getByRole('button', { name: new RegExp(`^위반 #${ids[1]} ·`) }).click();
  await panel.getByRole('button', { name: '웨이버 검토', exact: true }).click();
  await panel.getByRole('textbox', { name: '처리 사유', exact: true }).fill('선택한 위반만 별도 승인');
  const savedEvent = page.waitForResponse(r => r.url().endsWith(`/violations/${ids[1]}`) && r.request().method() === 'PATCH');
  await panel.getByRole('button', { name: '변경 저장', exact: true }).click();
  assert.equal((await savedEvent).status(), 200);
  await panel.getByRole('button', { name: new RegExp(`^위반 #${ids[1]} · 웨이버 승인`) }).waitFor();
  await panel.getByRole('button', { name: '변경 이력', exact: true }).click();
  await panel.getByText('선택한 위반만 별도 승인', { exact: true }).last().waitFor();
  const updated = await (await context.request.get(`${base}/api/runs/${run.id}/markers/1`)).json();
  assert.deepEqual(updated.item, original.item);
  assert.deepEqual(updated.geometry, original.geometry);
  assert.deepEqual(updated.violation_matches.items.map(item => item.status), ['waived', 'waived', 'open']);
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (width === 390) await panel.screenshot({ path: `${output}/approved-review.png` });
  }
  assert.deepEqual(errors, []);
  await other.close();
  console.log('PASS: ambiguous links require selection, viewer/editor/approver permissions, stale draft protection, single-record approval/history, immutable markers, responsive layout');
} finally { await browser.close(); }
