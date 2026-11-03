/* 詳情頁：paper.html / concept.html / topic.html 共用 */

const TRACK_LABEL = { foundations: '__T_web_099__', 'robot-learning': '__T_web_100__', engineering: '__T_web_101__', 'hands-on': '__T_web_102__' };
const LEVEL_LABEL = { beginner: '__T_web_103__', intermediate: '__T_web_104__', advanced: '__T_web_105__' };

const REL_LABEL = {
  uses: '__T_web_106__', related: '__T_web_107__', is_a: '__T_web_108__',
  includes: '__T_web_109__', covers: '__T_web_110__', mentions: '__T_web_111__',
};

function linkChip(l) {
  return `<a class="chip wl-${l.kind}" href="${itemHref(l)}"
    title="${esc(REL_LABEL[l.rel] || l.rel)}${l.via === 'body' ? '__T_web_112__' : ''}"
    >${esc(displayTitle(l))}</a>`;
}

function dl(pairs) {
  const rows = pairs.filter(([, v]) => v !== undefined && v !== null && v !== '' &&
    !(Array.isArray(v) && !v.length));
  if (!rows.length) return '';
  return `<dl>${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;
}

// 論文原文不進版控（CLAUDE.md §10.7），所以「讀原文」一律外連；
// arXiv 的 HTML 版與 ar5iv 覆蓋的年份不同，兩個都給。
//
// 站內全文（fulltext-zh/ 產生的 data/ft/*.json）是另一回事：它可能有、可能沒有，
// 端看這份 dist/ 是誰建的 —— Pages 的建置抓不到 fulltext-zh/。所以入口只在
// index.json 標了 ft / ften 時才畫出來，不能寫死。
function fulltextBar(kind, meta) {
  if (kind !== 'paper' || (!meta.ft && !meta.ften)) return '';
  const href = (lang) => `fulltext.html?id=${encodeURIComponent(meta.id)}&lang=${lang}`;
  const links = [
    meta.ft && [href('zh'), '__T_web_113__'],
    meta.ften && [href('en'), '__T_web_114__'],
  ].filter(Boolean);
  return `<div class="srcbar srcbar-ft">
    <span class="srcbar-label">__T_web_115__</span>
    ${links.map(([h, label]) => `<a href="${h}">${esc(label)}</a>`).join('')}
    <span class="note">__T_web_116__</span>
  </div>`;
}

function sourceBar(kind, meta) {
  if (kind !== 'paper') return '';
  const a = meta.arxiv;
  const links = [
    a && [`https://arxiv.org/abs/${a}`, '__T_web_117__'],
    a && [`https://arxiv.org/html/${a}`, '__T_web_118__'],
    a && [`https://ar5iv.labs.arxiv.org/html/${a}`, '__T_web_119__'],
    (meta.pdf || (a && `https://arxiv.org/pdf/${a}`)) &&
      [meta.pdf || `https://arxiv.org/pdf/${a}`, 'PDF'],
    !a && meta.url && [meta.url, '__T_web_120__'],
    meta.doi && [`https://doi.org/${meta.doi}`, 'DOI'],
    meta.code && [meta.code, '__T_web_121__'],
  ].filter(Boolean);
  if (!links.length) return '';
  return `<div class="srcbar">
    <span class="srcbar-label">__T_web_122__</span>
    ${links.map(([href, label]) =>
      `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(label)}</a>`).join('')}
  </div>`;
}

