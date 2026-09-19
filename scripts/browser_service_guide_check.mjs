// Read-only product guide and navigation checks; no project mutations.
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE);
const base = process.env.SIGNOFF_TEST_UI || 'http://127.0.0.1:15173';
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(base).hostname));
const output = '/tmp/signoff-service-guide-check';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const sections = ['overview', 'workflow', 'capabilities', 'agents', 'start'];
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  // The public guide must work without a backend or login session.
  let apiRequests = 0;
  await page.route('**/api/**', route => { apiRequests++; return route.abort(); });
  for (const lang of ['ko', 'en']) {
    for (const section of sections) {
      await page.goto(`${base}/guide/${lang}/${section}`);
      await page.getByRole('heading', { level: 1 }).waitFor();
      assert.equal(await page.locator('html').getAttribute('lang'), lang);
      assert.equal(await page.locator('.guide-nav a[aria-current="page"]').count(), 1);
      assert.equal(await page.locator('.guide-card').count(), section === 'overview' ? 3 : ['workflow', 'agents'].includes(section) ? 5 : 4);
      const content = await page.locator('main').innerText();
      if (lang === 'en') assert.ok(!/[가-힣]/.test(content), `${section} contains untranslated Korean`);
      for (const width of [1440, 390, 320]) {
        await page.setViewportSize({ width, height: 1000 });
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${lang}/${section}: overflow at ${width}`);
      }
      await page.setViewportSize({ width: 1440, height: 1000 });
    }
  }
  assert.equal(apiRequests, 0, 'Public guide must not request protected API data');
  await page.goto(`${base}/guide/ko/workflow`);
  await page.getByRole('link', { name: 'English', exact: true }).click();
  await page.waitForURL('**/guide/en/workflow');
  await page.reload();
  await page.getByRole('heading', { name: 'Build evidence throughout development, before final review.' }).waitFor();
  await page.goto(`${base}/guide`);
  await page.waitForURL('**/guide/en/overview');
  await page.screenshot({ path: `${output}/overview-en-desktop.png`, fullPage: true });
  await page.getByRole('link', { name: '한국어', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: `${output}/overview-ko-mobile.png`, fullPage: true });
  await page.goto(`${base}/guide/ko/workflow`);
  await page.screenshot({ path: `${output}/workflow-ko-mobile.png`, fullPage: true });
  await page.goto(`${base}/guide/unknown/missing`);
  await page.waitForURL('**/guide/ko/overview');
  // Check ordinary navigation and browser history preserve page and language.
  await page.locator('.guide-nav').getByRole('link', { name: '에이전트와 사람' }).click();
  await page.waitForURL('**/guide/ko/agents');
  await page.goBack();
  await page.waitForURL('**/guide/ko/overview');
  await page.unroute('**/api/**');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('link', { name: '작업 공간 열기' }).click();
  await page.getByRole('heading', { name: '프로젝트 대시보드' }).waitFor();
  const legacy = { 'rtl-signoff': 'rtl', 'sta-signoff': 'sta', 'ir-drop': 'ir-drop', timing: 'timing', 'glitch-power': 'glitch-power' };
  for (const [hash, slug] of Object.entries(legacy)) {
    await page.goto(`${base}/analysis#${hash}`);
    await page.waitForURL(`**/analysis/${slug}`);
    await page.locator(`[id="${hash}"]`).waitFor();
    assert.equal(await page.locator('[id="rtl-signoff"], [id="sta-signoff"], [id="ir-drop"], [id="timing"], [id="glitch-power"]').count(), 1);
    await page.getByRole('link', { name: '← 분석 도구 선택' }).click();
    await page.waitForURL('**/analysis');
    await page.locator('main a.card').first().waitFor();
    assert.equal(await page.locator('main a.card').count(), 5);
  }
  await page.screenshot({ path: `${output}/analysis-tools.png`, fullPage: true });
  // A login-required deployment still exposes the guide through the login screen.
  await page.route('**/api/auth/session', route => route.fulfill({ json: { mode: 'required', user: null, csrf_token: null, memberships: {} } }));
  await page.goto(base);
  await page.getByRole('heading', { name: 'Sign-off Hub 로그인' }).waitFor();
  await page.getByRole('link', { name: '서비스 소개 · 한국어 / English →' }).click();
  await page.waitForURL('**/guide/ko/overview');
  assert.equal(errors.length, 0, errors.join('\n'));
  console.log(JSON.stringify({ result: 'PASS', pages: 10, widths: [1440, 390, 320], checks: ['public without API', 'English completeness', 'language switch and persistence', 'history', 'legacy analysis URLs', 'one tool per page', 'login entry'], output }));
} finally { await browser.close(); }
