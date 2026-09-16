// Point only at a disposable local server. Hold/release its admission slot externally.
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE ?? process.argv[2] ?? 'playwright');
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(new URL(base).hostname, '127.0.0.1');
const busy = process.argv[3] !== 'available';
const output = '/private/tmp/signoff-rtl-capacity-check';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  page.setDefaultTimeout(15000);
  await page.route('**/api/agents/review/rtl', route => route.fulfill({ json: { role: 'a1_rtl', role_name: 'RTL 리뷰어', triggered: false, available: null, review: null, error: null } }));
  await page.goto(`${base}/analysis#rtl-signoff`);
  const ladder = page.locator('#rtl-signoff');
  const source = 'module capacity_test(input wire a, output wire y); assign y = a; endmodule';
  await ladder.getByRole('textbox', { name: 'SystemVerilog 소스', exact: true }).fill(source);
  const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/analysis/rtl-signoff/stream'));
  await ladder.getByRole('button', { name: '사인오프 래더 실행', exact: true }).click();
  const response = await responsePromise;
  assert.equal(response.status(), busy ? 429 : 200);
  if (busy) {
    await ladder.getByText('서버의 RTL 분석이 모두 사용 중입니다. 아직 분석을 시작하지 않았습니다. 5초 뒤 다시 실행하세요.', { exact: true }).waitFor();
    assert.equal(response.headers()['retry-after'], '5');
  } else {
    const result = JSON.parse((await response.text()).trim().split('\n').at(-1));
    assert.equal(result.event, 'result');
    assert.ok(result.result.verdict);
  }
  await ladder.getByRole('button', { name: '사인오프 래더 실행', exact: true }).waitFor();
  assert.equal(await ladder.getByRole('button', { name: '사인오프 래더 실행', exact: true }).isEnabled(), true);
  assert.ok((await ladder.getByRole('button', { name: '사인오프 래더 실행', exact: true }).boundingBox()).height < 64, 'Run button must not collapse into vertical text');
  assert.equal(await ladder.getByRole('textbox', { name: 'SystemVerilog 소스', exact: true }).inputValue(), source);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await ladder.screenshot({ path: `${output}/${busy ? 'busy' : 'available'}-mobile.png` });
  console.log(JSON.stringify({ result: 'PASS', mode: busy ? 'busy' : 'available', checks: ['HTTP status', 'retained source', 'run button restored', 'mobile'], output }));
} finally { await browser.close(); }
