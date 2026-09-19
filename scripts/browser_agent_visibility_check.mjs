// Disposable authenticated API; only LLM responses are mocked.
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE);
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(new URL(base).hostname, '127.0.0.1');
assert.equal(new URL(base).port, '15174');
const output = '/private/tmp/signoff-agent-visibility-check';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const login = await context.request.post(`${base}/api/auth/login`, { data: { username: 'qa-editor', password: fixture.password }, headers: { 'X-Signoff-Client': '1' } });
  assert.equal(login.status(), 200);
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const badge = label => page.locator('header').getByText(label, { exact: false });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  let mode = 'success';
  let release;
  const review = (role, available = true) => ({ role, role_name: role, triggered: true, available, review: available ? `${role} 근거 검토 완료` : null, error: available ? null : 'private provider credentials', error_id: available ? undefined : 'e'.repeat(32), review_id: role === 'a5_synth' ? 'a'.repeat(32) : 'b'.repeat(32), completed_at: '2026-09-16T03:00:00+00:00', duration_ms: 1200, trigger: 'private endpoint configuration' });
  await page.route('**/api/agents/review/gate', async route => {
    const current = mode;
    if (current === 'pending') await new Promise(resolve => { release = resolve; });
    if (current === 'http') return route.fulfill({ status: 503, json: { detail: 'private failure' } });
    const a5 = review('a5_synth', current !== 'upstream');
    if (current === 'skipped') Object.assign(a5, { triggered: false, available: null, review: null, completed_at: undefined, duration_ms: undefined });
    await route.fulfill({ json: { a5, v: ['upstream', 'skipped'].includes(current) ? null : review('v_verify', current !== 'verify-fail') } });
  });
  await page.goto(`${base}/agents`);
  await page.getByRole('heading', { name: '에이전트 개입 안내', exact: true }).waitFor();
  await page.getByText('자동 연결 안 됨', { exact: false }).waitFor();
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `guide overflow at ${width}`);
    if (width !== 320) await page.screenshot({ path: `${output}/guide-${width}.png`, fullPage: true });
  }
  for (const [tool, name, count] of [['rtl', 'RTL 리뷰어', 1], ['timing', '타이밍 분석가', 1], ['ir-drop', '파워/IR 무결성 분석가', 1]]) {
    await page.goto(`${base}/analysis/${tool}`);
    await page.getByRole('region', { name: `${name} 검토 의견`, exact: true }).waitFor();
    assert.equal(await badge('실행 전').count(), count);
  }
  mode = 'pending';
  await page.goto(`${base}/projects/${fixture.project}`);
  await badge('검토 결과 대기').first().waitFor();
  await page.getByText('이 단계 검증 미실행', { exact: false }).first().waitFor();
  assert.equal(await badge('검토 완료').count(), 0);
  await page.getByText('두 역할의 결과는 함께 표시되며', { exact: false }).waitFor();
  mode = 'success';
  release();
  await page.getByText('v_verify 근거 검토 완료', { exact: true }).waitFor();
  assert.equal(await badge('검토 완료').count(), 2);
  assert.equal(await page.locator('time').count(), 2);
  await page.getByText('검토 기록 안내', { exact: true }).first().click();
  await page.getByText('의견은 현재 화면의 조회 결과이며 서버에 검토 이력으로 저장되지 않습니다.', { exact: false }).first().waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: `${output}/gate-completed-390.png`, fullPage: true });
  for (const next of ['skipped', 'upstream', 'http', 'verify-fail']) {
    mode = next;
    await page.reload();
    if (next === 'skipped') {
      await badge('조건 미해당 · 실행 안 됨').first().waitFor();
      assert.equal(await badge('조건 미해당 · 실행 안 됨').count(), 2);
    } else if (next === 'upstream') {
      await badge('선행 검토 미완료').waitFor();
    } else if (next === 'http') {
      await badge('진행 확인 불가').waitFor();
    } else {
      await page.getByRole('region', { name: '검토 서비스 상태' }).waitFor();
      await page.getByText('a5_synth 근거 검토 완료', { exact: true }).waitFor();
      mode = 'success';
      await page.getByRole('button', { name: '종합·검증 다시 시도', exact: true }).click();
      await page.getByText('v_verify 근거 검토 완료', { exact: true }).waitFor();
    }
    assert.ok(!(await page.locator('body').innerText()).includes('private'));
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  }
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ result: 'PASS', output, checks: ['guide and inactive waiver role', 'pre-analysis conditions', 'pending without false completion', 'completion metadata', 'skipped roles', 'upstream failure', 'unknown HTTP outcome', 'verifier retry', 'no provider internals', '320/390/1440 layout'] }));
} finally { await browser.close(); }
