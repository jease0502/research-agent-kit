/* 客戶端搜尋。
 *
 * 中文沒有詞界，所以 CJK 連續段落切成字元 bigram、拉丁照詞切，
 * 索引期（build.py 的 tokenize）與查詢期用**完全相同**的規則。
 * bigram 會過度生成（「強化學習」→ 強化/化學/學習），recall 因此完美，
 * 誤中則靠下面的精確子字串加分壓下去 ——「化學」的誤中不會包含原始查詢字串。
 */

const D_ID = 0, D_KIND = 1, D_TITLE = 2, D_SUM = 3, D_YEAR = 4,
      D_TAGS = 5, D_ALIAS = 6, D_ZH = 7;

const CJK_RE = /[㐀-䶿一-鿿豈-﫿]/;
const TOKEN_RE = /[a-z0-9][a-z0-9+#._-]*|[㐀-䶿一-鿿豈-﫿]+/g;

function tokenize(s) {
  s = String(s).normalize('NFKC').toLowerCase();
  const out = [];
  let m;
  TOKEN_RE.lastIndex = 0;
  while ((m = TOKEN_RE.exec(s))) {
    const t = m[0];
    if (!CJK_RE.test(t[0])) {
      out.push(t);
      if (/[-._]/.test(t)) for (const p of t.split(/[-._]/)) if (p.length > 1) out.push(p);
    } else if (t.length === 1) {
      out.push(t);
    } else {
      for (let i = 0; i + 1 < t.length; i++) out.push(t.slice(i, i + 2));
    }
  }
  return out;
}

let IDX = null;
let FULL = null; // 深度搜尋才載入
const norm = (s) => String(s).normalize('NFKC').toLowerCase();

function mergePrefix(prefix) {
  // 只對拉丁字尾詞做前綴匹配：中文 bigram 做前綴沒有意義
  const acc = new Map();
  for (const term of Object.keys(IDX.terms)) {
    if (!term.startsWith(prefix)) continue;
    for (const [d, tf] of IDX.terms[term]) acc.set(d, Math.max(acc.get(d) || 0, tf));
  }
  return acc.size ? [...acc] : null;
}

function search(q, K = 24) {
  if (!IDX) return [];
  const qs = norm(q).trim();
  if (!qs) return [];
  const qt = tokenize(q);
  const last = qt[qt.length - 1];
  const scores = new Map();

  for (const t of new Set(qt)) {
    let postings = IDX.terms[t];
    if (!postings && t === last && !CJK_RE.test(t) && t.length >= 2) postings = mergePrefix(t);
    if (!postings) continue;
    const idf = Math.log(1 + IDX.n / postings.length);
    for (const [d, tf] of postings) {
      // BM25 的 tf 飽和項，不做長度正規化：被索引的欄位長度相近，
      // 正規化只會加噪音。
      scores.set(d, (scores.get(d) || 0) + idf * (tf / (tf + 1.2)));
    }
  }

  for (const [d, s] of scores) {
    const doc = IDX.docs[d];
    let b = 0;
    if (norm(doc[D_TITLE]).includes(qs) || norm(doc[D_ZH]).includes(qs)) b += 3.0;
    else if (norm(doc[D_SUM]).includes(qs)) b += 1.5;
    if ((doc[D_ALIAS] || []).some((a) => norm(a) === qs)) b += 4.0; // 搜 PPO 要看到 PPO 那張卡
    if ((doc[D_TAGS] || []).some((t) => norm(t) === qs)) b += 1.0;
    scores.set(d, s + b);
  }

  return [...scores]
    .sort((a, b) => b[1] - a[1])
    .slice(0, K)
    .map(([d, s]) => ({ doc: IDX.docs[d], score: s, deep: false }));
}

async function deepSearch(q, have) {
  if (!FULL) FULL = (await getData('fulltext')).docs;
  const qs = norm(q).trim();
  if (!qs) return [];
  const seen = new Set(have.map((h) => h.doc[D_ID]));
  const out = [];
  for (const doc of IDX.docs) {
    if (seen.has(doc[D_ID])) continue;
    const text = FULL[doc[D_ID]];
    if (text && norm(text).includes(qs)) out.push({ doc, score: -1, deep: true });
  }
  return out;
}

function snippetOf(doc, qs) {
  const s = doc[D_SUM] || '';
  const i = norm(s).indexOf(qs);
  if (i < 0) return esc(s.slice(0, 90));
  const a = Math.max(0, i - 34);
  return (
    (a ? '…' : '') + esc(s.slice(a, i)) +
    `<mark>${esc(s.slice(i, i + qs.length))}</mark>` +
    esc(s.slice(i + qs.length, i + qs.length + 46))
  );
}

function renderHits(box, hits, q, deepAvailable) {
  const qs = norm(q).trim();
  if (!hits.length) {
    box.innerHTML = `<div class="meta">__T_web_213__${
      deepAvailable ? ' · <button data-deep>__T_web_214__</button>' : ''
    }</div>`;
    return;
  }
  const kindOf = (c) => KIND_OF_CHAR[c];
  box.innerHTML =
    hits
      .map((h) => {
        const d = h.doc;
        const zh = d[D_ZH] && d[D_ZH] !== d[D_TITLE] ? ` <span class="zh">${esc(d[D_ZH])}</span>` : '';
        return `<a class="hit" href="${kindOf(d[D_KIND]) &&
          KINDS[kindOf(d[D_KIND])].page}?id=${encodeURIComponent(d[D_ID])}">
          <div class="t"><span class="dot dot-${kindOf(d[D_KIND])}"></span>
            ${esc(d[D_TITLE])}${zh}${h.deep ? ' <span class="note">__T_web_215__</span>' : ''}</div>
          <div class="s">${snippetOf(d, qs)}</div></a>`;
      })
      .join('') +
    (deepAvailable ? '<div class="meta"><button data-deep>__T_web_216__</button></div>' : '');
}

function initSearch(index) {
  const input = document.getElementById('q');
  const box = document.getElementById('results');
  if (!input || !box) return;

  let hits = [];
  let sel = -1;
  let timer = null;
  let loading = null;

  const close = () => {
    box.innerHTML = '';
    sel = -1;
  };

  async function run() {
    const q = input.value.trim();
    if (q.length < 1) return close();
    if (!IDX) {
      loading = loading || getData('search');
      IDX = await loading;
    }
    hits = search(q);
    sel = -1;
    renderHits(box, hits, q, true);
  }

  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(run, 110);
  });
  input.addEventListener('focus', () => input.value.trim() && run());

  input.addEventListener('keydown', (e) => {
    const items = [...box.querySelectorAll('.hit')];
    if (e.key === 'Escape') return input.blur(), close();
    if (!items.length) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      sel = (sel + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length;
      items.forEach((n, i) => n.classList.toggle('sel', i === sel));
      items[sel].scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter') {
      e.preventDefault();
      items[Math.max(sel, 0)].click();
    }
  });

  box.addEventListener('click', async (e) => {
    if (!e.target.closest('[data-deep]')) return;
    e.preventDefault();
    const q = input.value.trim();
    e.target.textContent = '__T_web_217__';
    const extra = await deepSearch(q, hits);
    hits = hits.concat(extra);
    renderHits(box, hits, q, false);
  });

  document.addEventListener('click', (e) => {
    if (!e.target.closest('.search-wrap')) close();
  });
}
