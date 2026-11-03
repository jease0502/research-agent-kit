/* 課程總覽：把 lessons 依軌道與 order 排成一條可以照著走的路徑。 */

const TRACKS = [
  {
    key: 'foundations',
    name: '基礎軌',
    lede: '假設你什麼都還不會。從「機器學習到底在做什麼」開始，一路到能看懂一篇 VLA 論文的架構圖。',
  },
  {
    key: 'robot-learning',
    name: '機器人學習軌',
    lede: '有了基礎之後，這一軌講機器人特有的問題：動作怎麼表示、資料從哪來、模擬訓的東西怎麼搬到真機、怎麼知道它其實沒學會。',
  },
  {
    key: 'engineering',
    name: '自建軌',
    lede: '前兩軌讓你看懂別人做了什麼。這一軌講你自己要蓋什麼：資料引擎、實驗架構、訓練與服務堆疊，以及一份從 0 到 1 的里程碑。假設你有一支小團隊與有限預算。',
  },
  {
    key: 'hands-on',
    name: '實作軌',
    lede: '真的把 GPU 用起來。以 Unitree Go1 / G1 為示範本體、一張 RTX 5080 為算力：從環境安裝、PPO 訓練、獎勵設計、超參數調整、sim-to-sim 驗證，到微調 GR00T 與換場景的完整流程。每一課都有可以直接跑的程式碼與本機實測的數字。',
  },
];

const LEVEL = { beginner: '入門', intermediate: '中階', advanced: '進階' };

function lessonRow(it, idx) {
  const mins = it.minutes ? `${it.minutes} 分鐘` : '';
  const bits = [LEVEL[it.level] || it.level, mins].filter(Boolean).join(' · ');
  return `<a class="step" href="lesson.html?id=${encodeURIComponent(it.id)}">
    <span class="step-n">${idx}</span>
    <span class="step-body">
      <span class="step-title">${esc(it.title_zh || it.title)}</span>
      <span class="step-sum">${esc(it.summary || '')}</span>
    </span>
    <span class="step-meta">${esc(bits)}</span>
  </a>`;
}

(async function main() {
  mountHeader('learn');
  let index;
  try {
    index = await getListIndex();
  } catch (e) {
    return fail(`讀不到資料：${e.message}`);
  }

  const lessons = index.items.filter((i) => i.kind === 'lesson');
  const total = lessons.reduce((a, b) => a + (b.minutes || 0), 0);

  if (!lessons.length) {
    document.getElementById('app').innerHTML =
      '<h1>從零開始學</h1><div class="empty">教材還沒建立。</div>';
    mountFooter(index.build);
    return initSearch(index);
  }

  const sections = TRACKS.map((t) => {
    const list = lessons
      .filter((l) => l.track === t.key)
      .sort((a, b) => (a.order || 0) - (b.order || 0));
    if (!list.length) return '';
    const mins = list.reduce((a, b) => a + (b.minutes || 0), 0);
    return `<section class="track">
      <h2>${t.name} <span class="note">${list.length} 課 · 約 ${Math.round(mins / 60)} 小時</span></h2>
      <p class="lede">${t.lede}</p>
      <div class="steps">${list.map((l, i) => lessonRow(l, i + 1)).join('')}</div>
    </section>`;
  }).join('');

  document.getElementById('app').innerHTML = `
    <h1>從零開始學</h1>
    <p class="lede">
      ${lessons.length} 課，約 ${Math.round(total / 60)} 小時。<strong>照順序讀。</strong>
      每一課都連到這個庫裡的概念卡與論文 ——
      課本講懂原理，概念卡查定義，論文看真實的數字與限制。
    </p>
    <div class="callout">
      <strong>怎麼用這份教材</strong>
      <ul>
        <li>每一課先看「這一課要解決什麼」，確認你需不需要它。</li>
        <li>看到 <a class="wl wl-concept" href="index.html?kind=concept">橘色連結</a>
            是概念卡，<a class="wl wl-paper" href="index.html?kind=paper">藍色連結</a>是論文。
            第一次讀可以先跳過，第二次讀再點進去。</li>
        <li>做完「自我檢核」再往下一課。答不出來就回頭，不要硬推。</li>
        <li>課文裡的數字都標了出處論文；<strong>要引用請去看原文</strong>。</li>
      </ul>
    </div>
    ${sections}`;

  mountFooter(index.build);
  initSearch(index);
})();
