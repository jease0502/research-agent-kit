/* 知識圖譜。無外部函式庫，canvas 繪製。
 *
 * 佈局在 build.py 就算好了（Fruchterman–Reingold，決定性），前端載入的是
 * 已收斂的座標，所以開頁面不用等。只有拖曳、改篩選、看 ego 子圖時才跑模擬。
 * 這也讓佈局跨 session 穩定 —— 圖才會變成可以建立空間記憶的地方。
 */

const EGO_DEFAULT_THRESHOLD = 300; // 超過這個節點數，預設只顯示 ego 子圖

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function palette() {
  return {
    p: cssVar('--paper'),
    c: cssVar('--concept'),
    t: cssVar('--topic'),
    edge: cssVar('--border-strong'),
    text: cssVar('--text'),
    dim: cssVar('--text-faint'),
    bg: cssVar('--surface'),
  };
}

/* ---------------- 模擬 ---------------- */

const EDGE_LEN = { is_a: 0.6, includes: 0.9, uses: 1.0, covers: 1.0, related: 1.3, mentions: 1.2 };

function makeSim(nodes, edges, W, H) {
  const N = nodes.length;
  const k = Math.sqrt((W * H) / Math.max(N, 1));
  const REP = k * k, SPR = 0.06, DAMP = 0.85, CENTER = 0.002, MAXD2 = (6 * k) ** 2;
  let alpha = 1;

  function tick() {
    for (const n of nodes) { n.fx = 0; n.fy = 0; }
    for (let i = 0; i < N; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < N; j++) {
        const b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy;
        if (d2 > MAXD2) continue;
        if (d2 < 1e-4) { dx = Math.cos(i * 2.399) * 0.01; dy = Math.sin(i * 2.399) * 0.01; d2 = 1e-4; }
        const d = Math.sqrt(d2), f = REP / d2, ux = (dx / d) * f, uy = (dy / d) * f;
        a.fx += ux; a.fy += uy; b.fx -= ux; b.fy -= uy;
      }
    }
    for (const e of edges) {
      const a = e.a, b = e.b;
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.hypot(dx, dy) || 1e-3;
      const f = SPR * (d - k * (EDGE_LEN[e.r] || 1));
      const ux = (dx / d) * f, uy = (dy / d) * f;
      a.fx += ux; a.fy += uy; b.fx -= ux; b.fy -= uy;
    }
    for (const n of nodes) {
      if (n.pinned) { n.vx = n.vy = 0; continue; }
      n.vx = (n.vx + (n.fx - n.x * CENTER * N) * alpha) * DAMP;
      n.vy = (n.vy + (n.fy - n.y * CENTER * N) * alpha) * DAMP;
      const s = Math.hypot(n.vx, n.vy);
      if (s > 12) { n.vx *= 12 / s; n.vy *= 12 / s; }
      n.x += n.vx; n.y += n.vy;
    }
    alpha *= 0.985;
    return alpha >= 0.008; // false = 收斂，可以停掉 rAF
  }

  return { tick, reheat: (a = 0.4) => (alpha = a) };
}

const radiusOf = (n) => 4 + 2.2 * Math.sqrt(n.deg || 0);

/* ---------------- 繪製 ---------------- */

function drawNode(ctx, n, r, color, alpha) {
  ctx.globalAlpha = alpha;
  ctx.fillStyle = color;
  ctx.beginPath();
  if (n.k === 'c') {
    ctx.moveTo(n.x, n.y - r); ctx.lineTo(n.x + r, n.y);
    ctx.lineTo(n.x, n.y + r); ctx.lineTo(n.x - r, n.y);
    ctx.closePath();
  } else if (n.k === 't') {
    ctx.roundRect(n.x - r, n.y - r * 0.8, r * 2, r * 1.6, 2);
  } else {
    ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
  }
  ctx.fill();
  ctx.globalAlpha = 1;
}

/* ---------------- 主圖 ---------------- */

class GraphView {
  constructor(canvas, data, opts = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.data = data;
    this.opts = opts;
    this.hover = null;
    this.matched = null;
    this.scale = 1;
    this.tx = 0;
    this.ty = 0;
    this.running = false;
    this.setView(opts.nodeFilter || (() => true));
    this.bind();
    this.resize(); // 量到真實尺寸之後才 fit，否則會用預設值算縮放
    this.fit();
  }

