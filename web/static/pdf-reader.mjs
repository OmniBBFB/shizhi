// PDF content stays on the existing read-only BV file endpoint.
const root = document.querySelector('[data-pdf-url]');

async function startReader() {
  const status = root.querySelector('[role="status"]');
  const retry = root.querySelector('[data-pdf-retry]');
  const toolbar = root.querySelector('.pdf-toolbar');
  const viewport = root.querySelector('.pdf-viewport');
  let frame = root.querySelector('.pdf-page');
  const pageInput = root.querySelector('#pdf-page');
  const zoomInput = root.querySelector('#pdf-zoom');
  const previous = root.querySelector('[data-pdf-prev]');
  const next = root.querySelector('[data-pdf-next]');
  const controls = [...toolbar.querySelectorAll('button, input, select')];
  let pdf, pdfjs, displayedPage;
  let rendering = false;
  let pending = false;
  const params = new URL(location.href).searchParams;
  let requestedPage = Math.max(1, Math.trunc(Number(params.get('pdfPage'))) || 1);
  const modes = [...zoomInput.options].map(option => option.value);
  zoomInput.value = modes.includes(params.get('pdfZoom')) ? params.get('pdfZoom') : 'fit';
  let zoom = zoomInput.value;

  function busy(value) {
    root.setAttribute('aria-busy', String(value));
    controls.forEach(control => {
      if (value) {
        // Preserve the appearance of controls disabled only for this redraw;
        // genuine first/last-page boundaries keep their disabled appearance.
        if (!control.disabled) control.dataset.pdfLoadingDisabled = 'true';
        control.disabled = true;
      } else {
        delete control.dataset.pdfLoadingDisabled;
        control.disabled = false;
      }
    });
    if (!value) {
      previous.disabled = requestedPage <= 1;
      next.disabled = requestedPage >= pdf.numPages;
    }
  }

  function fail(error) {
    console.error('PDF.js reader:', error);
    root.dataset.state = 'error';
    root.setAttribute('aria-busy', 'false');
    controls.forEach(control => {
      delete control.dataset.pdfLoadingDisabled;
      control.disabled = true;
    });
    frame.hidden = !displayedPage;
    status.textContent = error?.name === 'PasswordException'
      ? '这份 PDF 需要密码，请下载后打开。'
      : 'PDF 未能加载，请重新加载，或使用下方链接打开原文件。';
    retry.hidden = false;
  }

  // Serialize rendering: PDF.js cannot render twice onto the same canvas.
  async function draw() {
    pending = true;
    if (rendering || !pdf) return;
    rendering = true;
    try {
      while (pending) {
        pending = false;
        const number = requestedPage;
        busy(true);
        root.dataset.state = 'loading';
        if (!displayedPage) status.textContent = `正在绘制第 ${number} 页…`;
        const page = await pdf.getPage(number);
        const natural = page.getViewport({ scale: 1 });
        const available = Math.max(160, viewport.clientWidth - 32);
        const scale = zoom === 'fit' ? available / natural.width : Number(zoom);
        const dimensions = page.getViewport({ scale });
        // Bound raster memory on large pages and high-density mobile screens.
        const density = Math.min(devicePixelRatio || 1, 2,
          Math.sqrt(16_000_000 / (dimensions.width * dimensions.height)));
        // Keep the last painted page on screen. Resize and render only a
        // detached replacement, then commit canvas and text in one DOM swap.
        const replacement = document.createElement('div');
        replacement.className = 'pdf-page';
        const canvas = document.createElement('canvas');
        canvas.setAttribute('aria-hidden', 'true');
        canvas.width = Math.max(1, Math.floor(dimensions.width * density));
        canvas.height = Math.max(1, Math.floor(dimensions.height * density));
        canvas.style.width = `${dimensions.width}px`;
        canvas.style.height = `${dimensions.height}px`;
        replacement.style.width = `${dimensions.width}px`;
        replacement.style.height = `${dimensions.height}px`;
        replacement.style.setProperty('--total-scale-factor', scale);
        replacement.append(canvas);
        const renderTask = page.render({
          canvasContext: canvas.getContext('2d'), viewport: dimensions,
          transform: density === 1 ? null : [density, 0, 0, density, 0, 0],
        });
        await renderTask.promise;
        const text = document.createElement('div');
        text.className = 'textLayer';
        text.setAttribute('role', 'document');
        text.setAttribute('aria-label', `第 ${number} 页文字`);
        replacement.append(text);
        const textLayer = new pdfjs.TextLayer({
          textContentSource: page.streamTextContent(), container: text, viewport: dimensions,
        });
        await textLayer.render();
        const centerX = (viewport.scrollLeft + viewport.clientWidth / 2) / Math.max(1, viewport.scrollWidth);
        const centerY = (viewport.scrollTop + viewport.clientHeight / 2) / Math.max(1, viewport.scrollHeight);
        frame.replaceWith(replacement);
        frame = replacement;
        pageInput.value = number;
        canvas.setAttribute('aria-label', `第 ${number} 页，共 ${pdf.numPages} 页`);
        if (displayedPage === number) {
          viewport.scrollTop = centerY * viewport.scrollHeight - viewport.clientHeight / 2;
          viewport.scrollLeft = centerX * viewport.scrollWidth - viewport.clientWidth / 2;
        } else {
          viewport.scrollTop = 0;
          viewport.scrollLeft = 0;
        }
        displayedPage = number;
        status.textContent = `第 ${number} 页，共 ${pdf.numPages} 页。可选择页面文字。`;
        root.dataset.state = 'ready';
        const address = new URL(location.href);
        address.searchParams.set('pdfPage', number);
        address.searchParams.set('pdfZoom', zoom);
        history.replaceState(null, '', address);
        busy(false);
      }
    } catch (error) {
      fail(error);
    } finally {
      rendering = false;
    }
  }

  function go(number) {
    if (!pdf || rendering) return;
    requestedPage = Math.min(pdf.numPages, Math.max(1, Math.trunc(number) || 1));
    void draw();
  }

  retry.addEventListener('click', () => location.reload());
  previous.addEventListener('click', () => go(requestedPage - 1));
  next.addEventListener('click', () => go(requestedPage + 1));
  root.querySelector('[data-pdf-page-form]').addEventListener('submit', event => {
    event.preventDefault();
    go(pageInput.valueAsNumber);
  });
  zoomInput.addEventListener('change', () => {
    zoom = zoomInput.value;
    void draw();
  });
  viewport.addEventListener('keydown', event => {
    if (event.target !== viewport || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const targets = { ArrowLeft: requestedPage - 1, ArrowRight: requestedPage + 1,
      PageUp: requestedPage - 1, PageDown: requestedPage + 1, Home: 1, End: pdf?.numPages };
    if (event.key in targets) {
      event.preventDefault();
      go(targets[event.key]);
    }
  });

  busy(true);
  root.dataset.state = 'loading';
  try {
    pdfjs = await import('/static/vendor/pdfjs/pdf.min.mjs');
    pdfjs.GlobalWorkerOptions.workerSrc = '/static/vendor/pdfjs/pdf.worker.min.mjs';
    pdf = await pdfjs.getDocument({
      url: root.dataset.pdfUrl,
      cMapUrl: '/static/vendor/pdfjs/cmaps/', cMapPacked: true,
      standardFontDataUrl: '/static/vendor/pdfjs/standard_fonts/',
      wasmUrl: '/static/vendor/pdfjs/wasm/',
      isEvalSupported: false,
    }).promise;
    requestedPage = Math.min(pdf.numPages, requestedPage);
    pageInput.max = pdf.numPages;
    root.querySelector('[data-pdf-total]').textContent = `共 ${pdf.numPages} 页`;
    toolbar.hidden = false;
    viewport.hidden = false;
    await draw();
    let timer;
    let width = viewport.clientWidth;
    new ResizeObserver(() => {
      if (viewport.clientWidth === width) return;
      width = viewport.clientWidth;
      if (zoom !== 'fit') return;
      clearTimeout(timer);
      timer = setTimeout(() => void draw(), 150);
    }).observe(viewport);
  } catch (error) {
    fail(error);
  }
}

if (root) void startReader();
