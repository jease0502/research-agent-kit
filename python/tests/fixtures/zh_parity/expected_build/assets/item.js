/* 詳情頁：paper.html / concept.html / topic.html 共用 */

const TRACK_LABEL = { foundations: '基礎軌', 'robot-learning': '機器人學習軌', engineering: '自建軌', 'hands-on': '實作軌' };
const LEVEL_LABEL = { beginner: '入門', intermediate: '中階', advanced: '進階' };

const REL_LABEL = {
  uses: '使用', related: '相關', is_a: '屬於',
  includes: '收錄', covers: '涵蓋', mentions: '提到',
};

function linkChip(l) {
  return `<a class="chip wl-${l.kind}" href="${itemHref(l)}"
    title="${esc(REL_LABEL[l.rel] || l.rel)}${l.via === 'body' ? '（內文提到）' : ''}"
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
    meta.ft && [href('zh'), '全文中文'],
    meta.ften && [href('en'), '英文原文'],
  ].filter(Boolean);
  return `<div class="srcbar srcbar-ft">
    <span class="srcbar-label">站內全文</span>
    ${links.map(([h, label]) => `<a href="${h}">${esc(label)}</a>`).join('')}
    <span class="note">中文為機器翻譯，引用前請以原文為準</span>
  </div>`;
}

function sourceBar(kind, meta) {
  if (kind !== 'paper') return '';
  const a = meta.arxiv;
  const links = [
    a && [`https://arxiv.org/abs/${a}`, 'arXiv 摘要頁'],
    a && [`https://arxiv.org/html/${a}`, 'HTML 全文'],
    a && [`https://ar5iv.labs.arxiv.org/html/${a}`, 'ar5iv 全文'],
    (meta.pdf || (a && `https://arxiv.org/pdf/${a}`)) &&
      [meta.pdf || `https://arxiv.org/pdf/${a}`, 'PDF'],
    !a && meta.url && [meta.url, '原文連結'],
    meta.doi && [`https://doi.org/${meta.doi}`, 'DOI'],
    meta.code && [meta.code, '程式碼'],
  ].filter(Boolean);
  if (!links.length) return '';
  return `<div class="srcbar">
    <span class="srcbar-label">讀原文</span>
    ${links.map(([href, label]) =>
      `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(label)}</a>`).join('')}
  </div>`;
}

function sidebarFor(kind, meta, data) {
  const out = [];

  if (kind === 'paper') {
    const links = [
      meta.url && `<a href="${esc(meta.url)}">來源</a>`,
      meta.pdf && `<a href="${esc(meta.pdf)}">PDF</a>`,
      meta.code && `<a href="${esc(meta.code)}">程式碼</a>`,
      meta.doi && `<a href="https://doi.org/${esc(meta.doi)}">DOI</a>`,
    ].filter(Boolean);
    out.push(`<section>${dl([
      ['年份', meta.year],
      ['發表', esc(meta.venue || '')],
      ['狀態', esc(meta.status || '')],
      ['評分', meta.rating ? '★'.repeat(meta.rating) + '☆'.repeat(5 - meta.rating) : ''],
      ['arXiv', meta.arxiv ? `<a href="https://arxiv.org/abs/${esc(meta.arxiv)}">${esc(meta.arxiv)}</a>` : ''],
      ['連結', links.join(' · ')],
    ])}</section>`);

    const authors = data.authors || [];
    if (authors.length) {
      const shown = authors.length > 8 ? authors.slice(0, 8) : authors;
      out.push(`<section><h3>作者（${authors.length}）</h3>
        <div>${shown.map(esc).join('、')}${
          authors.length > 8 ? `<span class="note"> 等 ${authors.length} 人</span>` : ''}</div>
      </section>`);
    }
    if (data.bibtex) {
      out.push(`<section><h3>引用</h3>
        <button class="copy-btn" id="bib">複製 BibTeX</button></section>`);
    }
  } else if (kind === 'lesson') {
    out.push(`<section>${dl([
      ['軌道', esc(TRACK_LABEL[meta.track] || meta.track || '')],
      ['第幾課', meta.order],
      ['程度', esc(LEVEL_LABEL[meta.level] || meta.level || '')],
      ['預估', meta.minutes ? `${meta.minutes} 分鐘` : ''],
    ])}</section>`);
    if ((meta.prereqs || []).length) {
      out.push(`<section><h3>先讀這些</h3><div class="links">${meta.prereqs
        .map((x) => `<a class="chip wl-lesson" href="lesson.html?id=${
          encodeURIComponent(x)}">${esc(x)}</a>`).join('')}</div></section>`);
    }
    out.push('<section><a class="chip" href="learn.html">← 回課程總覽</a></section>');
  } else if (kind === 'concept') {
    out.push(`<section>${dl([
      ['類型', esc(meta.type || '')],
      ['別名', (meta.aliases || []).map(esc).join('、')],
      ['上位概念', (meta.parents || [])
        .map((p) => `<a href="concept.html?id=${encodeURIComponent(p)}">${esc(p)}</a>`)
        .join(' · ')],
    ])}</section>`);
  } else {
    out.push(`<section>${dl([
      ['類型', esc(meta.type || '')],
      ['狀態', esc(meta.status || '')],
    ])}</section>`);
  }

  if ((meta.tags || []).length) {
    out.push(`<section><h3>tags</h3><div class="links">${meta.tags
      .map((t) => `<a class="chip" href="index.html?tag=${encodeURIComponent(t)}">${esc(t)}</a>`)
      .join('')}</div></section>`);
  }

  if (data.outlinks.length) {
    out.push(`<section><h3>連到（${data.outlinks.length}）</h3>
      <div class="links">${data.outlinks.map(linkChip).join('')}</div></section>`);
  }
  if (data.broken.length) {
    out.push(`<section><h3>還沒建立的節點</h3><div class="links">${data.broken
      .map((b) => `<span class="chip broken" title="尚未建立">${esc(b)}</span>`)
      .join('')}</div></section>`);
  }

  out.push(`<section><h3>知識圖譜</h3>
    <canvas class="mini-graph" id="mini" title="點一下開啟完整圖譜"></canvas>
    <div class="note" id="mini-note"></div></section>`);

  out.push(`<section>${dl([
    ['加入', esc(meta.added || '')],
    ['更新', esc(meta.updated || '')],
  ])}</section>`);

  return out.join('');
}

function backlinksHtml(list) {
  if (!list.length) return '';
  return `<h2>被引用（${list.length}）</h2>` + list
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
  if (!id) return fail('網址缺少 ?id=');

  let index, data;
  try {
    [index, data] = await Promise.all([getData('index'), getData(`items/${id}`)]);
  } catch (e) {
    return fail(`找不到 ${id}：${e.message}`);
  }
  if (data.kind !== kind) {
    location.replace(itemHref(data)); // 用錯頁面就導到對的那一頁
    return;
  }

  const meta = data.meta;
  document.title = `${displayTitle(meta)} — kb`;

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
          ${meta.todo ? `<span class="todo-badge">${meta.todo} 個章節還沒寫</span>` : ''}
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
      bib.textContent = '已複製 ✓';
      setTimeout(() => (bib.textContent = '複製 BibTeX'), 1600);
    });
  }

  const mini = document.getElementById('mini');
  if (mini && typeof mountMiniGraph === 'function') mountMiniGraph(mini, id);
})();
