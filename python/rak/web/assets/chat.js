/* 問答介面。把問題送到本機的 /api/ask，SSE 串回答案。
 *
 * 這個頁面只存在於本機預覽（build.py 預設不把它放進 dist/），
 * 因為 /api/ask 會用使用者輸入啟動一個本機行程。
 */

let busy = false;

function bubble(cls, html) {
  const n = el('div', { class: `msg ${cls}` }, html);
  document.getElementById('thread').appendChild(n);
  n.scrollIntoView({ block: 'end', behavior: 'smooth' });
  return n;
}

async function checkHealth() {
  const box = document.getElementById('status');
  try {
    const r = await fetch('api/health');
    if (!r.ok) throw new Error(String(r.status));
    const s = await r.json();
    if (s.ok) {
      box.innerHTML = `__T_web_031__<code>${esc(s.cmd)}</code>`;
      return true;
    }
    box.innerHTML = `<span class="broken">${esc(s.hint)}</span>`;
    return false;
  } catch {
    box.innerHTML =
      '<span class="broken">__T_web_032__<code>python scripts/build.py --serve</code>__T_web_033__</span>';
    return false;
  }
}

async function ask(question) {
  if (busy) return;
  busy = true;
  document.getElementById('send').disabled = true;

  bubble('me', esc(question).replace(/\n/g, '<br>'));
  const out = bubble('bot', '<span class="note" id="tools">__T_web_034__</span><div class="raw"></div>');
  const tools = out.querySelector('#tools');
  const raw = out.querySelector('.raw');
  let text = '';

  // 第一段文字通常要等 10–30 秒（CLI 要先 grep、再讀命中的段落）。沒有計時器的話，
  // 靜止的「思考中…」跟當掉長得一模一樣 —— 實測時使用者就是這樣等了三分半才離開。
  const t0 = Date.now();
  let step = '__T_web_035__';
  const tick = setInterval(() => {
    if (!tools.isConnected) return clearInterval(tick);
    const s = Math.round((Date.now() - t0) / 1000);
    tools.textContent = step + '… ' + s + 's' +
      (s > 90 ? '__T_web_036__' : '');
  }, 1000);

  try {
    const r = await fetch('api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ q: question }),
    });
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = '';

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const chunks = buf.split('\n\n');
      buf = chunks.pop();
      for (const c of chunks) {
        const line = c.split('\n').find((l) => l.startsWith('data: '));
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line.slice(6)); } catch { continue; }

        if (ev.type === 'tool') {
          step = `__T_web_037__${ev.name}`;
        } else if (ev.type === 'delta') {
          text += ev.text;
          step = '__T_web_038__';
          // 串流時先顯示純文字；完成後再換成渲染好的 HTML
          raw.textContent = text;
          out.scrollIntoView({ block: 'end' });
        } else if (ev.type === 'done') {
          tools.remove();
          raw.outerHTML = `<div class="body">${ev.html}</div>`;
          wrapTables(out);
          if (typeof renderMath === 'function') renderMath(out);
        } else if (ev.type === 'error') {
          tools.remove();
          raw.outerHTML = `<div class="broken">${esc(ev.message)}</div>`;
        }
      }
    }
  } catch (e) {
    tools.remove();
    raw.outerHTML = `<div class="broken">__T_web_039__${esc(e.message)}</div>`;
  } finally {
    clearInterval(tick);
    busy = false;
    document.getElementById('send').disabled = false;
    document.getElementById('askq').focus();
  }
}

(async function main() {
  mountHeader('chat');
  let index;
  try {
    index = await getData('index');
    mountFooter(index.build);
    initSearch(index);
  } catch { /* 問答不依賴 index.json，讀不到就算了 */ }

  await checkHealth();

  const form = document.getElementById('ask');
  // 這裡一定要用 askq 而不是 q：頁首的搜尋框就是 id="q"，
  // getElementById 會回傳文件順序中的第一個（頁首在 main 前面）。
  // 撞名時這裡讀到的是搜尋框，永遠是空的 —— 送出就會靜靜跳出，看起來像按鈕壞掉。
  const box = document.getElementById('askq');
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const q = box.value.trim();
    if (!q) {
      // 靜靜 return 是上一版真正的病灶。任何不送出的情況都要說出理由。
      document.getElementById('status').innerHTML =
        '<span class="broken">__T_web_040__</span>';
      box.focus();
      return;
    }
    ask(q);
    box.value = '';
  });
  box.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) form.requestSubmit();
  });
  box.focus();
})();
