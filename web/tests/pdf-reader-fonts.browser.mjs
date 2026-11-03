// Regression: embedded fonts must survive missing modern APIs in the worker.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createRequire } from 'node:module';
import { copyFile, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { createInterface } from 'node:readline';

const require = createRequire(import.meta.url);
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer-core');
const cwd = fileURLToPath(new URL('../../', import.meta.url));
let browser, server, temporary;
let base = process.env.TEST_BASE_URL;
const route = process.env.TEST_PDF_ROUTE || (base
  ? '/?video=BV1Guxu6EERa&pdfPage=3&pdfZoom=fit'
  : '/?video=kb-fonts&tab=pdf');

try {
  if (!base) {
    temporary = await mkdtemp(join(tmpdir(), 'shizhi-fonts-'));
    await mkdir(join(temporary, 'kb-fonts'));
    await copyFile(new URL('./fixtures/embedded-serif.pdf', import.meta.url),
      join(temporary, 'kb-fonts', 'embedded-serif.pdf'));
    server = spawn(process.env.PYTHON || 'python3',
      ['-u', '-m', 'web.controller', '--root', temporary, '--port', '0'],
      { cwd, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, SHIZHI_UPLOAD_TOKEN: '' } });
    let stderr = '';
    server.stderr.on('data', chunk => { stderr += chunk; });
    const lines = createInterface({ input: server.stdout });
    try {
      base = await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('Test server did not start')), 10000);
        server.once('error', error => { clearTimeout(timer); reject(error); });
        server.once('exit', code => {
          clearTimeout(timer);
          reject(new Error(`Test server exited ${code}: ${stderr}`));
        });
        lines.on('line', line => {
          const url = line.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0];
          if (url) { clearTimeout(timer); resolve(url); }
        });
      });
    } finally { lines.close(); }
  }
  browser = await puppeteer.launch({ executablePath: process.env.CHROME_PATH,
    headless: true, args: process.env.PDF_TEST_NO_SANDBOX === '1' ? ['--no-sandbox'] : [] });
  const page = await browser.newPage();
  const warnings = [], failures = [];
  let workerPatched = false;
  page.on('console', message => {
    if (['warn', 'error'].includes(message.type()) &&
        !message.location().url?.endsWith('/favicon.ico')) warnings.push(message.text());
  });
  page.on('pageerror', error => failures.push(error.message));
  await page.setRequestInterception(true);
  page.on('request', async request => {
    try {
      if (new URL(request.url()).pathname.endsWith('/pdf.worker.min.mjs')) {
        const response = await fetch(request.url());
        assert.ok(response.ok, `Worker HTTP ${response.status}`);
        const body = Buffer.from(await response.arrayBuffer());
        // Force the original failure even on browsers that now support this API.
        await request.respond({ status: 200, contentType: 'text/javascript',
          body: Buffer.concat([Buffer.from('Math.sumPrecise = undefined;\n'), body]) });
        workerPatched = true;
      } else await request.continue();
    } catch (error) {
      failures.push(error.message);
      await request.abort();
    }
  });
  await page.goto(base + route, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('[data-pdf-url][data-state="ready"]', { timeout: 45000 });
  const fonts = await page.evaluate(() => [...document.fonts]
    .filter(font => /^g_d\d+_f\d+$/.test(font.family))
    .map(font => ({ family: font.family, status: font.status })));
  assert.ok(workerPatched, 'The test must exercise a worker without Math.sumPrecise');
  assert.deepEqual(failures, []);
  assert.deepEqual(warnings, [], 'PDF.js warned while loading or rendering embedded fonts');
  assert.ok(fonts.length > 0, 'PDF.js substituted system fonts for embedded fonts');
  assert.ok(fonts.every(font => font.status === 'loaded'), 'Embedded font failed to load');
  console.log(`PASS: ${fonts.length} embedded fonts loaded with Math.sumPrecise absent in worker`);
} finally {
  if (browser) await browser.close();
  if (server && server.exitCode === null) {
    const exited = once(server, 'exit');
    server.kill();
    await exited;
  }
  if (temporary) await rm(temporary, { recursive: true, force: true });
}
