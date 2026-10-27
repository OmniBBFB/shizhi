// Optional browser integration check against a running server and real BV PDFs.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
const require = createRequire(import.meta.url);
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer-core');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:8766';
const browser = await puppeteer.launch({ executablePath: process.env.CHROME_PATH,
  headless: true, args: process.env.PDF_TEST_NO_SANDBOX === '1' ? ['--no-sandbox'] : [] });
const route = '/?video=BV144nc6KEA4&tab=pdf';
const shotDir = '.artifacts/pdfjs-shots';
await mkdir(shotDir, { recursive: true });
async function ready(page, number) {
  await page.waitForFunction(n => {
    const r = document.querySelector('[data-pdf-url]');
    return r?.dataset.state === 'error' || (r?.dataset.state === 'ready' &&
      (!n || document.querySelector('#pdf-page').value === String(n)));
  }, { timeout: 45000 }, number);
  assert.equal(await page.$eval('[data-pdf-url]', r => r.dataset.state), 'ready',
    await page.$eval('.pdf-status', r => r.textContent));
}
try {
  const page = await browser.newPage();
  const errors = [], external = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error' && !message.location().url?.endsWith('/favicon.ico')) errors.push(message.text()); });
  page.on('request', request => { if (/^https?:/.test(request.url()) && new URL(request.url()).origin !== new URL(base).origin) external.push(request.url()); });
  await page.setViewport({ width: 1280, height: 900 });
  await page.goto(base + route);
  await ready(page, 1);
  assert.equal(await page.$eval('[data-pdf-prev]', button => button.disabled), true);
  assert.ok(await page.$$eval('.textLayer span', spans => spans.length > 20 && /[\u4e00-\u9fff]/.test(spans.map(s => s.textContent).join(''))));
  assert.ok(await page.$eval('canvas', canvas => {
    const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
    let ink = 0;
    for (let i = 0; i < data.length; i += 400) if (data[i] < 200 && data[i+1] < 200 && data[i+2] < 200) ink++;
    return ink > 20;
  }), 'PDF canvas has actual rendered ink');
  await page.click('[data-pdf-next]');
  await ready(page, 2);
  await page.$eval('#pdf-page', input => { input.value = 3; });
  await page.click('[data-pdf-page-form] button');
  await ready(page, 3);
  await page.select('#pdf-zoom', '1.5');
  await page.waitForFunction(() => new URL(location.href).searchParams.get('pdfZoom') === '1.5' && document.querySelector('[data-pdf-url]').dataset.state === 'ready');
  await page.reload();
  await ready(page, 3);
  assert.equal(await page.$eval('#pdf-zoom', el => el.value), '1.5');
  await page.focus('.pdf-viewport');
  await page.keyboard.press('End');
  await page.waitForFunction(() => document.querySelector('[data-pdf-url]').dataset.state === 'ready' && document.querySelector('[data-pdf-next]').disabled);
  await page.focus('.pdf-viewport');
  await page.keyboard.press('Home');
  await ready(page, 1);
  await page.select('#pdf-zoom', 'fit');
  await page.waitForFunction(() => new URL(location.href).searchParams.get('pdfZoom') === 'fit' && document.querySelector('[data-pdf-url]').dataset.state === 'ready');
  await page.$eval('.pdf-reader', el => el.scrollIntoView());
  await page.screenshot({ path: `${shotDir}/desktop.png` });
  await page.setViewport({ width: 375, height: 812 });
  await page.waitForFunction(() => document.querySelector('[data-pdf-url]').dataset.state === 'ready' && parseFloat(document.querySelector('canvas').style.width) <= document.querySelector('.pdf-viewport').clientWidth);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.$eval('.pdf-reader', el => el.scrollIntoView());
  await page.screenshot({ path: `${shotDir}/phone.png` });
  await page.goto(base + '/?video=BV16M4m1m7YP&part=P07&tab=pdf');
  await ready(page, 1);
  assert.ok(await page.$$eval('.textLayer span', spans => spans.length > 0));
  assert.deepEqual(errors, []);
  assert.deepEqual(external, []);
  const failed = await browser.newPage();
  await failed.setRequestInterception(true);
  failed.on('request', request => {
    if (new URL(request.url()).pathname.endsWith('.pdf')) request.respond({ status: 404, body: 'missing' });
    else request.continue();
  });
  await failed.goto(base + route);
  await failed.waitForSelector('[data-pdf-url][data-state="error"]');
  assert.equal(await failed.$eval('[data-pdf-retry]', el => el.hidden), false);
  assert.equal(await failed.$eval('a[download]', el => !!el.href), true);
  const noScript = await browser.newPage();
  await noScript.setJavaScriptEnabled(false);
  await noScript.goto(base + route);
  assert.ok(await noScript.$eval('noscript', el => el.textContent.includes('JavaScript')));
  assert.equal(await noScript.$eval('a[download]', el => !!el.href), true);
  console.log('PASS: Chinese PDF raster/text, prev/next, jump, zoom, URL restore, keyboard bounds, mobile fit, course PDF, local-only requests, load error and no-JS fallback');
} finally {
  await browser.close();
}
