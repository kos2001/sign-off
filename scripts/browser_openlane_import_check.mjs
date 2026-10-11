// OpenLane 2 metrics import: upload real flow results, save domain runs, inspect evidence and compare revisions.
// Requires a local-mode backend on a throwaway DB; creates its own project.
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE);
const base = process.env.SIGNOFF_TEST_UI || 'http://127.0.0.1:15173';
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(base).hostname));
const output = process.env.SIGNOFF_TEST_OUTPUT || '/tmp/signoff-openlane-import-check';
await mkdir(output, { recursive: true });
const fixture = name => fileURLToPath(new URL(`../backend/tests/fixtures/openlane/${name}.json`, import.meta.url));

const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(() => { try { if (!localStorage.getItem('signoff-language')) localStorage.setItem('signoff-language', 'en'); } catch { /* storage blocked */ } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const created = await page.request.post(`${base}/api/projects`, { data: { name: `openlane-qa-${Date.now()}`, process_node: 'SKY130', foundry: 'SkyWater' } });
  assert.equal(created.status(), 201, await created.text());
  const project = await created.json();

  async function importRun(name, revision) {
    await page.goto(`${base}/projects/${project.id}/import`);
    await page.getByRole('navigation', { name: 'Report format' }).getByRole('link', { name: 'OpenLane 2', exact: true }).click();
    await page.getByRole('heading', { name: 'Import OpenLane 2 flow results' }).waitFor();
    await page.getByLabel('metrics.json or state_out.json file').setInputFiles(fixture(name));
    await page.getByLabel('OpenLane version').fill('2.3.10');
    await page.getByLabel('Design revision').fill(revision);
    await page.getByLabel('Run tag / configuration').fill(`${name}-run`);
    assert.match(await page.getByLabel('Metrics JSON').inputValue(), /timing__setup__ws/);
    await page.getByRole('button', { name: 'Preview import' }).click();
    const preview = page.getByRole('region', { name: 'Import preview' });
    await preview.waitFor();
    return preview;
  }

  const failing = await importRun('aes-timing-fail', 'rev-a');
  const sta = failing.getByRole('region', { name: 'STA' });
  assert.match(await sta.getByRole('row', { name: /max_ss_100C_1v60/ }).innerText(), /-1,467/);
  assert.match(await sta.innerText(), /6 blocking findings/);
  assert.match(await failing.getByRole('region', { name: 'PV' }).innerText(), /Antenna-violating nets\s*10/);
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `preview overflows at ${width}px`);
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: `${output}/preview-en-desktop.png`, fullPage: true });
  await failing.getByRole('button', { name: 'Save as 3 runs' }).click();
  const saved = page.getByRole('status', { name: 'Saved runs' });
  await saved.waitFor();
  const links = saved.getByRole('link', { name: /^Run #\d+ · / });
  assert.equal(await links.count(), 3);
  const staHref = await links.filter({ hasText: 'STA' }).getAttribute('href');
  const baseline = Number(staHref.split('/').pop());

  const passing = await importRun('aes-antenna', 'rev-b');
  await passing.getByRole('button', { name: 'Save as 3 runs' }).click();
  await page.getByRole('status', { name: 'Saved runs' }).waitFor();
  const candidate = Number((await page.getByRole('status', { name: 'Saved runs' }).getByRole('link', { name: /STA/ }).getAttribute('href')).split('/').pop());

  await page.goto(`${base}/runs/${baseline}`);
  await page.getByRole('button', { name: 'Show run evidence' }).first().click();
  const evidence = page.getByRole('region', { name: `Run #${baseline} evidence` });
  await evidence.getByText('OpenLane 2 · metrics.json · aes-timing-fail.json').waitFor();
  assert.match(await evidence.innerText(), /Runs created from the same file: STA · PV · LVS/);
  const download = page.waitForEvent('download');
  await evidence.getByRole('button', { name: /Download source/ }).click();
  assert.match((await download).suggestedFilename(), /\.json$/);

  await page.goto(`${base}/projects/${project.id}/compare?baseline=${baseline}&candidate=${candidate}`);
  await page.getByText('setup_wns_ps').first().waitFor();
  assert.match(await page.locator('main').innerText(), /setup_violations/);

  await page.goto(`${base}/projects/${project.id}`);
  await page.getByRole('button', { name: 'Routing', exact: true }).click();
  await page.waitForLoadState('networkidle');
  assert.equal(await page.getByRole('button', { name: 'Routing', exact: true }).getAttribute('aria-pressed'), 'true');
  assert.match(await page.locator('main').innerText(), /OpenLane flow metrics alone do not establish full coverage/);
  const hangul = await page.evaluate(() => /[가-힣]/.test(document.querySelector('main').innerText));
  assert.equal(hangul, false, 'English project page shows Korean text');

  await page.getByRole('button', { name: '한국어', exact: true }).click();
  await page.goto(`${base}/projects/${project.id}/import/openlane`);
  await page.getByRole('heading', { name: 'OpenLane 2 플로우 결과 가져오기' }).waitFor();
  assert.deepEqual(errors, [], 'Page errors');
  console.log(JSON.stringify({ result: 'PASS', checks: ['file upload preview', 'per-corner timing table', 'domain findings', '390/320 width', 'three domain runs', 'evidence panel and source download', 'revision comparison', 'gate reason', 'English and Korean'], output }));
} finally {
  await browser.close();
}
