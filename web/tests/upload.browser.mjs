// Optional browser integration check against a disposable writable library.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
const require = createRequire(import.meta.url);
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer-core');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:18766';
const env = await readFile(process.env.UPLOAD_ENV || '.env', 'utf8');
const secret = env.split('\n').find(line => line.startsWith('SHIZHI_UPLOAD_TOKEN=')).split('=').slice(1).join('=');
const artifacts = '.artifacts/upload';
await mkdir(artifacts, { recursive: true });
const file = `${artifacts}/测试笔记.md`;
await writeFile(file, '# 浏览器上传检查\n上传后立刻可以阅读。\n');
const browser = await puppeteer.launch({ executablePath: process.env.CHROME_PATH, headless: true });
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', failure => errors.push(failure.message));
  await page.setViewport({ width: 1280, height: 800 });
  await page.goto(base + '/upload');
  await page.type('#collection-title', '上传端到端检查');
  await page.type('#upload-token', 'wrong');
  await (await page.$('#upload-files')).uploadFile(file);
  await page.click('#upload-submit');
  await page.waitForFunction(() => document.querySelector('#upload-error').textContent.includes('口令不正确'));
  assert.equal(await page.$eval('#upload-token', element => element.getAttribute('aria-invalid')), 'true');
  assert.equal(await page.$eval('#upload-submit', element => element.disabled), false);
  await page.$eval('#upload-token', (element, token) => { element.value = token; }, secret);
  await page.click('#upload-submit');
  await page.waitForSelector('#upload-result:not([hidden])');
  assert.equal(await page.$eval('.file-state', element => element.textContent), '已上传');
  const href = await page.$eval('#upload-result', element => element.getAttribute('href'));
  assert.ok(new URL(href, base).searchParams.get('video').startsWith('kb-'));
  assert.equal(await page.evaluate(() => Object.keys(localStorage).length + Object.keys(sessionStorage).length), 0);
  await page.screenshot({ path: `${artifacts}/success-desktop.png`, fullPage: true });
  await page.click('#upload-result');
  await page.waitForSelector('.prose');
  assert.ok(await page.$eval('.prose', element => element.textContent.includes('上传后立刻可以阅读')));
  assert.equal(await page.$$eval('.reader-head a', links => links.some(link => link.textContent.includes('观看原视频'))), false);
  await page.goto(base + '/upload');
  for (const width of [320, 375, 720, 1280, 1920]) {
    await page.setViewport({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `overflow at ${width}`);
  }
  await page.setViewport({ width: 375, height: 812 });
  await page.screenshot({ path: `${artifacts}/phone.png`, fullPage: true });
  assert.deepEqual(errors, []);
  console.log('PASS: wrong-token recovery, create collection, real upload, immediate public reading, no token storage, 320–1920px layout');
} finally {
  await browser.close();
}
