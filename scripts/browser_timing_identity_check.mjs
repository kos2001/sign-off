// Read-only analysis against localhost; review-provider responses are mocked.
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE ?? process.argv[2] ?? 'playwright');
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(new URL(base).hostname, '127.0.0.1');
const output = '/private/tmp/signoff-timing-identity-check';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.name));
  await page.route('**/api/projects', route => route.fulfill({ json: [] }));
  await page.route('**/api/agents/review/timing', route => route.fulfill({ json: { role: 'a2_timing', role_name: '타이밍 분석가', triggered: false, available: null, review: null, error: null } }));
  await page.goto(`${base}/analysis#timing`);
  const panel = page.locator('#timing');
  await panel.getByText('분석 데이터 편집', { exact: true }).click();
  const corners = [{ name: 'slow', endpoint_ids: ['a/D', 'b/D'], endpoint_slacks_ps: [-10, 20] }, { name: 'fast', endpoint_ids: ['b/D', 'a/D'], endpoint_slacks_ps: [5, -20] }];
  const input = panel.getByRole('textbox', { name: '코너 JSON', exact: true });
  await input.fill(JSON.stringify(corners, null, 2));
  await panel.getByRole('button', { name: '코너 분석', exact: true }).click();
  await panel.getByRole('status').filter({ hasText: '종점 ID 기준으로 코너를 대응했습니다.' }).waitFor();
  await panel.getByText('1/2', { exact: true }).first().waitFor();
  const worst = panel.getByRole('region', { name: '최악 종점과 코너', exact: true });
  await worst.getByText('EP0 · a/D', { exact: true }).waitFor();
  await worst.getByText('-20 ps · fast', { exact: true }).waitFor();
  assert.equal(await panel.getByRole('figure', { name: '엔드포인트 슬랙', exact: true }).getByRole('button').count(), 2);
  const chart = panel.getByRole('figure', { name: '엔드포인트 슬랙', exact: true });
  const firstRow = chart.getByRole('button').first();
  await firstRow.focus();
  await firstRow.press('Enter');
  await chart.getByRole('region', { name: 'EP0 슬랙 상세', exact: true }).getByText('EP0 · a/D', { exact: true }).waitFor();
  assert.equal(await firstRow.getAttribute('aria-expanded'), 'true');
  await firstRow.press('Space');
  assert.equal(await chart.getByRole('region').count(), 0);
  await firstRow.press('Tab');
  assert.match(await page.evaluate(() => document.activeElement.getAttribute('aria-label')), /^EP1/);
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await chart.evaluate(element => element.scrollWidth <= element.clientWidth));
    assert.ok(await chart.getByRole('button').evaluateAll(buttons => buttons.every(button => button.scrollWidth <= button.clientWidth)));
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await chart.screenshot({ path: `${output}/slack-chart-mobile.png` });

  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await panel.screenshot({ path: `${output}/by-id-mobile.png` });
  const invalid = structuredClone(corners);
  invalid[1].endpoint_ids = ['a/D', 'a/D'];
  await input.fill(JSON.stringify(invalid));
  assert.equal(await worst.count(), 0);
  await panel.getByRole('button', { name: '코너 분석', exact: true }).click();
  await panel.getByRole('alert').filter({ hasText: 'endpoint_ids must be unique' }).waitFor();
  assert.equal(await input.inputValue(), JSON.stringify(invalid));
  await input.fill(JSON.stringify(corners.map(({ endpoint_ids, ...corner }) => corner)));
  await panel.getByRole('button', { name: '코너 분석', exact: true }).click();
  await panel.getByRole('status').filter({ hasText: '입력 순서대로 대응했습니다.' }).waitFor();
  await panel.getByText('2/2', { exact: true }).first().waitFor();
  const edgeValues = [-1.23456789e100, -1.23456789e100, -1e-100, 0, 1.23456789e100];
  const longId = 'top/' + 'nested/'.repeat(25) + 'D';
  await input.fill(JSON.stringify([{ name: 'numeric-boundaries', endpoint_ids: [longId, 'tie/D', 'tiny/D', 'zero/D', 'positive/D'], endpoint_slacks_ps: edgeValues }]));
  await panel.getByRole('button', { name: '코너 분석', exact: true }).click();
  await panel.getByRole('status').filter({ hasText: '종점 ID 기준으로 코너를 대응했습니다.' }).waitFor();
  assert.equal(await chart.getByRole('button', { name: /표시된 종점 중 최소 슬랙/ }).count(), 2);
  await chart.getByRole('button').first().click();
  await chart.getByRole('region').getByText(`EP0 · ${longId}`, { exact: true }).waitFor();
  await chart.getByRole('region').getByText(`슬랙 ${edgeValues[0]} ps · 표시된 종점 중 최소 슬랙`, { exact: true }).waitFor();
  await chart.getByRole('button', { name: 'EP2 · tiny/D · 슬랙 -1e-100 ps', exact: true }).waitFor();
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await chart.evaluate(element => element.scrollWidth <= element.clientWidth));
    assert.ok(await chart.getByRole('button').evaluateAll(buttons => buttons.every(button => button.scrollWidth <= button.clientWidth)));
  }
  await page.setViewportSize({ width: 320, height: 900 });
  await chart.screenshot({ path: `${output}/slack-chart-boundaries.png` });
  await input.fill(JSON.stringify([{ name: 'tiny-violation', endpoint_slacks_ps: [-0.00001, 0] }]));
  await panel.getByRole('button', { name: '코너 분석', exact: true }).click();
  await panel.getByRole('status').filter({ hasText: '입력 순서대로 대응했습니다.' }).waitFor();
  const wnsTile = panel.locator('.card').filter({ has: page.getByText('머지 WNS', { exact: true }) });
  const tnsTile = panel.locator('.card').filter({ has: page.getByText('머지 TNS', { exact: true }) });
  assert.match(await wnsTile.innerText(), /-0\.00001/);
  assert.match(await tnsTile.innerText(), /-0\.00001/);
  const cornerRow = panel.getByRole('row').filter({ has: page.getByRole('cell', { name: 'tiny-violation', exact: true }) });
  assert.equal(await cornerRow.getByRole('cell', { name: '-0.00001', exact: true }).count(), 2);
  await worst.getByText('-0.00001 ps · tiny-violation', { exact: true }).waitFor();
  await panel.getByText('1/2', { exact: true }).first().waitFor();
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  }
  await page.setViewportSize({ width: 320, height: 900 });
  await panel.screenshot({ path: `${output}/tiny-violation-mobile.png` });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ result: 'PASS', checks: ['custom corner input', 'reordered IDs', 'limiting corner', 'server-derived chart', 'keyboard detail', '320/390/1440 width', 'duplicate rejection', 'stale result cleared', 'positional disclosure', 'mobile', 'minimum ties', 'long ID', 'tiny/zero/large values', 'full precision detail', 'tiny violation summary and corner metrics'], output }));
} finally { await browser.close(); }
