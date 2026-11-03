/* 共用：資料抓取、header、小工具。所有頁面都先載這一支。 */

// build.py 會把下面字串裡的佔位符換成 commit SHA。
// 注意：佔位符只能出現在「字串值」位置 —— 它曾經也被當成變數名，
// 而 SHA 有 62.5% 機率以數字開頭，那會產生「window.<以數字開頭的SHA> = ...」
// 這種語法錯誤，整個 inline script 掛掉、BUILD 沒定義、頁面卡在「載入中…」。
// build.py 的 _assert_build_id_safe() 現在會擋下這種情況。
// 每一個 fetch 都必須帶上它 —— GitHub Pages 走 Fastly，max-age=600，
// 少帶一個就會出現「新的 index.json 配舊的 search.json」這種混版狀態。
const BUILD = window.RAK_BUILD || 'dev';

const KINDS = {
  paper:   { label: '__T_web_041__', page: 'paper.html',   char: 'p' },
  concept: { label: '__T_web_042__', page: 'concept.html', char: 'c' },
  topic:   { label: '__T_web_043__', page: 'topic.html',   char: 't' },
  lesson:  { label: '__T_web_044__', page: 'lesson.html',  char: 'l' },
};
const KIND_OF_CHAR = { p: 'paper', c: 'concept', t: 'topic', l: 'lesson' };

const _cache = new Map();

async function getData(name) {
  if (!_cache.has(name)) {
    _cache.set(name, fetch(`data/${name}.json?v=${BUILD}`).then((r) => {
      if (!r.ok) throw new Error(`data/${name}.json → ${r.status}`);
      return r.json();
    }));
  }
  return _cache.get(name);
}

// index.json 只有核心欄位（id／kind／title／title_zh／status／type），清單要的 summary、tags、deg……在 list.json。
// 清單、圖、教材目錄用這個：兩個一起抓、依 id 合併，回傳的物件跟以前的 index.json 同形狀。
// 單一項目的頁面不要用它 —— 那些欄位在 items/<id>.json 的 meta 裡都有。
let _listIndex = null;
function getListIndex() {
  if (!_listIndex) {
    _listIndex = Promise.all([getData('index'), getData('list')]).then(([index, list]) => {
      if (list.build !== index.build.id) {
        throw new Error(`__T_web_045__${index.build.id}__T_web_046__${list.build}__T_web_047__`);
      }
      const extra = new Map(list.items.map((it) => [it.id, it]));
      return { ...index, items: index.items.map((it) => ({ ...it, ...extra.get(it.id) })) };
    });
  }
  return _listIndex;
}

const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const qs = (k) => new URLSearchParams(location.search).get(k);

function el(tag, attrs = {}, html = '') {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') n.className = v;
    else n.setAttribute(k, v);
  }
  if (html) n.innerHTML = html;
  return n;
}

function itemHref(item) {
  const kind = item.kind || KIND_OF_CHAR[item.k];
  return `${KINDS[kind].page}?id=${encodeURIComponent(item.id)}`;
}

function displayTitle(item) {
  return item.title_zh || item.title || item.id;
}

/* ---------------- header ---------------- */

function mountHeader(active) {
  const host = document.getElementById('hdr');
  if (!host) return;
  const nav = [
    ['learn.html', 'learn', '__T_web_048__'],
    ['index.html', 'list', '__T_web_049__'],
    ['graph.html', 'graph', '__T_web_050__'],
  ];
  host.outerHTML = `
    <header class="site">
      <a class="brand" href="index.html">__SITE_NAME__</a>
      <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="site-nav"
              aria-label="__T_web_051__"><span></span><span></span><span></span></button>
      <nav id="site-nav">${nav
        .map(([h, k, t]) => `<a href="${h}" class="${k === active ? 'on' : ''}">${t}</a>`)
        .join('')}</nav>
      <div class="search-wrap">
        <input id="q" type="search" autocomplete="off" spellcheck="false"
               placeholder="__T_web_052__" aria-label="__T_web_053__">
        <span class="hint">/</span>
        <div class="results" id="results"></div>
      </div>
      <span id="whoami"></span>
    </header>`;

  mountWhoami();
  mountChatLink(active);
  mountNavToggle();

  document.addEventListener('keydown', (e) => {
    const input = document.getElementById('q');
    const ae = document.activeElement;
    const typing = ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' ||
      ae.isContentEditable);
    if (e.key === '/' && input && !typing && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      input.focus();
      input.select();
    }
  });
}

