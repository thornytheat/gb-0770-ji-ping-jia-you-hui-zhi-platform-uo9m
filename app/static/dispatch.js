const status = document.querySelector('#dispatch-message');

async function post(path,body) {
  const response = await fetch(path, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || '交班提交失败');
  return data;
}

function bind(selector, submit) {
  const form = document.querySelector(selector);
  form?.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    status.textContent = '正在核量…';
    try { await submit(form); }
    catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  });
}

bind('#archive', async form => {
  const files = Object.fromEntries(['tickets','receipts','stock'].map(id => [id,document.getElementById(id).value]));
  const values = Object.values(files);
  if (values.some(Boolean) && !values.every(Boolean)) throw new Error('请填全三份 CSV');
  const sample = form.dataset.sample;
  const ack = await post('/api/shifts', values.every(Boolean) ? files : {sample});
  location.assign('/ops/sign?' + new URLSearchParams({sample,batch:ack.batch}));
});

const pick = document.querySelector('#batch');
const carrier = document.querySelector('#carrier');
const hash = document.querySelector('#checksum');
const exportLink = document.querySelector('#export-slip');

function resetResult() {
  hash.value = '';
  exportLink.hidden = true;
}

// 航司分册只对应归档它的批次：换批次时丢弃不属于该批次的航司选择。
function syncCarrier() {
  const option = carrier?.selectedOptions[0];
  if (option?.value && option.dataset.batch !== pick?.value) carrier.value = '';
}

pick?.addEventListener('change', () => { syncCarrier(); resetResult(); });
carrier?.addEventListener('change', () => {
  if (carrier.value) pick.value = carrier.selectedOptions[0].dataset.batch;
  resetResult();
});

bind('#signature', async () => {
  const batch = pick.value;
  const airline = carrier?.value || '';
  const result = await post(`/api/shifts/${batch}/sign`, airline ? {airline} : {});
  if (pick.value !== batch) return;
  hash.value = result.checksum;
  const scope = result.scope === 'airline' ? `?airline=${encodeURIComponent(result.airline)}` : '';
  exportLink.href = `/api/shifts/${batch}/export${scope}`;
  exportLink.hidden = false;
  const label = result.scope === 'airline' ? `${result.airline} 航司分册` : '整班证据单';
  status.textContent = `${label}已签发 · 待复核 ${result.open_items} 票 · 归属留待核 ${result.held_for_review} 票`;
});
