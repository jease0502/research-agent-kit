/* 全文頁：fulltext.html?id=<slug>&lang=zh|en
 *
 * 內容來自 data/ft/<slug>.<lang>.json，由 build.py 從 fulltext-zh/ 產生。
 * 那個目錄不在版控裡，所以 **GitHub Pages 的版本沒有這些檔案** ——
 * 前端因此不能假設 ft 一定存在，index.json 的 ft / ften 旗標才是唯一依據。
 */

const LANGS = {
  zh: { label: '__T_web_063__', flag: 'ft', note: '__T_web_064__' },
  en: { label: '__T_web_065__', flag: 'ften', note: '__T_web_066__' },
};

function langTabs(id, cur, meta) {
  const tabs = Object.entries(LANGS)
    .filter(([, cfg]) => meta[cfg.flag])
    .map(([code, cfg]) =>
      `<a class="chip${code === cur ? ' on' : ''}"
          href="fulltext.html?id=${encodeURIComponent(id)}&lang=${code}">${cfg.label}</a>`)
    .join('');
  return `<div class="ft-tabs">
    <a class="chip" href="paper.html?id=${encodeURIComponent(id)}">__T_web_067__</a>
    ${tabs}
  </div>`;
}

(async function main() {
  const id = qs('id');
  let lang = qs('lang') || 'zh';
  if (!LANGS[lang]) lang = 'zh';
  mountHeader('list');
  if (!id) return fail('__T_web_068__');

  // ft／ften、arxiv、url、code 都在單一項目的 meta 裡（index.json 只剩核心欄位）
  let index, item;
  try {
    index = await getData('index');
  } catch (e) {
    return fail(`__T_web_069__${e.message}`);
  }
  if (!index.items.some((it) => it.id === id)) return fail(`__T_web_070__${id}`);
  try {
    item = await getData(`items/${id}`);
  } catch (e) {
    return fail(`items/${id}__T_web_071__${e.message}`);
  }
  const meta = item.meta;

  // 要的語言沒有就退到另一個；兩個都沒有才報錯
  if (!meta[LANGS[lang].flag]) {
    const alt = Object.keys(LANGS).find((c) => meta[LANGS[c].flag]);
    if (!alt) {
      return fail(`${displayTitle(meta)}__T_web_072__`);
    }
    lang = alt;
  }

  let doc;
  try {
    doc = await getData(`ft/${id}.${lang}`);
  } catch (e) {
    return fail(`__T_web_073__${e.message}`);
  }

  document.title = `${displayTitle(meta)}__T_web_074__${LANGS[lang].label}__T_web_075__`;

  const src = [
    meta.arxiv && `<a href="https://arxiv.org/abs/${esc(meta.arxiv)}"
      target="_blank" rel="noopener">arXiv ${esc(meta.arxiv)} ↗</a>`,
    !meta.arxiv && meta.url &&
      `<a href="${esc(meta.url)}" target="_blank" rel="noopener">__T_web_076__</a>`,
  ].filter(Boolean).join(' · ');

  document.getElementById('app').innerHTML = `
    <div class="detail">
      <div>
        ${langTabs(id, lang, meta)}
        <h1>${esc(meta.title)}</h1>
        ${meta.title_zh && meta.title_zh !== meta.title
          ? `<div class="lede">${esc(meta.title_zh)}</div>` : ''}
        <div class="ft-note">${LANGS[lang].note}${src ? ` · ${src}` : ''}</div>
        <div class="body ft-body">${doc.html}</div>
      </div>
      <aside class="side">
        <section><h3>__T_web_077__</h3><nav class="ft-toc" id="toc"></nav></section>
      </aside>
    </div>`;

  const body = document.querySelector('.ft-body');
  wrapTables(body);

  // 目錄：只收 h2，h3 以下太細，188 篇裡有的會有上百個標題
  const toc = document.getElementById('toc');
  const heads = [...body.querySelectorAll('h2')];
  if (heads.length) {
    toc.innerHTML = heads
      .map((h, i) => {
        h.id = h.id || `ft-h${i}`;
        return `<a href="#${h.id}">${esc(h.textContent)}</a>`;
      })
      .join('');
  } else {
    toc.innerHTML = '<span class="note">__T_web_078__</span>';
  }

  mountFooter(index.build);
  initSearch(index);
})();
