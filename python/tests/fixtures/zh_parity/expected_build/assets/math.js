/* 把 build.py 產生的 <span class="math"> 用 KaTeX 渲染成公式。
 *
 * 為什麼是客戶端渲染：build.py 的 MathStashPre 已經把 $…$ / $$…$$ 挑出來、
 * 存成帶原始 TeX 的 span（避免 markdown 把 `_` 吃成 <em>）。這裡只要把那些
 * span 換成排版好的公式即可，不需要在 Python 端再裝一套 TeX 引擎。
 *
 * KaTeX 是 vendor 進來的（web/assets/vendor/katex/），不用 CDN ——
 * 離線要能看，而且這個知識庫的壽命應該比任何 CDN 的網址長。
 * 300 KB 的 JS 只在頁面真的有公式時才載入。
 */

let katexLoading = null;

function loadKatex() {
  if (katexLoading) return katexLoading;
  katexLoading = new Promise((resolve, reject) => {
    const css = document.createElement('link');
    css.rel = 'stylesheet';
    css.href = 'assets/vendor/katex/katex.min.css';
    document.head.appendChild(css);

    const js = document.createElement('script');
    js.src = 'assets/vendor/katex/katex.min.js';
    js.onload = () => resolve(window.katex);
    js.onerror = () => reject(new Error('KaTeX 載入失敗'));
    document.head.appendChild(js);
  });
  return katexLoading;
}

async function renderMath(root) {
  const nodes = (root || document).querySelectorAll('.math:not([data-rendered])');
  if (!nodes.length) return;

  let katex;
  try {
    katex = await loadKatex();
  } catch {
    return; // 載不到就維持原始 TeX，總比整頁壞掉好
  }

  nodes.forEach((n) => {
    // textContent 拿到的是未跳脫的原始 TeX（build.py 存進去時做過 html.escape）
    const tex = n.textContent;
    const display = n.classList.contains('math-display');
    try {
      katex.render(tex, n, { displayMode: display, throwOnError: false, output: 'html' });
    } catch {
      // 語法錯誤就保留原文，讓人看得出哪裡寫壞了
    }
    n.setAttribute('data-rendered', '1');
  });
}
