import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
const { chromium } = await import(process.env.SIGNOFF_PLAYWRIGHT_MODULE);
const fixture = JSON.parse(await readFile(process.env.SIGNOFF_AUTH_FIXTURE, 'utf8'));
const base = process.env.SIGNOFF_TEST_UI;
assert.equal(new URL(base).hostname, '127.0.0.1');
assert.equal(new URL(base).port, '15174');
const output = '/private/tmp/signoff-source-export-check';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const login = await context.request.post(`${base}/api/auth/login`, { headers: { 'X-Signoff-Client': '1' }, data: { username: 'qa-editor', password: fixture.password } });
  assert.equal(login.status(), 200);
  const session = await (await context.request.get(`${base}/api/auth/session`)).json();
  const source = '\ufeff{\r\n  "checks": [], "note": "한글 원본 µW"\r\n}\r\n';
  const response = await context.request.post(`${base}/api/projects/${fixture.project}/imports/opensta`, { headers: { 'X-CSRF-Token': session.csrf_token }, data: { import_id: randomUUID(), stage: 'placement', filename: 'original.json', tool_version: 'QA', design_revision: 'source-test', scenario: 'test', source_text: source } });
  assert.equal(response.status(), 201);
  const run = await response.json();
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(`${base}/runs/${run.id}/paths`);
  await page.getByRole('button', { name: '실행 근거 보기', exact: true }).click();
  const panel = page.getByRole('region', { name: `런 #${run.id} 실행 근거`, exact: true });
  const button = panel.getByRole('button', { name: '원본 파일 다운로드', exact: true });
  let downloads = 0;
  page.on('download', () => downloads++);
  async function download() {
    const event = page.waitForEvent('download');
    await button.click();
    const file = await event;
    assert.equal(file.suggestedFilename(), `run-${run.id}-source.json`);
    const bytes = await readFile(await file.path());
    assert.deepEqual(bytes, Buffer.from(source, 'utf8'));
    const digest = createHash('sha256').update(bytes).digest('hex');
    const evidence = await (await context.request.get(`${base}/api/runs/${run.id}/evidence`)).json();
    assert.equal(digest, evidence.source_sha256);
    await panel.getByRole('status').waitFor();
  }
  await download();
  await page.route(`**/api/runs/${run.id}/evidence/source`, route => route.fulfill({ status: 409, json: { detail: '저장된 원본과 SHA-256이 일치하지 않습니다. 원본 근거를 확인하세요.' } }), { times: 1 });
  const before = downloads;
  await button.click();
  await panel.getByRole('alert').waitFor();
  assert.equal(downloads, before);
  assert.equal(await panel.getByRole('status').count(), 0);
  await download();
  for (const width of [390, 320, 1440]) {
    await page.setViewportSize({ width, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (width === 390) await page.screenshot({ path: `${output}/source-export-mobile.png`, fullPage: true });
  }
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ result: 'PASS', output, checks: ['exact UTF-8 BOM CRLF bytes', 'hash matches captured evidence', '409 produces no file', 'retry clears error', '320/390/1440 layout'] }));
} finally { await browser.close(); }
