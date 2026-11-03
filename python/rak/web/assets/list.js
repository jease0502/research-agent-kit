/* 首頁：卡片列表 + 篩選 + 排序 */

const state = { kind: '', tag: '', status: '', sort: 'updated' };
let INDEX = null;

const SORTS = {
  updated: ['__T_web_201__', (a, b) => (b.updated || '').localeCompare(a.updated || '')],
  year:    ['__T_web_202__', (a, b) => (b.year || 0) - (a.year || 0)],
  deg:     ['__T_web_203__', (a, b) => b.deg - a.deg],
  title:   ['__T_web_204__',     (a, b) => displayTitle(a).localeCompare(displayTitle(b), '__HTML_LANG__')],
};

function card(it) {
  const kind = it.kind;
  const bits = [];
  if (kind === 'paper') {
    if (it.year) bits.push(esc(it.year));
    if (it.venue) bits.push(esc(it.venue));
    if (it.authors_short) bits.push(esc(it.authors_short));
    if (it.status) bits.push(esc(it.status));
  } else if (kind === 'concept') {
    if (it.type) bits.push(esc(it.type));
  } else if (it.type) {
    bits.push(esc(it.type));
  }
  if (it.deg) bits.push(`${it.deg}__T_web_205__`);
  // ft 旗標只有「帶著 fulltext-zh/ 建置」的版本才有，Pages 版不會出現這一格
  if (it.ft) bits.push('<span class="ft-mark">__T_web_206__</span>');

  const zh = it.title_zh && it.title_zh !== it.title
    ? `<span class="zh">${esc(it.title_zh)}</span>` : '';

  return `<a class="card" href="${itemHref(it)}" data-status="${esc(it.status || '')}">
    <div class="row1">
      <span class="dot dot-${kind}"></span>
      <span class="title">${esc(it.title)}</span>${zh}
      ${it.todo ? `<span class="todo-badge">${it.todo} TODO</span>` : ''}
    </div>
    ${it.summary ? `<div class="summary">${esc(it.summary)}</div>`
                 : '<div class="summary note">__T_web_207__</div>'}
    <div class="row2">
      <span>${bits.join(' · ')}</span>
      ${(it.tags || []).map((t) => `<span class="chip">${esc(t)}</span>`).join('')}
    </div>
  </a>`;
}

function apply() {
  const list = INDEX.items.filter(
    (it) =>
      (!state.kind || it.kind === state.kind) &&
      (!state.tag || (it.tags || []).includes(state.tag)) &&
      (!state.status || it.status === state.status)
  );
  list.sort(SORTS[state.sort][1]);

  document.getElementById('count').textContent = `${list.length} / ${INDEX.items.length}`;
  document.getElementById('cards').innerHTML =
    list.length ? list.map(card).join('') : '<div class="empty">__T_web_208__</div>';

  document.querySelectorAll('[data-f]').forEach((b) => {
    const [f, v] = b.dataset.f.split(':');
    b.classList.toggle('on', state[f] === v);
  });

  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(state)) if (v && v !== 'updated') p.set(k, v);
  history.replaceState(null, '', p.toString() ? `?${p}` : location.pathname);
}

function chip(field, value, label) {
  return `<button class="chip" data-f="${field}:${value}">${esc(label)}</button>`;
}

function mountFilters() {
  const statuses = [...new Set(INDEX.items.map((i) => i.status).filter(Boolean))].sort();
  const topTags = INDEX.tags.slice(0, 14);

  document.getElementById('filters').innerHTML = `
    ${chip('kind', '', '__T_web_209__')}
    ${['paper', 'concept', 'topic']
      .filter((k) => INDEX.build.counts[k])
      .map((k) => chip('kind', k, `${KINDS[k].label} ${INDEX.build.counts[k]}`))
      .join('')}
    <span class="sep"></span>
    ${statuses.map((s) => chip('status', s, s)).join('')}
    <span class="sep"></span>
    ${topTags.map(([t, n]) => chip('tag', t, `${t} ${n}`)).join('')}
    <span class="sep"></span>
    <select id="sort">${Object.entries(SORTS)
      .map(([k, [label]]) => `<option value="${k}">${label}</option>`)
      .join('')}</select>
    <span class="count" id="count"></span>`;

  document.getElementById('filters').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-f]');
    if (!btn) return;
    const [f, v] = btn.dataset.f.split(':');
    state[f] = state[f] === v ? '' : v; // 再按一次取消
    apply();
  });
  document.getElementById('sort').addEventListener('change', (e) => {
    state.sort = e.target.value;
    apply();
  });
}

(async function main() {
  mountHeader('list');
  try {
    INDEX = await getListIndex();
  } catch (e) {
    return fail(`__T_web_210__${e.message}__T_web_211__`);
  }

  for (const k of ['kind', 'tag', 'status', 'sort']) {
    const v = qs(k);
    if (v) state[k] = v;
  }
  if (!SORTS[state.sort]) state.sort = 'updated';

  mountFilters();
  document.getElementById('sort').value = state.sort;
  apply();
  mountFooter(INDEX.build);
  initSearch(INDEX);
})();
