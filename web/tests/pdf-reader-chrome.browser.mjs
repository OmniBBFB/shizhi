// Regression: navigation must not dim the whole toolbar or shift the page area.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer-core');
const browser = await puppeteer.launch({ executablePath: process.env.CHROME_PATH,
  headless: true, args: process.env.PDF_TEST_NO_SANDBOX === '1' ? ['--no-sandbox'] : [] });
try {
 for (const width of [1280, 375]) {
  const page = await browser.newPage();
  await page.setViewport({ width, height: 900 });
  await page.goto((process.env.TEST_BASE_URL || 'http://127.0.0.1:8766') + '/?video=BV144nc6KEA4&tab=pdf&pdfPage=2');
  await page.waitForSelector('[data-pdf-url][data-state="ready"]', { timeout: 45000 });
  await page.emulateCPUThrottling(4);
  await page.evaluate(() => {
    const button = document.querySelector('#pdf-zoom');
    const viewport = document.querySelector('.pdf-viewport');
    const initial = { opacity: getComputedStyle(button).opacity, top: viewport.getBoundingClientRect().top };
    window.pdfChromeProbe = { dimmedFrames: 0, shiftedFrames: 0, frames: 0, stopped: false, intermediateMessages: 0 };
    const initialMessage = document.querySelector('.pdf-status').textContent;
    function sample() {
      const p = window.pdfChromeProbe;
      if (getComputedStyle(button).opacity !== initial.opacity) p.dimmedFrames++;
      if (Math.abs(viewport.getBoundingClientRect().top - initial.top) > 1) p.shiftedFrames++;
      if (document.querySelector('[data-pdf-url]').dataset.state === 'loading' && document.querySelector('.pdf-status').textContent !== initialMessage) p.intermediateMessages++;
      p.frames++;
      if (!p.stopped) requestAnimationFrame(sample);
    }
    requestAnimationFrame(sample);
  });
  // DOM click avoids Puppeteer's automatic outer-page scrolling.
  await page.$eval('[data-pdf-next]', button => button.click());
  await page.waitForFunction(() => document.querySelector('[data-pdf-url]').dataset.state === 'ready' && document.querySelector('#pdf-page').value === '3');
  const result = await page.evaluate(() => { window.pdfChromeProbe.stopped = true; return window.pdfChromeProbe; });
  console.log(JSON.stringify({ width, ...result }));
  assert.equal(result.dimmedFrames, 0, 'Toolbar visibly dims on every page turn');
  assert.equal(result.shiftedFrames, 0, 'PDF viewport jumps on page turn');
  assert.equal(result.intermediateMessages, 0, 'Status text flashes a transient message on page turn');
  console.log('PASS: stable toolbar appearance and PDF viewport during page turn');
  await page.close();
 }
} finally { await browser.close(); }
