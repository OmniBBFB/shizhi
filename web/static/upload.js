// The token stays in this form; it is never put in a URL or browser storage.
const form = document.querySelector('#upload-form');
const collection = document.querySelector('#collection');
const title = document.querySelector('#collection-title');
const token = document.querySelector('#upload-token');
const files = document.querySelector('#upload-files');
const queue = document.querySelector('#file-queue');
const status = document.querySelector('#upload-status');
const error = document.querySelector('#upload-error');
const result = document.querySelector('#upload-result');
const rows = new Map();
const complete = new Set();
let busy = false;

collection.addEventListener('change', () => {
  document.querySelector('#new-collection').hidden = !!collection.value;
  title.required = !collection.value;
  title.setAttribute('aria-required', String(title.required));
  complete.clear();
});
document.querySelector('#upload-part').addEventListener('input', () => complete.clear());
files.addEventListener('change', () => {
  queue.replaceChildren();
  rows.clear();
  complete.clear();
  error.textContent = '';
  result.hidden = true;
  document.querySelector('#queue-empty').hidden = files.files.length > 0;
  for (const file of files.files) {
    const item = document.createElement('li');
    const name = document.createElement('span');
    name.textContent = file.name;
    const state = document.createElement('span');
    state.className = 'file-state';
    state.textContent = file.size > 128 * 1024 * 1024 ? '超过 128 MB' : '等待上传';
    item.append(name, state);
    queue.append(item);
    rows.set(file, state);
  }
});

async function request(url, body, contentType) {
  const response = await fetch(url, { method: 'POST', credentials: 'same-origin',
    headers: { Authorization: `Bearer ${token.value}`, 'Content-Type': contentType }, body });
  let data;
  try { data = await response.json(); } catch { throw new Error('服务器未能接收文件，请检查文件大小与网络后重试。'); }
  if (!response.ok) {
    if (response.status === 401) token.setAttribute('aria-invalid', 'true');
    throw new Error(data.error || '上传失败，请重试。');
  }
  return data;
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  const selected = [...files.files];
  error.textContent = '';
  token.removeAttribute('aria-invalid');
  files.removeAttribute('aria-invalid');
  if (selected.some(file => !file.size || file.size > 128 * 1024 * 1024)) {
    files.setAttribute('aria-invalid', 'true');
    error.textContent = '请移除空文件或超过 128 MB 的文件后重试。';
    files.focus();
    return;
  }
  busy = true;
  result.hidden = true;
  const button = document.querySelector('#upload-submit');
  button.disabled = true;
  button.setAttribute('aria-busy', 'true');
  // Freeze target and input selection while preserving their original values.
  const controls = [...form.querySelectorAll('input, select')];
  controls.forEach(control => { control.disabled = true; });
  let active;
  try {
    if (!collection.value) {
      status.textContent = '正在创建资料集…';
      const created = await request('/api/collections', JSON.stringify({ title: title.value.trim() }), 'application/json');
      collection.add(new Option(created.title, created.id));
      collection.value = created.id;
      document.querySelector('#new-collection').hidden = true;
      title.required = false;
    }
    for (let index = 0; index < selected.length; index++) {
      const file = selected[index];
      if (complete.has(file)) continue;
      active = file;
      rows.get(file).textContent = '正在上传';
      status.textContent = `正在上传 ${index + 1} / ${selected.length}：${file.name}`;
      const query = new URLSearchParams({ collection: collection.value,
        part: document.querySelector('#upload-part').value, filename: file.name });
      await request(`/api/uploads?${query}`, file, 'application/octet-stream');
      complete.add(file);
      rows.get(file).textContent = '已上传';
      rows.get(file).dataset.state = 'success';
      active = undefined;
    }
    status.textContent = `已上传 ${complete.size} 份材料。`;
    result.href = `/?${new URLSearchParams({ video: collection.value, part: document.querySelector('#upload-part').value || 'main' })}`;
    result.hidden = false;
  } catch (failure) {
    if (active) { rows.get(active).textContent = '上传失败'; rows.get(active).dataset.state = 'error'; }
    error.textContent = failure.message || '网络中断，请检查连接后重试。';
    status.textContent = `已上传 ${complete.size} / ${selected.length} 份；重试时跳过本轮已完成的文件。`;
  } finally {
    busy = false;
    controls.forEach(control => { control.disabled = false; });
    button.disabled = false;
    button.removeAttribute('aria-busy');
    if (token.getAttribute('aria-invalid') === 'true') token.focus();
  }
});
