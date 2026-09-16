// Requires an isolated local backend with SIGNOFF_SIMULATION_MODE=trusted_local.
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE ?? process.argv[2] ?? 'playwright');
const base = process.env.SIGNOFF_TEST_UI ?? 'http://127.0.0.1:15173';
const backend = process.env.SIGNOFF_TEST_API ?? 'http://127.0.0.1:18000';
const output = process.env.SIGNOFF_TEST_OUTPUT ?? '/private/tmp/signoff-simulation-check';
for (const url of [base, backend]) assert.equal(new URL(url).hostname, '127.0.0.1');
await mkdir(output, { recursive: true });
async function api(path, body) {
  const response = await fetch(`${backend}${path}`, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
  assert.ok(response.ok);
  return response.json();
}
const project = await api('/projects', { name: `Simulation QA ${Date.now()}`, process_node: '130nm', foundry: 'SkyWater' });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
page.setDefaultTimeout(10000);
const errors = [];
page.on('pageerror', error => errors.push(error.message));
try {
  await page.goto(`${base}/analysis#rtl-signoff`);
  const ladder = page.locator('#rtl-signoff');
  await ladder.getByText('테스트벤치 (선택)', { exact: true }).click();
  await ladder.getByRole('button', { name: '펄스 동기화 검증 예제 불러오기', exact: true }).click();
  await ladder.getByRole('combobox', { name: '프로젝트에 기록 (선택)', exact: true }).selectOption(String(project.id));
  const bench = await ladder.getByRole('textbox', { name: '테스트벤치 SystemVerilog', exact: true }).inputValue();
  async function run() {
    const [response] = await Promise.all([
      page.waitForResponse(r => r.url().endsWith('/api/analysis/rtl-signoff/stream')),
      ladder.getByRole('button', { name: '사인오프 래더 실행', exact: true }).click(),
    ]);
    assert.equal(response.status(), 200);
    return JSON.parse((await response.text()).trim().split('\n').at(-1)).result;
  }
  const passed = await run();
  if (process.env.SIGNOFF_EXPECT_CONTAINER === '1') assert.equal(passed.execution.backend, 'container');
  assert.equal(passed.verdict, 'SIGNED_OFF');
  assert.equal(passed.simulation.status, 'pass');
  await ladder.getByText('테스트벤치 실행 근거 · pass', { exact: true }).click();
  await ladder.getByText('시뮬레이션 로그 · 종료 코드 0', { exact: true }).click();
  assert.match(await ladder.getByLabel('시뮬레이션 로그', { exact: true }).innerText(), /SIGNOFF_TEST_PASS/);
  await ladder.screenshot({ path: `${output}/simulation-desktop.png` });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Simulation form has no page overflow');
  await ladder.screenshot({ path: `${output}/simulation-mobile.png` });
  await ladder.getByRole('textbox', { name: '테스트벤치 SystemVerilog', exact: true }).fill(bench.replace('pulses !== 1', 'pulses !== 2'));
  const failed = await run();
  assert.equal(failed.verdict, 'REJECTED');
  const gate = await api(`/projects/${project.id}/signoff-status?stage=rtl`);
  assert.equal(gate.domains.find(d => d.domain === 'rtl').ready, false);
  await ladder.getByText('테스트벤치 실행 근거 · fail', { exact: true }).click();
  await ladder.getByText('시뮬레이션 로그 · 종료 코드 1', { exact: true }).click();
  assert.match(await ladder.getByLabel('시뮬레이션 로그', { exact: true }).innerText(), /expected exactly one/);
  await page.goto(`${base}/projects/${project.id}`);
  const row = page.getByRole('listitem', { name: `런 #${passed.run_id}`, exact: true });
  await row.getByRole('button', { name: '실행 근거 보기', exact: true }).click();
  if (process.env.SIGNOFF_EXPECT_CONTAINER === '1') await row.getByText(`실행 환경: 컨테이너 워커 · 이미지 ${passed.execution.image_id}`, { exact: true }).waitFor();
  await row.getByText('테스트벤치 실행 근거 · pass', { exact: true }).click();
  await row.getByText('실행한 테스트벤치 소스', { exact: true }).click();
  assert.equal((await row.getByLabel('실행한 테스트벤치 코드', { exact: true }).innerText()).trim(), bench.trim());
  const [download] = await Promise.all([page.waitForEvent('download'), row.getByRole('button', { name: '근거 JSON 다운로드', exact: true }).click()]);
  await download.saveAs(`${output}/simulation-evidence.json`);
  const saved = JSON.parse(await readFile(`${output}/simulation-evidence.json`, 'utf8')).result.simulation;
  assert.equal(saved.testbench_sha256, createHash('sha256').update(saved.testbench_source).digest('hex'));
  assert.equal(saved.status, 'pass');
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Stored evidence has no page overflow');
  await row.screenshot({ path: `${output}/simulation-evidence-mobile.png` });
  await page.goto(`${base}/analysis#rtl-signoff`);
  await page.route('**/api/analysis/rtl-signoff/stream', route => route.fulfill({ status: 200, contentType: 'application/x-ndjson', body: JSON.stringify({ event: 'error', detail: 'worker failed' }) + '\n' }));
  await ladder.getByRole('button', { name: '사인오프 래더 실행', exact: true }).click();
  await ladder.getByText('RTL 실행 워커가 작업을 완료하지 못했습니다. 서버 상태를 확인하고 다시 실행하세요.', { exact: true }).waitFor();
  assert.equal(await ladder.getByRole('button', { name: '사인오프 래더 실행', exact: true }).isEnabled(), true);
  await page.unroute('**/api/analysis/rtl-signoff/stream');
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ status: 'PASS', projectId: project.id, passedRun: passed.run_id, failedRun: failed.run_id, output }));
} catch (error) {
  console.error(await page.locator('main').ariaSnapshot());
  throw error;
} finally {
  await browser.close();
}