function sidebarFor(kind, meta, data) {
  const out = [];

  if (kind === 'paper') {
    const links = [
      meta.url && `<a href="${esc(meta.url)}">__T_web_123__</a>`,
      meta.pdf && `<a href="${esc(meta.pdf)}">PDF</a>`,
      meta.code && `<a href="${esc(meta.code)}">__T_web_124__</a>`,
      meta.doi && `<a href="https://doi.org/${esc(meta.doi)}">DOI</a>`,
    ].filter(Boolean);
    out.push(`<section>${dl([
      ['__T_web_125__', meta.year],
      ['__T_web_126__', esc(meta.venue || '')],
      ['__T_web_127__', esc(meta.status || '')],
      ['__T_web_128__', meta.rating ? '★'.repeat(meta.rating) + '☆'.repeat(5 - meta.rating) : ''],
      ['arXiv', meta.arxiv ? `<a href="https://arxiv.org/abs/${esc(meta.arxiv)}">${esc(meta.arxiv)}</a>` : ''],
      ['__T_web_129__', links.join(' · ')],
    ])}</section>`);

    const authors = data.authors || [];
    if (authors.length) {
      const shown = authors.length > 8 ? authors.slice(0, 8) : authors;
      out.push(`<section><h3>__T_web_130__${authors.length}__T_web_131__</h3>
        <div>${shown.map(esc).join('__T_web_132__')}${
          authors.length > 8 ? `<span class="note">__T_web_133__${authors.length}__T_web_134__</span>` : ''}</div>
      </section>`);
    }
    if (data.bibtex) {
      out.push(`<section><h3>__T_web_135__</h3>
        <button class="copy-btn" id="bib">__T_web_136__</button></section>`);
    }
  } else if (kind === 'lesson') {
    out.push(`<section>${dl([
      ['__T_web_137__', esc(TRACK_LABEL[meta.track] || meta.track || '')],
      ['__T_web_138__', meta.order],
      ['__T_web_139__', esc(LEVEL_LABEL[meta.level] || meta.level || '')],
      ['__T_web_140__', meta.minutes ? `${meta.minutes}__T_web_141__` : ''],
    ])}</section>`);
    if ((meta.prereqs || []).length) {
      out.push(`<section><h3>__T_web_142__</h3><div class="links">${meta.prereqs
        .map((x) => `<a class="chip wl-lesson" href="lesson.html?id=${
          encodeURIComponent(x)}">${esc(x)}</a>`).join('')}</div></section>`);
    }
    out.push('<section><a class="chip" href="learn.html">__T_web_143__</a></section>');
  } else if (kind === 'concept') {
    out.push(`<section>${dl([
      ['__T_web_144__', esc(meta.type || '')],
      ['__T_web_145__', (meta.aliases || []).map(esc).join('__T_web_146__')],
      ['__T_web_147__', (meta.parents || [])
        .map((p) => `<a href="concept.html?id=${encodeURIComponent(p)}">${esc(p)}</a>`)
        .join(' · ')],
    ])}</section>`);
  } else {
    out.push(`<section>${dl([
      ['__T_web_148__', esc(meta.type || '')],
      ['__T_web_149__', esc(meta.status || '')],
    ])}</section>`);
  }

  if ((meta.tags || []).length) {
    out.push(`<section><h3>tags</h3><div class="links">${meta.tags
      .map((t) => `<a class="chip" href="index.html?tag=${encodeURIComponent(t)}">${esc(t)}</a>`)
      .join('')}</div></section>`);
  }

  if (data.outlinks.length) {
    out.push(`<section><h3>__T_web_150__${data.outlinks.length}__T_web_151__</h3>
      <div class="links">${data.outlinks.map(linkChip).join('')}</div></section>`);
  }
  if (data.broken.length) {
    out.push(`<section><h3>__T_web_152__</h3><div class="links">${data.broken
      .map((b) => `<span class="chip broken" title="__T_web_153__">${esc(b)}</span>`)
      .join('')}</div></section>`);
  }

  out.push(`<section><h3>__T_web_154__</h3>
    <canvas class="mini-graph" id="mini" title="__T_web_155__"></canvas>
    <div class="note" id="mini-note"></div></section>`);

  out.push(`<section>${dl([
    ['__T_web_156__', esc(meta.added || '')],
    ['__T_web_157__', esc(meta.updated || '')],
  ])}</section>`);

  return out.join('');
}

function backlinksHtml(list) {
  if (!list.length) return '';
  return `<h2>__T_web_158__${list.length}__T_web_159__</h2>` + list
    .map((b) => `<div class="backlink">
      <span class="dot dot-${b.kind}"></span>
      <a href="${itemHref(b)}">${esc(b.title)}</a>
      <span class="note">· ${esc(REL_LABEL[b.rel] || b.rel)}</span>
      ${b.ctx ? `<div class="ctx">${b.ctx}</div>` : ''}
    </div>`)
    .join('');
}

(async function main() {
  const kind = document.body.dataset.kind;
  const id = qs('id');
  mountHeader(kind === 'lesson' ? 'learn' : 'list');
  if (!id) return fail('__T_web_160__');

  let index, data;
  try {
    [index, data] = await Promise.all([getData('index'), getData(`items/${id}`)]);
  } catch (e) {
    return fail(`__T_web_161__${id}__T_web_162__${e.message}`);
  }
  if (data.kind !== kind) {
    location.replace(itemHref(data)); // 用錯頁面就導到對的那一頁
    return;
  }

  const meta = data.meta;
  document.title = `${displayTitle(meta)} — __SITE_NAME__`;

  // 教材是給學生讀的，中文標題才是主標；論文與概念維持原文標題為主
  const isLesson = kind === 'lesson';
  const h1 = isLesson ? (meta.title_zh || meta.title) : meta.title;
  const sub = isLesson ? (meta.title_zh ? meta.title : '') : meta.title_zh;
  const zh = sub && sub !== h1 ? `<div class="lede">${esc(sub)}</div>` : '';
  const sections = data.sections
    .map((s) => `<h2 id="${esc(s.a)}">${esc(s.h)}</h2>${s.html}`)
    .join('\n');

  document.getElementById('app').innerHTML = `
    <div class="detail">
      <div>
        <div class="row1" style="display:flex;gap:8px;align-items:center">
          <span class="dot dot-${kind}"></span>
          <span class="kind kind-${kind}">${KINDS[kind].label}</span>
          ${meta.todo ? `<span class="todo-badge">${meta.todo}__T_web_163__</span>` : ''}
        </div>
        <h1>${esc(h1)}</h1>
        ${zh}
        ${meta.summary ? `<p class="lede">${esc(meta.summary)}</p>` : ''}
        ${sourceBar(kind, meta)}
        ${fulltextBar(kind, meta)}
        <div class="body">${sections}</div>
        ${backlinksHtml(data.backlinks)}
      </div>
      <aside class="side">${sidebarFor(kind, meta, data)}</aside>
    </div>`;

  wrapTables(document.querySelector('.body'));
  // math.js 只掛在有公式的詳情頁；沒載入就維持原始 TeX，不要讓整頁壞掉
  if (typeof renderMath === 'function') renderMath(document.querySelector('.body'));
  mountFooter(index.build);
  initSearch(index);

  const bib = document.getElementById('bib');
  if (bib) {
    bib.addEventListener('click', async () => {
      await navigator.clipboard.writeText(data.bibtex);
      bib.textContent = '__T_web_164__';
      setTimeout(() => (bib.textContent = '__T_web_165__'), 1600);
    });
  }

  const mini = document.getElementById('mini');
  if (mini && typeof mountMiniGraph === 'function') mountMiniGraph(mini, id);
})();
