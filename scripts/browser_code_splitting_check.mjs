// Route-level code splitting on the production build: first-load JS per screen, lazy navigation, stale-chunk recovery.
// Serve `npm run build` with `npx vite preview` (dev mode does not split) against a local-mode backend seeded by
// backend/scripts/seed_demo.py.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE);
const base = process.env.SIGNOFF_TEST_UI || 'http://127.0.0.1:4173';
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(base).hostname));

const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(() => { try { if (!localStorage.getItem('signoff-language')) localStorage.setItem('signoff-language', 'en'); } catch { /* storage blocked */ } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const projects = await (await page.request.get(`${base}/api/projects`)).json();
  const project = projects.find(item => item.name === 'ibex-riscv-sky130');
  assert.ok(project, 'Seed the demo project first');

  async function firstLoadJs(path, heading) {
    // A fresh context per screen: no chunk is served from an earlier screen's cache.
    const fresh = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await fresh.addInitScript(() => { try { localStorage.setItem('signoff-language', 'en'); } catch { /* storage blocked */ } });
    const view = await fresh.newPage();
    view.on('pageerror', error => errors.push(error.message));
    await view.goto(`${base}${path}`);
    await view.getByRole('heading', { level: 1, name: heading }).waitFor();
    await view.waitForLoadState('networkidle');
    const bytes = await view.evaluate(() => performance.getEntriesByType('resource')
      .filter(entry => entry.name.endsWith('.js')).reduce((sum, entry) => sum + entry.decodedBodySize, 0));
    await fresh.close();
    return bytes;
  }
  const sizes = {
    guide: await firstLoadJs('/guide/overview', 'From chip verification evidence to an accountable decision.'),
    dashboard: await firstLoadJs('/', 'Project dashboard'),
    project: await firstLoadJs(`/projects/${project.id}`, project.name),
  };
  for (const [name, bytes] of Object.entries(sizes)) assert.ok(bytes < 600_000, `${name} first load ${bytes} bytes`);
  assert.ok(sizes.guide < sizes.project, 'The public guide must not download project screens');

  // Client-side navigation loads the next screen on demand without a page error.
  await page.goto(`${base}/`);
  await page.getByRole('heading', { name: 'Project dashboard' }).waitFor();
  await page.getByRole('link', { name: 'MMMC timing' }).click();
  await page.locator('[id="timing"]').waitFor();

  // A tab left open across a deploy requests a chunk the server no longer has.
  const stale = await context.newPage();
  await stale.route(/\/assets\/RunComparison-[^/]+\.js$/, route => route.fulfill({ status: 404, body: 'gone' }));
  await stale.goto(`${base}/projects/${project.id}/compare`);
  await stale.getByRole('heading', { name: 'A new version is available' }).waitFor();
  await stale.getByRole('button', { name: 'Reload page' }).waitFor();
  await stale.getByRole('navigation', { name: 'Main navigation' }).waitFor();
  await stale.close();

  assert.deepEqual(errors, [], 'Page errors');
  console.log(JSON.stringify({ result: 'PASS', first_load_js_bytes: sizes,
    checks: ['first-load JS per screen', 'guide smaller than project', 'lazy client navigation', 'stale chunk recovery'] }));
} finally {
  await browser.close();
}