  setView(filter) {
    const keep = this.data.nodes.filter(filter);
    const set = new Set(keep.map((n) => n.i));
    this.nodes = keep.map((n) => ({
      ...n, x: n.x * 420, y: n.y * 420, vx: 0, vy: 0, fx: 0, fy: 0,
    }));
    const byI = new Map(this.nodes.map((n) => [n.i, n]));
    this.edges = this.data.edges
      .filter((e) => set.has(e.s) && set.has(e.t))
      .map((e) => ({ a: byI.get(e.s), b: byI.get(e.t), r: e.r }));

    this.adj = new Map(this.nodes.map((n) => [n.i, new Set()]));
    for (const e of this.edges) {
      this.adj.get(e.a.i).add(e.b.i);
      this.adj.get(e.b.i).add(e.a.i);
    }
    this.sim = makeSim(this.nodes, this.edges, 900, 700);
    this.userMoved = false; // 換檢視就重新自動 fit
    this.fit();
    if (this.opts.onView) this.opts.onView(this.nodes.length, this.edges.length);
  }

  resize() {
    const dpr = window.devicePixelRatio || 1;
    const r = this.canvas.getBoundingClientRect();
    this.canvas.width = Math.max(1, r.width * dpr);
    this.canvas.height = Math.max(1, r.height * dpr);
    this.w = r.width;
    this.h = r.height;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  }

