// Regression: an already visible PDF must remain painted during redraws.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer-core');
const browser = await puppeteer.launch({ executablePath: process.env.CHROME_PATH,
  headless: true, args: process.env.PDF_TEST_NO_SANDBOX === '1' ? ['--no-sandbox'] : [] });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  await page.goto((process.env.TEST_BASE_URL || 'http://127.0.0.1:8766') + '/?video=BV144nc6KEA4&tab=pdf');
  await page.waitForSelector('[data-pdf-url][data-state="ready"]', { timeout: 45000 });
  // Slow real rendering so a blank paint cannot slip between samples.
  await page.emulateCPUThrottling(4);
  await page.evaluate(() => {
    window.pdfPaintProbe = { blankFrames: 0, frames: 0, stopped: false, redraws: 0 };
    new MutationObserver(records => {
      for (const record of records) {
        if (record.oldValue === 'ready') window.pdfPaintProbe.redraws++;
      }
    }).observe(document.querySelector('[data-pdf-url]'), { attributes: true, attributeFilter: ['data-state'], attributeOldValue: true });
    function sample() {
      const probe = window.pdfPaintProbe;
      const canvas = document.querySelector('.pdf-page canvas');
      if (!canvas || !canvas.getBoundingClientRect().width || !canvas.getBoundingClientRect().height || !canvas.getContext('2d').getImageData(0, 0, 1, 1).data[3]) probe.blankFrames++;
      probe.frames++;
      if (!probe.stopped) requestAnimationFrame(sample);
    }
    requestAnimationFrame(sample);
  });
  await page.click('[data-pdf-next]');
  await page.waitForFunction(() => document.querySelector('[data-pdf-url]').dataset.state === 'ready' && document.querySelector('#pdf-page').value === '2');
  const idleRedraws = await page.evaluate(async () => {
    const before = window.pdfPaintProbe.redraws;
    await new Promise(resolve => setTimeout(resolve, 800));
    return window.pdfPaintProbe.redraws - before;
  });
  await page.waitForSelector('[data-pdf-url][data-state="ready"]');
  await page.select('#pdf-zoom', '1');
  await page.waitForFunction(() => document.querySelector('[data-pdf-url]').dataset.state === 'ready' && new URL(location.href).searchParams.get('pdfZoom') === '1');
  await page.select('#pdf-zoom', 'fit');
  await page.waitForFunction(() => document.querySelector('[data-pdf-url]').dataset.state === 'ready' && new URL(location.href).searchParams.get('pdfZoom') === 'fit');
  await page.setViewport({ width: 1000, height: 900 });
  await page.waitForFunction(() => {
    const v = document.querySelector('.pdf-viewport');
    return document.querySelector('[data-pdf-url]').dataset.state === 'ready' && Math.abs(parseFloat(document.querySelector('.pdf-page').style.width) - (v.clientWidth - 32)) < 1;
  });
  const result = await page.evaluate(() => { window.pdfPaintProbe.stopped = true; return window.pdfPaintProbe; });
  console.log(JSON.stringify({ ...result, idleRedraws }));
  assert.equal(result.blankFrames, 0, 'PDF disappeared during page/zoom redraw');
  assert.equal(idleRedraws, 0, 'Fit-width redraw loops without user input');
  console.log('PASS: no blank PDF frames during page and zoom changes');
} finally {
  await browser.close();
}
