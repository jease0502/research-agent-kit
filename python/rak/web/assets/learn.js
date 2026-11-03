/* 課程總覽：把 lessons 依軌道與 order 排成一條可以照著走的路徑。 */

const TRACKS = [
  {
    key: 'foundations',
    name: '__T_web_166__',
    lede: '__T_web_167__',
  },
  {
    key: 'robot-learning',
    name: '__T_web_168__',
    lede: '__T_web_169__',
  },
  {
    key: 'engineering',
    name: '__T_web_170__',
    lede: '__T_web_171__',
  },
  {
    key: 'hands-on',
    name: '__T_web_172__',
    lede: '__T_web_173__',
  },
];

const LEVEL = { beginner: '__T_web_174__', intermediate: '__T_web_175__', advanced: '__T_web_176__' };

function lessonRow(it, idx) {
  const mins = it.minutes ? `${it.minutes}__T_web_177__` : '';
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
    return fail(`__T_web_178__${e.message}`);
  }

  const lessons = index.items.filter((i) => i.kind === 'lesson');
  const total = lessons.reduce((a, b) => a + (b.minutes || 0), 0);

  if (!lessons.length) {
    document.getElementById('app').innerHTML =
      '<h1>__T_web_179__</h1><div class="empty">__T_web_180__</div>';
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
      <h2>${t.name} <span class="note">${list.length}__T_web_181__${Math.round(mins / 60)}__T_web_182__</span></h2>
      <p class="lede">${t.lede}</p>
      <div class="steps">${list.map((l, i) => lessonRow(l, i + 1)).join('')}</div>
    </section>`;
  }).join('');

  document.getElementById('app').innerHTML = `
    <h1>__T_web_183__</h1>
    <p class="lede">
      ${lessons.length}__T_web_184__${Math.round(total / 60)}__T_web_185__<strong>__T_web_186__</strong>
__T_web_187__
__T_web_188__
    </p>
    <div class="callout">
      <strong>__T_web_189__</strong>
      <ul>
        <li>__T_web_190__</li>
        <li>__T_web_191__<a class="wl wl-concept" href="index.html?kind=concept">__T_web_192__</a>
__T_web_193__<a class="wl wl-paper" href="index.html?kind=paper">__T_web_194__</a>__T_web_195__
__T_web_196__</li>
        <li>__T_web_197__</li>
        <li>__T_web_198__<strong>__T_web_199__</strong>__T_web_200__</li>
      </ul>
    </div>
    ${sections}`;

  mountFooter(index.build);
  initSearch(index);
})();