  fit() {
    if (!this.nodes.length) return;
    const xs = this.nodes.map((n) => n.x), ys = this.nodes.map((n) => n.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const w = this.w || this.canvas.clientWidth || 800;
    const h = this.h || this.canvas.clientHeight || 600;
    const pad = 46;
    this.scale = Math.min(
      (w - pad * 2) / Math.max(maxX - minX, 1),
      (h - pad * 2) / Math.max(maxY - minY, 1),
      3
    );
    this.tx = w / 2 - ((minX + maxX) / 2) * this.scale;
    this.ty = h / 2 - ((minY + maxY) / 2) * this.scale;
    this.draw();
  }

  toWorld(px, py) {
    return { x: (px - this.tx) / this.scale, y: (py - this.ty) / this.scale };
  }

  hit(px, py) {
    const p = this.toWorld(px, py);
    let best = null, bestD = Infinity;
    for (const n of this.nodes) {
      const r = radiusOf(n) + 5;
      const d = (n.x - p.x) ** 2 + (n.y - p.y) ** 2;
      if (d < r * r && d < bestD) { best = n; bestD = d; }
    }
    return best;
  }

  run() {
    if (this.running) return;
    this.running = true;
    const step = () => {
      const alive = this.sim.tick();
      this.draw();
      if (alive) return requestAnimationFrame(step);
      this.running = false; // 凍結：永不停的 rAF 會釘住一顆 CPU 核心
      // 模擬會把節點推出原本 fit 的範圍，收斂後補一次 —— 但使用者自己
      // 平移縮放過就不要動，那會很煩
      if (!this.userMoved) this.fit();
    };
    requestAnimationFrame(step);
  }

  draw() {
    const { ctx } = this;
    const C = palette();
    ctx.save();
    ctx.clearRect(0, 0, this.w, this.h);
    ctx.translate(this.tx, this.ty);
    ctx.scale(this.scale, this.scale);

    const focus = this.hover;
    const near = focus ? this.adj.get(focus.i) : null;
    const isLit = (n) => !focus || n.i === focus.i || near.has(n.i);

    ctx.lineWidth = 1 / this.scale;
    for (const e of this.edges) {
      const lit = !focus || e.a.i === focus.i || e.b.i === focus.i;
      ctx.globalAlpha = lit ? (focus ? 0.75 : 0.38) : 0.07;
      ctx.strokeStyle = e.r === 'is_a' ? C.text : C.edge;
      ctx.beginPath();
      ctx.moveTo(e.a.x, e.a.y);
      ctx.lineTo(e.b.x, e.b.y);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    for (const n of this.nodes) {
      const dim = !isLit(n);
      let a = n.st === 'queued' ? 0.5 : 1;
      if (dim) a *= 0.18;
      if (this.matched && !this.matched.has(n.i)) a *= 0.25;
      drawNode(ctx, n, radiusOf(n), C[n.k] || C.p, a);
    }

    ctx.font = `${12 / this.scale}px ${cssVar('--sans') || 'sans-serif'}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    // 標籤不設限就是一團糊，但小圖藏標籤又會顯得空。
    // 60 個節點以下全顯示（這是還讀得動的甜蜜點），再多就只留高連結度與焦點附近的。
    const focusOnly = this.opts.labelMode === 'focus';
    const smallGraph = this.nodes.length <= 60;
    for (const n of this.nodes) {
      const show = focusOnly
        ? n.id === this.opts.center || (focus && n.i === focus.i)
        : smallGraph || this.scale > 0.9 || n.deg >= 5 ||
          (focus && (n.i === focus.i || near.has(n.i))) ||
          (this.matched && this.matched.has(n.i));
      if (!show) continue;
      ctx.globalAlpha = isLit(n) ? 1 : 0.2;
      ctx.fillStyle = C.text;
      const label = n.l.length > 16 ? n.l.slice(0, 15) + '…' : n.l;
      ctx.fillText(label, n.x, n.y + radiusOf(n) + 3 / this.scale);
    }
    ctx.restore();
  }

  bind() {
    const cv = this.canvas;
    let drag = null, panning = null;

    cv.addEventListener('pointerdown', (e) => {
      const r = cv.getBoundingClientRect();
      const px = e.clientX - r.left, py = e.clientY - r.top;
      const n = this.hit(px, py);
      cv.setPointerCapture(e.pointerId);
      if (n) {
        drag = { n, moved: false };
        n.pinned = true;
      } else {
        panning = { px, py, tx: this.tx, ty: this.ty };
      }
    });

    cv.addEventListener('pointermove', (e) => {
      const r = cv.getBoundingClientRect();
      const px = e.clientX - r.left, py = e.clientY - r.top;
      if (drag) {
        const p = this.toWorld(px, py);
        drag.n.x = p.x; drag.n.y = p.y;
        drag.moved = true;
        this.sim.reheat(0.35);
        this.run();
        return;
      }
      if (panning) {
        this.userMoved = true;
        this.tx = panning.tx + (px - panning.px);
        this.ty = panning.ty + (py - panning.py);
        this.draw();
        return;
      }
      const n = this.hit(px, py);
      if (n !== this.hover) {
        this.hover = n;
        cv.style.cursor = n ? 'pointer' : 'grab';
        this.draw();
        if (this.opts.onHover) this.opts.onHover(n, px, py);
      } else if (n && this.opts.onHover) {
        this.opts.onHover(n, px, py);
      }
    });

    const end = (e) => {
      if (drag) {
        drag.n.pinned = false;
        if (!drag.moved && this.opts.onClick) this.opts.onClick(drag.n);
        drag = null;
      }
      panning = null;
      cv.releasePointerCapture?.(e.pointerId);
    };
    cv.addEventListener('pointerup', end);
    cv.addEventListener('pointercancel', end);
    cv.addEventListener('pointerleave', () => {
      if (this.hover) { this.hover = null; this.draw(); this.opts.onHover?.(null); }
    });

    cv.addEventListener('wheel', (e) => {
      e.preventDefault();
      const r = cv.getBoundingClientRect();
      const px = e.clientX - r.left, py = e.clientY - r.top;
      this.userMoved = true;
      const before = this.toWorld(px, py);
      const f = Math.exp(-e.deltaY * 0.0016);
      this.scale = Math.min(6, Math.max(0.15, this.scale * f));
      this.tx = px - before.x * this.scale;
      this.ty = py - before.y * this.scale;
      this.draw();
    }, { passive: false });

    window.addEventListener('resize', () => this.resize());
  }
}

/* ---------------- 詳情頁的迷你圖 ---------------- */

async function mountMiniGraph(canvas, centerId) {
  let g;
  try {
    g = await getData('graph');
  } catch { return; }

  const center = g.nodes.find((n) => n.id === centerId);
  const note = document.getElementById('mini-note');
  if (!center) return;

  const near = new Set([center.i]);
  for (const e of g.edges) {
    if (e.s === center.i) near.add(e.t);
    if (e.t === center.i) near.add(e.s);
  }
  if (near.size < 2) {
    canvas.remove();
    if (note) note.textContent = '__T_web_079__';
    return;
  }

  const view = new GraphView(canvas, g, {
    nodeFilter: (n) => near.has(n.i),
    labelMode: 'focus', // 190px 高的畫布放不下十個中文標籤
    center: centerId,
    onClick: (n) => (location.href = itemHref({ id: n.id, k: n.k })),
  });
  view.sim.reheat(0.9);
  view.run();
  setTimeout(() => view.fit(), 900);
  if (note) note.innerHTML = `${near.size - 1}__T_web_080__<a href="graph.html?focus=${
    encodeURIComponent(centerId)}">__T_web_081__</a>`;
}

/* ---------------- 圖譜頁 ---------------- */

async function mountGraphPage() {
  mountHeader('graph');
  let index, g;
  try {
    [index, g] = await Promise.all([getListIndex(), getData('graph')]);
  } catch (e) {
    return fail(`__T_web_082__${e.message}`);
  }
  mountFooter(index.build);
  initSearch(index);

  const byId = new Map(index.items.map((i) => [i.id, i]));
  const app = document.getElementById('app');
  const focus = qs('focus');

  app.innerHTML = `
    <h1>__T_web_083__</h1>
    <p class="lede">__T_web_084__</p>
    <div class="filters" id="gf"></div>
    <div class="graph-wrap">
      <canvas id="cv"></canvas>
      <div class="graph-legend">
        <span><span class="dot dot-paper"></span>__T_web_085__</span>
        <span><span class="dot dot-concept"></span>__T_web_086__</span>
        <span><span class="dot dot-topic"></span>__T_web_087__</span>
        <span id="gcount"></span>
      </div>
      <div class="graph-tip" id="tip" style="display:none"></div>
    </div>`;

  // 預設不要一次倒出所有節點：超過門檻就先給連結度最高的 ego 子圖
  let egoOf = focus || null;
  if (!egoOf && g.nodes.length > EGO_DEFAULT_THRESHOLD) {
    egoOf = g.nodes.reduce((a, b) => (b.deg > a.deg ? b : a)).id;
  }

  const filter = { kinds: new Set(['p', 'c', 't']), tag: '', ego: egoOf, egoSet: null };

  function computeEgo() {
    // 先算好一次，不要在 nodeFilter 裡對每個節點重掃整份邊表（那是 O(n·e)）
    if (!filter.ego) return (filter.egoSet = null);
    const c = g.nodes.find((x) => x.id === filter.ego);
    if (!c) return (filter.egoSet = null);
    const s = new Set([c.i]);
    for (const e of g.edges) {
      if (e.s === c.i) s.add(e.t);
      if (e.t === c.i) s.add(e.s);
    }
    filter.egoSet = s;
  }

  function nodeFilter(n) {
    if (!filter.kinds.has(n.k)) return false;
    if (filter.tag && !(n.tg || []).includes(filter.tag)) return false;
    if (filter.egoSet && !filter.egoSet.has(n.i)) return false;
    return true;
  }
  computeEgo();

  const tip = document.getElementById('tip');
  const view = new GraphView(document.getElementById('cv'), g, {
    nodeFilter,
    onClick: (n) => (location.href = itemHref({ id: n.id, k: n.k })),
    onView: (nn, ne) => {
      document.getElementById('gcount').textContent = `${nn}__T_web_088__${ne}__T_web_089__`;
    },
    onHover: (n, px, py) => {
      if (!n) return (tip.style.display = 'none');
      const it = byId.get(n.id) || {};
      tip.innerHTML = `<div><b>${esc(n.l)}</b></div>
        ${it.summary ? `<div class="s">${esc(it.summary)}</div>` : ''}
        <div class="s">${esc(KINDS[KIND_OF_CHAR[n.k]].label)} · ${n.deg}__T_web_090__</div>`;
      tip.style.display = 'block';
      tip.style.left = Math.min(px + 14, view.w - 290) + 'px';
      tip.style.top = Math.min(py + 14, view.h - 90) + 'px';
    },
  });

  function rebuild() {
    computeEgo();
    view.setView(nodeFilter);
    view.sim.reheat(0.7);
    view.run();
    renderFilters();
  }

  function renderFilters() {
    const tags = index.tags.slice(0, 12);
    document.getElementById('gf').innerHTML = `
      ${[['p', '__T_web_091__'], ['c', '__T_web_092__'], ['t', '__T_web_093__']]
        .map(([k, l]) => `<button class="chip ${filter.kinds.has(k) ? 'on' : ''}"
              data-kind="${k}">${l}</button>`).join('')}
      <span class="sep"></span>
      ${tags.map(([t]) => `<button class="chip ${filter.tag === t ? 'on' : ''}"
            data-tag="${esc(t)}">${esc(t)}</button>`).join('')}
      <span class="sep"></span>
      ${filter.ego
        ? `<button class="chip on" data-all>__T_web_094__${esc(filter.ego)}__T_web_095__</button>`
        : (g.nodes.length > EGO_DEFAULT_THRESHOLD
            ? `<span class="note">__T_web_096__${g.nodes.length}__T_web_097__</span>` : '')}
      <button class="chip" data-fit>__T_web_098__</button>`;
  }

  document.getElementById('gf').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.kind) {
      filter.kinds.has(b.dataset.kind)
        ? filter.kinds.delete(b.dataset.kind)
        : filter.kinds.add(b.dataset.kind);
    } else if (b.dataset.tag) {
      filter.tag = filter.tag === b.dataset.tag ? '' : b.dataset.tag;
    } else if ('all' in b.dataset) {
      filter.ego = null;
    } else if ('fit' in b.dataset) {
      view.sim.reheat(0.8);
      view.run();
      return;
    }
    rebuild();
  });

  document.addEventListener('keydown', (e) => {
    if (document.activeElement.tagName === 'INPUT') return;
    if (e.key === 'r' || e.key === 'R') { view.sim.reheat(0.8); view.run(); }
    if (e.key === 'f' || e.key === 'F') view.fit();
  });

  renderFilters();
  view.sim.reheat(0.15); // 座標已經是收斂的，只要輕輕安頓一下
  view.run();
}
