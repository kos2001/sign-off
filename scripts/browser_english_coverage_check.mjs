// English workspace coverage: with English selected, no screen may render Korean UI text.
// Requires a local-mode backend (default SIGNOFF_AUTH_MODE) on a throwaway DB seeded by
// backend/scripts/seed_demo.py, whose data is English, so any Hangul on screen is UI copy.
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE);
const base = process.env.SIGNOFF_TEST_UI || 'http://127.0.0.1:15173';
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(base).hostname));
const output = process.env.SIGNOFF_TEST_OUTPUT || '/tmp/signoff-english-coverage-check';
await mkdir(output, { recursive: true });

const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(() => { try { localStorage.setItem('signoff-language', 'en'); } catch { /* storage blocked */ } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));

  const projects = await (await page.request.get(`${base}/api/projects`)).json();
  const project = projects.find(item => item.name === 'ibex-riscv-sky130');
  assert.ok(project, 'Seed the demo project first (backend/scripts/seed_demo.py)');
  const runsPayload = await (await page.request.get(`${base}/api/projects/${project.id}/runs?limit=100`)).json();
  const runs = Array.isArray(runsPayload) ? runsPayload : runsPayload.items;
  const runOf = domain => runs.find(run => run.domain === domain)?.id ?? runs[0].id;
  const p = `/projects/${project.id}`;
  const routes = [
    '/', p, `${p}/violations`, `${p}/compare`, `${p}/sta-matrix`, `${p}/revision-coverage`, `${p}/members`, `${p}/collectors`,
    `${p}/import`, `${p}/import/openlane`, `${p}/import/commercial-sta`, `${p}/import/commercial-drc`, `${p}/import/klayout`,
    ...['emir', 'power', 'thermal', 'rtl', 'lvs', 'lec', 'cdc', 'dft', 'low-power'].map(kind => `${p}/import/commercial-${kind}`),
    ...runs.map(run => `/runs/${run.id}`),
    `/runs/${runOf('rtl')}/structure`, `/runs/${runOf('sta')}/paths`, `/runs/${runOf('pv')}/markers`,
    `/runs/${runOf('emir')}/power-integrity`, `/runs/${runOf('rtl')}/power-breakdown`, `/runs/${runOf('rtl')}/thermal-hotspots`,
    ...['rtl-regression', 'lvs-mismatches', 'lec-failures', 'cdc-findings', 'dft-findings', 'low-power-findings'].map(view => `/runs/${runOf('rtl')}/${view}`),
    '/account', '/admin/security-events', '/agents', '/analysis',
    ...['rtl', 'sta', 'ir-drop', 'timing', 'glitch-power'].map(tool => `/analysis/${tool}`),
    '/no-such-screen',
  ];

  const findings = [];
  for (const route of routes) {
    await page.goto(`${base}${route}`);
    await page.locator('main').first().waitFor();
    await page.waitForLoadState('networkidle');
    assert.equal(await page.locator('html').getAttribute('lang'), 'en', `${route}: document language`);
    const hits = await page.evaluate(() => {
      document.querySelectorAll('details').forEach(item => { item.open = true; });
      const hangul = /[가-힣]/;
      const toggle = el => el.closest('[lang="ko"]');
      const out = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const text = node.textContent.trim();
        if (hangul.test(text) && !toggle(node.parentElement) && !node.parentElement.closest('script,style')) out.push(text.slice(0, 120));
      }
      for (const el of document.querySelectorAll('[aria-label],[placeholder],[title],[alt]')) {
        for (const name of ['aria-label', 'placeholder', 'title', 'alt']) {
          const value = el.getAttribute(name);
          if (value && hangul.test(value) && !toggle(el)) out.push(`@${name}: ${value.slice(0, 120)}`);
        }
      }
      return [...new Set(out)];
    });
    for (const hit of hits) findings.push(`${route} → ${hit}`);
  }
  // Longer English copy must not push any screen wider than a phone.
  await page.setViewportSize({ width: 390, height: 844 });
  for (const route of routes) {
    await page.goto(`${base}${route}`);
    await page.waitForLoadState('networkidle');
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    if (overflow > 0) findings.push(`${route} → horizontal overflow ${overflow}px at 390px`);
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${base}${p}`);
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: `${output}/project-en-desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: `${output}/project-en-mobile.png`, fullPage: true });

  assert.deepEqual(errors, [], 'Page errors');
  assert.deepEqual(findings, [], `Untranslated Korean in English mode:\n${findings.join('\n')}`);
  console.log(`result: PASS\nchecked: ${routes.length} routes in English, no Korean UI text, no 390px overflow, no page errors\noutput: ${output}`);
} finally {
  await browser.close();
}
