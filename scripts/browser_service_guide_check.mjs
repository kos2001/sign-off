// Read-only guide, shared language preference and navigation checks.
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
  let apiRequests = 0;
  await page.route('**/api/**', route => { apiRequests++; return route.abort(); });
  await page.goto(`${base}/guide/overview`);
  for (const lang of ['ko', 'en']) {
    await page.getByRole('button', { name: lang === 'ko' ? '한국어' : 'English', exact: true }).click();
    for (const section of sections) {
      await page.goto(`${base}/guide/${section}`);
      await page.getByRole('heading', { level: 1 }).waitFor();
      assert.equal(await page.locator('html').getAttribute('lang'), lang);
      assert.equal(await page.locator('.guide-nav a[aria-current="page"]').count(), 1);
      assert.equal(await page.getByRole('group', { name: lang === 'ko' ? '서비스 언어' : 'Service language' }).count(), 1);
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
  await page.goto(`${base}/guide/workflow`);
  await page.getByRole('button', { name: '한국어', exact: true }).click();
  assert.equal(new URL(page.url()).pathname, '/guide/workflow', 'Switching language must not navigate');
  await page.getByRole('button', { name: 'English', exact: true }).click();
  await page.reload();
  await page.getByRole('heading', { name: 'Build evidence throughout development, before final review.' }).waitFor();
  await page.goto(`${base}/guide`);
  await page.waitForURL('**/guide/overview');
  await page.screenshot({ path: `${output}/overview-en-desktop.png`, fullPage: true });
  await page.getByRole('button', { name: '한국어', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: `${output}/overview-ko-mobile.png`, fullPage: true });
  await page.goto(`${base}/guide/workflow`);
  await page.screenshot({ path: `${output}/workflow-ko-mobile.png`, fullPage: true });
  await page.goto(`${base}/guide/unknown`);
  await page.waitForURL('**/guide/overview');
  await page.locator('.guide-nav').getByRole('link', { name: '에이전트와 사람' }).click();
  await page.waitForURL('**/guide/agents');
  await page.goBack();
  await page.waitForURL('**/guide/overview');
  await page.unroute('**/api/**');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('button', { name: 'English', exact: true }).click();
  await page.locator('.global-header').getByRole('link', { name: 'Workspace', exact: true }).click();
  await page.getByRole('heading', { name: 'Project dashboard' }).waitFor();
  await page.getByPlaceholder('Name, process node or foundry').fill('retain my input');
  const projectName = page.locator('input[placeholder="orion-soc"]');
  await projectName.fill('draft-project');
  await page.getByRole('button', { name: '한국어', exact: true }).click();
  await page.getByRole('heading', { name: '프로젝트 대시보드' }).waitFor();
  assert.equal(await page.getByPlaceholder('이름·공정 노드·파운드리').inputValue(), 'retain my input');
  assert.equal(await projectName.inputValue(), 'draft-project', 'Language change must not remount the form');
  await page.getByRole('button', { name: 'English', exact: true }).click();
  await page.reload();
  await page.getByRole('heading', { name: 'Project dashboard' }).waitFor();
  assert.equal(await page.locator('html').getAttribute('lang'), 'en');
  await page.screenshot({ path: `${output}/dashboard-en-desktop.png`, fullPage: true });
  const legacy = { 'rtl-signoff': 'rtl', 'sta-signoff': 'sta', 'ir-drop': 'ir-drop', timing: 'timing', 'glitch-power': 'glitch-power' };
  for (const [hash, slug] of Object.entries(legacy)) {
    await page.goto(`${base}/analysis#${hash}`);
    await page.waitForURL(`**/analysis/${slug}`);
    await page.locator(`[id="${hash}"]`).waitFor();
    assert.equal(await page.locator('[id="rtl-signoff"], [id="sta-signoff"], [id="ir-drop"], [id="timing"], [id="glitch-power"]').count(), 1);
    assert.equal(await page.getByRole('group', { name: 'Service language' }).count(), 1);
    await page.getByRole('link', { name: '← Choose an analysis tool' }).click();
    await page.waitForURL('**/analysis');
    await page.locator('main a.card').first().waitFor();
    assert.equal(await page.locator('main a.card').count(), 5);
  }
  await page.screenshot({ path: `${output}/analysis-tools.png`, fullPage: true });
  await page.route('**/api/auth/session', route => route.fulfill({ json: { mode: 'required', user: null, csrf_token: null, memberships: {} } }));
  await page.goto(base);
  await page.getByRole('heading', { name: 'Sign in to Sign-off Hub' }).waitFor();
  await page.getByRole('textbox', { name: 'Username' }).fill('draft-user');
  await page.getByRole('button', { name: '한국어', exact: true }).click();
  await page.getByRole('heading', { name: 'Sign-off Hub 로그인' }).waitFor();
  assert.equal(await page.getByRole('textbox', { name: '사용자 이름' }).inputValue(), 'draft-user');
  await page.getByRole('link', { name: '서비스 소개 →', exact: true }).click();
  await page.waitForURL('**/guide/overview');
  // Language changes propagate to an already-open tab, without navigating either tab.
  const other = await context.newPage();
  await other.goto(`${base}/guide/start`);
  await other.getByRole('heading', { name: '한 개의 리비전, 한 번의 검증부터.' }).waitFor();
  await page.getByRole('button', { name: 'English', exact: true }).click();
  await other.getByRole('heading', { name: 'Start with one revision and one verification run.' }).waitFor();
  assert.equal(new URL(other.url()).pathname, '/guide/start');
  await other.close();
  // Previously shared language URLs are normalized once and set the shared preference.
  await page.goto(`${base}/guide/en/agents`);
  await page.waitForURL('**/guide/agents');
  await page.getByRole('heading', { name: 'Agents help interpret. People make decisions.' }).waitFor();
  assert.equal(errors.length, 0, errors.join('\n'));
  console.log(JSON.stringify({ result: 'PASS', pages: 10, widths: [1440, 390, 320], checks: ['public without API', 'English guide completeness', 'shared language control and cross-tab sync', 'stable URLs', 'persistence across guide/workspace/login', 'draft preservation', 'history', 'legacy URLs', 'one tool per page'], output }));
} finally { await browser.close(); }