/* 手機版的導覽收在按鈕後面（寬螢幕時按鈕被 CSS 藏起來，這段不影響桌面版）。
   問答入口是之後才 append 進 nav 的，因為收合的是整個 nav，它自然跟著。 */
function mountNavToggle() {
  const hdr = document.querySelector('header.site');
  const btn = hdr && hdr.querySelector('.nav-toggle');
  if (!btn) return;
  const set = (open) => {
    hdr.classList.toggle('nav-open', open);
    btn.setAttribute('aria-expanded', String(open));
  };
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    set(!hdr.classList.contains('nav-open'));
  });
  document.addEventListener('click', (e) => {
    if (!e.target.closest('header.site')) set(false);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') set(false);
  });
}

/* 登入層是「有就用、沒有就當作不存在」。
   Cloud Run 版有 /api/me；GitHub Pages 版沒有這支，會 404 或被靜態伺服器
   回一頁 HTML —— 兩種都要靜靜略過，不能把頁首弄壞或在 console 噴錯。 */
async function mountWhoami() {
  const host = document.getElementById('whoami');
  if (!host) return;
  let me;
  try {
    const r = await fetch('api/me', { headers: { Accept: 'application/json' } });
    if (!r.ok) return;
    me = await r.json();
  } catch {
    return;
  }
  if (!me || !me.email) return;
  const admin = me.role === 'superadmin'
    ? '<a href="admin">__T_web_054__</a>' : '';
  host.outerHTML = `<span class="whoami">
      <span class="who" title="${esc(me.email)}">${esc(me.name || me.email)}</span>
      ${admin}<a href="logout">__T_web_055__</a>
    </span>`;
}

/* 問答只存在於本機預覽（build.py 預設不把 chat.html 放進 dist/），
   所以用 /api/health 探測後才把入口加上去 —— 部署版上不會出現一個死連結。*/
async function mountChatLink(active) {
  try {
    const r = await fetch('api/health', { cache: 'no-store' });
    if (!r.ok) return;
  } catch {
    return;
  }
  const nav = document.querySelector('.site nav');
  if (!nav || nav.querySelector('[data-chat]')) return;
  const a = el('a', { href: 'chat.html', 'data-chat': '1',
                      class: active === 'chat' ? 'on' : '' }, '__T_web_056__');
  nav.appendChild(a);
}

function mountFooter(build) {
  const f = document.getElementById('ftr');
  if (!f) return;
  const n = build?.counts || {};
  const parts = [
    `__T_web_057__${n.paper || 0}__T_web_058__${n.concept || 0}__T_web_059__${n.topic || 0}` + (n.lesson ? `__T_web_060__${n.lesson}` : ''),
    build?.broken ? `__T_web_061__${build.broken}` : '',
    `build ${build?.id || BUILD}`,
    // rak.toml 沒給 source_url 時建置會換成空字串，這一項就被 filter 掉
    '__SOURCE_URL__' ? '<a href="__SOURCE_URL__">__T_web_062__</a>' : '',
  ].filter(Boolean);
  f.outerHTML = `<footer>${parts.map((p) => `<span>${p}</span>`).join('')}</footer>`;
}

function fail(msg) {
  const app = document.getElementById('app');
  if (app) app.innerHTML = `<div class="empty">${esc(msg)}</div>`;
}

/* 表格在窄螢幕要能自己橫向捲，不能讓整個 body 橫捲 */
function wrapTables(root) {
  root.querySelectorAll('table').forEach((t) => {
    if (t.parentElement.classList.contains('table-wrap')) return;
    const w = el('div', { class: 'table-wrap' });
    t.replaceWith(w);
    w.appendChild(t);
  });
}
