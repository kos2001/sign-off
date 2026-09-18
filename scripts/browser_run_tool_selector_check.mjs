import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';

const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE ?? 'playwright');
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(new URL(base).hostname, '127.0.0.1');
const output = '/private/tmp/signoff-run-tool-selector-check';
await mkdir(output, { recursive: true });

const expected = {
  rtl: { value: 'Verilator + Yosys', count: 5, text: '실제 실행은 RTL 분석에서 제공됩니다.' },
  sta: { value: 'OpenSTA', count: 3, text: 'OpenSTA JSON 보고서 가져오기를 지원합니다.' },
  emir: { value: 'Ansys RedHawk-SC', count: 3, text: 'IR drop과 전자이동 분석 결과' },
  pv: { value: 'KLayout DRC', count: 3, text: 'KLayout LYRDB 보고서 가져오기를 지원합니다.' },
  glitch_power: { value: 'Synopsys PrimePower', count: 3, text: '글리치와 동적 전력 분석 결과' },
  thermal: { value: 'Cadence Celsius', count: 3, text: '칩·패키지 열 분석 결과' },
};

const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 900 } });
  const login = await context.request.post(`${base}/api/auth/login`, { data: { username: 'qa-editor', password: fixture.password }, headers: { 'X-Signoff-Client': '1' } });
  assert.equal(login.status(), 200);
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/agents/review/gate', route => route.fulfill({ json: { a5: { role: 'a5_synth', triggered: false, available: null }, v: null } }));
  await page.goto(`${base}/projects/${fixture.project}`);
  await page.getByRole('heading', { name: '사인오프 런', exact: true }).waitFor();
  const domain = page.getByRole('combobox', { name: '도메인', exact: true });
  const tool = page.getByRole('combobox', { name: '결과 생성 툴', exact: true });
  const guide = page.getByRole('region', { name: '선택한 툴 안내', exact: true });
  assert.equal(await page.getByRole('textbox', { name: '툴', exact: true }).count(), 0);
  for (const [name, config] of Object.entries(expected)) {
    await domain.selectOption(name);
    assert.equal(await tool.inputValue(), config.value);
    assert.equal(await tool.locator('option').count(), config.count);
    await guide.getByText(config.text, { exact: false }).waitFor();
    await guide.getByText('툴을 실행하지 않고 수동 런의 출처만 기록', { exact: false }).waitFor();
  }
  await domain.selectOption('sta');
  await tool.selectOption('Cadence Tempus');
  await page.getByRole('button', { name: '런 생성', exact: true }).click();
  const created = page.getByRole('listitem').filter({ hasText: 'Cadence Tempus' }).first();
  await created.waitFor();
  await created.getByRole('button', { name: '실행 근거 보기', exact: true }).click();
  await created.getByText('수동으로 등록한 런입니다.', { exact: false }).waitFor();
  assert.equal(await tool.inputValue(), 'Cadence Tempus');
  await domain.selectOption('pv');
  assert.equal(await tool.inputValue(), 'KLayout DRC');
  const importLink = guide.getByRole('link', { name: 'KLayout DRC 보고서 가져오기로 이동', exact: true });
  assert.equal(await importLink.getAttribute('href'), `/projects/${fixture.project}/import/klayout`);
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `overflow at ${width}`);
  }
  await page.setViewportSize({ width: 390, height: 900 });
  await guide.locator('..').screenshot({ path: `${output}/selector-mobile.png` });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ result: 'PASS', checks: ['domain-specific options', 'recommended defaults', 'tool guidance', 'manual evidence boundary', 'selection persisted after create', 'domain reset', 'report import route', '320/390/1440 layout'], output }));
} finally {
  await browser.close();
}
