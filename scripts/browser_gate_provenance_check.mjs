// Real disposable auth API and gate; only the advisory provider is mocked.
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE);
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(base, 'http://127.0.0.1:15174');
const output = '/private/tmp/signoff-gate-provenance-check';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  assert.equal((await context.request.post(`${base}/api/auth/login`, { headers: { 'X-Signoff-Client': '1' }, data: { username: 'qa-viewer', password: fixture.password } })).status(), 200);
  const page = await context.newPage();
  const errors = [], requests = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/api/agents/review/gate', async route => {
    requests.push(route.request().postDataJSON());
    await route.fulfill({ json: { a5: { role: 'a5_synth', role_name: 'QA', triggered: true, available: false, review: null, error: 'review_unavailable' }, v: null } });
  });
  await page.goto(`${base}/projects/${fixture.project}`);
  await page.getByRole('button', { name: 'Placement', exact: true }).click();
  await page.getByText('설계 리비전 불일치 · 게이트 차단', { exact: true }).waitFor();
  await page.getByText('선택된 리비전: revision-A / revision-B', { exact: true }).waitFor();
  await page.getByText('리비전 누락:', { exact: false }).waitFor();
  assert.equal(await page.getByText('검증 범위 근거 필요 · 수동 상태만으로 통과 불가', { exact: false }).count(), 3);
  assert.ok(requests.some(r => r.gate_status.stage === 'placement' && r.gate_status.revision_check.status === 'mismatch' && r.gate_status.ready === false));
  let downloaded = 0;
  page.on('download', () => downloaded++);
  const exportRoute = '**/signoff-status/export?stage=placement';
  await page.route(exportRoute, route => route.fulfill({ status: 503, json: { detail: 'test unavailable' } }), { times: 1 });
  await page.getByRole('button', { name: '게이트·근거 JSON 다운로드', exact: true }).click();
  await page.getByRole('alert').waitFor();
  assert.equal(downloaded, 0);
  let wireBytes;
  await page.route(exportRoute, async route => {
    const upstream = await route.fetch();
    wireBytes = await upstream.body();
    await route.fulfill({ response: upstream });
  }, { times: 1 });
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button', { name: '게이트·근거 JSON 다운로드', exact: true }).click();
  const download = await downloadEvent;
  assert.equal(download.suggestedFilename(), `project-${fixture.project}-placement-gate.json`);
  const downloadedBytes = await readFile(await download.path());
  assert.ok(downloadedBytes.equals(wireBytes));
  const bundle = JSON.parse(downloadedBytes.toString());
  assert.equal(bundle.gate.revision_check.status, 'mismatch');
  assert.equal(bundle.gate.ready, false);
  assert.deepEqual(bundle.runs.map(run => run.id).sort(), bundle.gate.domains.map(domain => domain.run_id).sort());
  assert.equal(bundle.runs.length, 3);
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `overflow ${width}`);
    if (width === 390) await page.screenshot({ path: `${output}/gate-mobile.png`, fullPage: true });
  }
  await page.getByRole('button', { name: 'Synthesis', exact: true }).click();
  await page.getByText('설계 리비전 미확인 · 게이트 차단', { exact: true }).waitFor();
  assert.equal(await page.getByText('선택된 리비전: revision-A / revision-B', { exact: true }).count(), 0);
  assert.deepEqual(errors, []);
  console.log('PASS: real gate, byte-exact export, error/retry, provider input, stage isolation, 320/390/1440 layout');
} finally { await browser.close(); }
