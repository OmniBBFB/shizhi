// Progressive enhancement: every navigation and reading action works without JS.
document.querySelectorAll('form:not([data-pdf-page-form])').forEach(form => {
  form.addEventListener('submit', () => {
    const status = form.querySelector('[role="status"]');
    if (status) status.hidden = false;
    const button = form.querySelector('button');
    if (button) button.setAttribute('aria-busy', 'true');
  });
});
window.addEventListener('pageshow', () => {
  document.querySelectorAll('[aria-busy]').forEach(el => el.removeAttribute('aria-busy'));
  document.querySelectorAll('.loading').forEach(el => { el.hidden = true; });
});
