/* Яйцерез — таймлайн как в монтажке: дорожки V/A, волна звука, инструменты Premiere
   (Выделение, Лезвие, Ripple, Rolling, Slip, Slide), прилипание, In/Out, мини-карта.
   Рисуется только видимая часть — тысячи кусков на многочасовом монтаже не тормозят. */
'use strict';

function createTimeline(o) {
  const cv = o.canvas, ctx = cv.getContext('2d');
  const mm = o.mmCanvas, mctx = mm.getContext('2d');
  const HEAD = 64, RULER = 24, GAP = 2, EDGE = 6;
  let items = [], total = 1;
  let view0 = 0, viewDur = 1, head = 0, W = 0, H = 0, MW = 0, MH = 0, dpr = 1, hoverT = null;
  let colors = {}, mmDirty = true, anim = null;
  let drag = null, preview = null, hover = null, activeCut = null, marq = null;
  const MIN_DUR = 2;

  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  function readColors() {
    colors = {
      video: css('--trk-video'), videoSel: css('--trk-video-sel'), audio: css('--trk-audio'), audioSel: css('--trk-audio-sel'),
      wave: css('--trk-wave'), extra: css('--trk-extra'), cam: css('--trk-cam'),
      text: css('--text'), text3: css('--text-3'), border: css('--border'), head: css('--blue'),
      bg2: css('--bg-menu'), lane: css('--trk-lane'), headBg: css('--bg-side'), label: css('--trk-label'),
      mark: css('--blue-soft'), red: css('--c-red'), snap: css('--trk-snap'),
      labs: [1, 2, 3, 4, 5, 6].map((n) => css('--lab-' + n)),
    };
    mmDirty = true;
  }

  /* ---------- раскладка дорожек ---------- */
  let rows = [];
  function layout() {
    rows = [];
    let y = RULER + 4;
    for (const tr of o.tracks()) { rows.push({ ...tr, y }); y += tr.h + GAP; }
    const need = y + 20;
    const box = cv.parentElement;
    if (Math.abs(box.offsetHeight - need) > 1) box.style.height = need + 'px';
  }
  function resize() {
    dpr = window.devicePixelRatio || 1;
    const r = cv.getBoundingClientRect(), m = mm.getBoundingClientRect();
    W = r.width; H = r.height; MW = m.width; MH = m.height;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    mm.width = Math.round(MW * dpr); mm.height = Math.round(MH * dpr);
    mmDirty = true;
  }
  new ResizeObserver(() => { resize(); request(); }).observe(cv);

  const TW = () => Math.max(1, W - HEAD);
  const xOf = (t) => HEAD + (t - view0) / viewDur * TW();
  const tOf = (x) => view0 + (x - HEAD) / TW() * viewDur;
  const pps = () => TW() / viewDur;
  function clampView() {
    viewDur = Math.min(Math.max(viewDur, Math.min(MIN_DUR, total)), Math.max(total, 1));
    view0 = Math.min(Math.max(view0, 0), Math.max(0, total - viewDur));
  }
  const durOf = (it) => it.out - it.in;
  function lowerBound(list, t) {
    let lo = 0, hi = list.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (list[m].t + durOf(list[m]) < t) lo = m + 1; else hi = m; }
    return lo;
  }
  function indexAt(list, t) {
    const i = lowerBound(list, t);
    const it = list[i];
    return it && t >= it.t && t <= it.t + durOf(it) ? i : -1;
  }
  function clock(t) {
    t = Math.max(0, t);
    const hh = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = Math.floor(t % 60), f = Math.floor((t % 1) * 25);
    const base = (hh ? `${hh}:${String(m).padStart(2, '0')}` : `${m}`) + `:${String(s).padStart(2, '0')}`;
    return pps() > 120 ? `${base}:${String(f).padStart(2, '0')}` : base;
  }
  const step = (sec) => [1 / 25, 2 / 25, 5 / 25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600].find((s) => s >= sec) || 7200;

  /* ---------- рисование ---------- */
  function roundRect(c, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath();
  }
  function drawClips(list, row, sel) {
    const from = lowerBound(list, view0);
    const p = pps();
    const isAudio = row.kind === 'audio';
    let lastX = -1;
    for (let i = from; i < list.length; i++) {
      const it = list[i];
      const x0 = xOf(it.t), x1 = xOf(it.t + durOf(it));
      if (x0 > W) break;
      if (x1 < HEAD) continue;
      let segIn = it.in, label = '';
      if (row.track != null) {   // дополнительная дорожка: тот же кусок с записи экрана / второй камеры
        const s = (it.scr || []).find((e) => o.trackOf(e[0]) === row.track);
        if (!s) continue;
        segIn = s[1];
        label = o.screenName(s[0]);
      }
      if (x1 - x0 < 1.5 && Math.floor(x0) === lastX) continue;
      lastX = Math.floor(x0);
      const selected = sel.has(i) && row.track == null;
      const cx0 = Math.max(x0, HEAD), cx1 = Math.min(x1, W);
      const w = Math.max(1, cx1 - cx0 - (x1 - x0 > 4 ? 1 : 0));
      ctx.fillStyle = row.track != null ? colors.extra
        : isAudio ? (row.cam ? colors.cam : (selected ? colors.audioSel : colors.audio)) : (selected ? colors.videoSel : colors.video);
      if (it.lab && row.track == null && !row.cam) ctx.fillStyle = colors.labs[it.lab - 1] || ctx.fillStyle;
      if (w > 6) { roundRect(ctx, cx0, row.y, w, row.h, 3); ctx.fill(); } else ctx.fillRect(cx0, row.y, w, row.h);
      if (selected && w > 3) { ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; roundRect(ctx, cx0 + 0.75, row.y + 0.75, w - 1.5, row.h - 1.5, 3); ctx.stroke(); }
      if (isAudio && !row.cam && w > 3) {      // волна звука микрофона
        const wave = o.wave(it.clip);
        if (wave) {
          const fps = o.waveFps || 200, mid = row.y + row.h / 2, amp = row.h / 2 - 2;
          const step = w > 1500 ? 1 : 0.5, n = wave.length;
          const xs = [], ys = [];
          for (let x = cx0; x <= cx1; x += step) {
            const ta = (segIn + (x - x0) / p) * fps, tb = ta + (step / p) * fps;
            let v;
            if (tb - ta <= 1) {   // крупно: плавно между соседними пиками
              const i = Math.floor(ta), f = ta - i;
              v = (wave[i] || 0) * (1 - f) + (wave[Math.min(i + 1, n - 1)] || 0) * f;
            } else {              // мелко: самый громкий пик под пикселем
              v = 0;
              const ia = Math.max(0, Math.floor(ta)), ib = Math.min(n, Math.ceil(tb));
              const stride = Math.max(1, Math.floor((ib - ia) / 48));
              for (let i = ia; i < ib; i += stride) if (wave[i] > v) v = wave[i];
            }
            xs.push(x); ys.push(Math.max(0.4, (v / 255) * amp));
          }
          ctx.save(); ctx.beginPath(); ctx.rect(cx0, row.y, w, row.h); ctx.clip();
          ctx.fillStyle = colors.wave;
          ctx.beginPath();
          ctx.moveTo(xs[0], mid);
          for (let i = 0; i < xs.length; i++) ctx.lineTo(xs[i], mid - ys[i]);
          for (let i = xs.length - 1; i >= 0; i--) ctx.lineTo(xs[i], mid + ys[i]);
          ctx.closePath(); ctx.fill();
          ctx.fillRect(cx0, mid - 0.25, w, 0.5);
          ctx.restore();
        }
      }
      if (!isAudio && row.track == null && it.z && w > 26) {
        const txt = Math.round(it.z.s) + '%';
        ctx.font = '600 10px ui-sans-serif, "Segoe UI", sans-serif';
        const tw = ctx.measureText(txt).width + 8;
        if (w > tw + 8) {
          ctx.fillStyle = 'rgba(0,0,0,.45)'; roundRect(ctx, cx0 + w - tw - 3, row.y + row.h - 15, tw, 12, 3); ctx.fill();
          ctx.fillStyle = '#fff'; ctx.fillText(txt, cx0 + w - tw + 1, row.y + row.h - 9);
        }
      }
      if (!isAudio && w > 40) {
        if (!label) label = o.label(it);
        if (label) {
          ctx.save(); ctx.beginPath(); ctx.rect(cx0 + 5, row.y, w - 10, row.h); ctx.clip();
          ctx.fillStyle = colors.label;
          ctx.font = (row.h > 36 ? '12px' : '11px') + ' ui-sans-serif, "Segoe UI", sans-serif';
          ctx.fillText(label, cx0 + 6, row.y + Math.min(15, row.h / 2 + 4));
          ctx.restore();
        }
      }
    }
  }
  function draw() {
    if (!W) return;
    clampView();
    layout();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const list = preview || items;
    const sel = o.selection();
    for (const row of rows) { ctx.fillStyle = colors.lane; ctx.fillRect(HEAD, row.y, W - HEAD, row.h); }
    const mk = o.marks();
    if (mk.in != null || mk.out != null) {
      const a = Math.max(HEAD, xOf(mk.in != null ? mk.in : 0)), b = Math.min(W, xOf(mk.out != null ? mk.out : total));
      ctx.fillStyle = colors.mark;
      if (b > a) ctx.fillRect(a, 0, b - a, H);
    }
    // линейка
    const st = step(80 / pps());
    ctx.font = '11px ui-sans-serif, "Segoe UI", sans-serif';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = colors.text3; ctx.strokeStyle = colors.border; ctx.lineWidth = 1;
    ctx.beginPath();
    for (let tt = Math.floor(view0 / st) * st; tt <= view0 + viewDur; tt += st) {
      const x = Math.round(xOf(tt)) + 0.5;
      if (x < HEAD) continue;
      ctx.moveTo(x, RULER - 7); ctx.lineTo(x, RULER);
      ctx.fillText(clock(tt), x + 4, RULER / 2 - 1);
      for (let k = 1; k < 5; k++) {
        const xs = Math.round(xOf(tt + (k * st) / 5)) + 0.5;
        if (xs > HEAD && pps() * st / 5 > 6) { ctx.moveTo(xs, RULER - 3); ctx.lineTo(xs, RULER); }
      }
    }
    ctx.stroke();
    for (const row of rows) drawClips(list, row, sel);
    // ромбики на склейках, где что-то вырезано
    const v1 = rows.find((r) => r.id === 'V1');
    if (v1 && !preview) {
      for (const c of o.cuts()) {
        if (!c.removed.length) continue;
        const x = Math.round(xOf(c.t)) + 0.5;
        if (x < HEAD - 6 || x > W + 6) continue;
        ctx.fillStyle = c === activeCut ? colors.head : colors.text;
        const y = v1.y + v1.h - 1;
        ctx.beginPath(); ctx.moveTo(x, y - 9); ctx.lineTo(x + 4.5, y - 4.5); ctx.lineTo(x, y); ctx.lineTo(x - 4.5, y - 4.5); ctx.fill();
      }
    }
    // выделенная склейка — как в Premiere: подсвечена сама точка склейки с обеих сторон
    const selT = o.selectedCut ? o.selectedCut() : null;
    if (selT != null && !drag) {
      const x = xOf(selT), lk = rows.filter((r) => r.track == null && !r.cam);
      if (lk.length && x > HEAD - 20 && x < W + 20) {
        const y0 = lk[0].y, y1 = lk[lk.length - 1].y + lk[lk.length - 1].h;
        ctx.fillStyle = colors.red;
        ctx.globalAlpha = 0.28; ctx.fillRect(x - 10, y0, 20, y1 - y0); ctx.globalAlpha = 1;
        ctx.fillRect(x - 1.5, y0 - 4, 3, y1 - y0 + 8);
        ctx.fillRect(x - 9, y0 - 4, 18, 2.5); ctx.fillRect(x - 9, y1 + 1.5, 18, 2.5);
      }
    }
    const hl = drag ? drag.hl : (hover && hover.t);
    const side = drag ? (drag.mode === 'roll' ? 'roll' : drag.side) : (hover && hover.side);
    if (hl != null) {
      const x = xOf(hl), lk = rows.filter((r) => r.track == null && !r.cam);
      const y0 = lk.length ? lk[0].y : RULER, y1 = lk.length ? lk[lk.length - 1].y + lk[lk.length - 1].h : H;
      ctx.fillStyle = colors.red;
      ctx.globalAlpha = 0.16;
      if (side === 'out') ctx.fillRect(x - 16, y0, 16, y1 - y0);
      else if (side === 'in') ctx.fillRect(x, y0, 16, y1 - y0);
      ctx.globalAlpha = 1;
      ctx.fillRect(x - 1, y0 - 3, 2, y1 - y0 + 6);
      // скобка: «]» — конец левого куска, «[» — начало правого, «][» — сдвиг склейки
      const tick = (dir) => { ctx.fillRect(dir < 0 ? x - 7 : x + 1, y0 - 3, 6, 2); ctx.fillRect(dir < 0 ? x - 7 : x + 1, y1 + 1, 6, 2); };
      if (side === 'out' || side === 'roll') tick(-1);
      if (side === 'in' || side === 'roll') tick(1);
    }
    if (marq) {
      ctx.fillStyle = colors.mark; ctx.strokeStyle = colors.head; ctx.lineWidth = 1;
      const x = Math.min(marq.x0, marq.x1), y = Math.min(marq.y0, marq.y1), w = Math.abs(marq.x1 - marq.x0), h = Math.abs(marq.y1 - marq.y0);
      ctx.fillRect(x, y, w, h); ctx.strokeRect(x + 0.5, y + 0.5, w, h);
    }
    if (drag && drag.label) {
      const x = Math.round(xOf(drag.hl != null ? drag.hl : head));
      ctx.font = '11px ui-sans-serif, "Segoe UI", sans-serif';
      const tw = ctx.measureText(drag.label).width + 10, lx = Math.min(x + 6, W - tw - 2);
      ctx.fillStyle = colors.bg2; ctx.fillRect(lx, RULER + 2, tw, 18);
      ctx.fillStyle = colors.text; ctx.fillText(drag.label, lx + 5, RULER + 11);
    }
    if (hoverT != null && !drag) {
      const x = Math.round(xOf(hoverT)) + 0.5;
      if (x >= HEAD) { ctx.strokeStyle = colors.text3; ctx.beginPath(); ctx.moveTo(x, RULER); ctx.lineTo(x, H); ctx.stroke(); }
    }
    // заголовки дорожек
    ctx.fillStyle = colors.headBg; ctx.fillRect(0, 0, HEAD, H);
    ctx.fillStyle = colors.border; ctx.fillRect(HEAD - 1, 0, 1, H);
    for (const row of rows) {
      ctx.fillStyle = row.kind === 'audio' ? colors.audio : (row.track != null ? colors.extra : colors.video);
      ctx.fillRect(5, row.y + 2, 3, row.h - 4);
      ctx.fillStyle = colors.text; ctx.font = '600 11px ui-sans-serif, "Segoe UI", sans-serif';
      ctx.fillText(row.id, 13, row.y + row.h / 2);
      if (row.sub && row.h >= 26) {
        ctx.fillStyle = colors.text3; ctx.font = '10px ui-sans-serif, "Segoe UI", sans-serif';
        ctx.fillText(row.sub.slice(0, 6), 33, row.y + row.h / 2);
      }
    }
    if (snapAt != null && drag) {
      const sx = xOf(snapAt);
      ctx.fillStyle = colors.snap;
      ctx.fillRect(sx - 0.5, RULER, 1, H - RULER);
      ctx.beginPath(); ctx.moveTo(sx - 5, RULER); ctx.lineTo(sx + 5, RULER); ctx.lineTo(sx, RULER + 6); ctx.fill();
      ctx.beginPath(); ctx.moveTo(sx - 5, H); ctx.lineTo(sx + 5, H); ctx.lineTo(sx, H - 6); ctx.fill();
    }
    // плейхед с ручкой на линейке, как в Premiere
    const hx = xOf(head);
    if (hx >= HEAD - 1 && hx <= W + 1) {
      ctx.fillStyle = colors.head;
      ctx.fillRect(hx - 0.75, RULER - 2, 1.5, H - RULER + 2);
      roundRect(ctx, hx - 6, 2, 12, RULER - 7, 3); ctx.fill();
      ctx.beginPath(); ctx.moveTo(hx - 6, RULER - 6); ctx.lineTo(hx + 6, RULER - 6); ctx.lineTo(hx, RULER); ctx.fill();
    }
  }
  function drawMini() {
    if (!MW) return;
    mctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    mctx.clearRect(0, 0, MW, MH);
    let lastX = -1;
    mctx.fillStyle = colors.video;
    for (const it of items) {
      const x0 = it.t / total * MW, x1 = (it.t + durOf(it)) / total * MW;
      if (Math.floor(x1) === lastX) continue;
      lastX = Math.floor(x1);
      mctx.fillRect(x0, 4, Math.max(1, x1 - x0 - (x1 - x0 > 3 ? 1 : 0)), MH - 8);
    }
  }
  function placeView() {
    o.mmView.style.left = (view0 / total * 100) + '%';
    o.mmView.style.width = `max(10px, ${viewDur / total * 100}%)`;
    const pos = Math.log(total / viewDur) / Math.log(Math.max(total / Math.min(MIN_DUR, total), 1.0001));
    const pc = Math.min(Math.max(pos, 0), 1) * 100;
    o.slider.querySelector('.fill').style.width = pc + '%';
    o.slider.querySelector('.knob').style.left = pc + '%';
  }
  let rq = false;
  function request() {
    if (rq) return;
    rq = true;
    requestAnimationFrame(() => { rq = false; if (mmDirty) { drawMini(); mmDirty = false; } draw(); placeView(); });
  }
  function animateTo(v0, vd) {
    stopGlide();
    const s0 = view0, sd = viewDur, t0 = performance.now();
    cancelAnimationFrame(anim);
    const tick = (now) => {
      const k = Math.min(1, (now - t0) / 200), e = 1 - Math.pow(1 - k, 3);
      view0 = s0 + (v0 - s0) * e; viewDur = sd + (vd - sd) * e;
      request();
      if (k < 1) anim = requestAnimationFrame(tick);
    };
    anim = requestAnimationFrame(tick);
  }
  // колесо: копим цель и мягко догоняем её каждый кадр — без рывков
  let goal = null, glide = 0, glideN = 0;
  function glideTo(v0, vd) {
    vd = Math.min(Math.max(vd, Math.min(MIN_DUR, total)), Math.max(total, 1));
    goal = { v0: Math.min(Math.max(v0, 0), Math.max(0, total - vd)), vd };
    glideN = 0;
    if (glide) return;
    const step = () => {
      if (++glideN > 90) { goal = null; glide = 0; request(); return; }
      const k = 0.28;
      view0 += (goal.v0 - view0) * k;
      viewDur += (goal.vd - viewDur) * k;
      if (Math.abs(goal.v0 - view0) < viewDur * 1e-4 && Math.abs(goal.vd - viewDur) < viewDur * 1e-4) {
        view0 = goal.v0; viewDur = goal.vd; goal = null; glide = 0; request(); return;
      }
      request();
      glide = requestAnimationFrame(step);
    };
    glide = requestAnimationFrame(step);
  }
  function stopGlide() { if (glide) cancelAnimationFrame(glide); glide = 0; goal = null; }
  function zoomAround(factor, tAnchor, smooth) {
    const nd = Math.min(Math.max(viewDur * factor, Math.min(MIN_DUR, total)), total);
    const n0 = tAnchor - ((tAnchor - view0) / viewDur) * nd;
    if (smooth) animateTo(n0, nd); else { view0 = n0; viewDur = nd; request(); }
  }

  /* ---------- попадание мышью ---------- */
  const rowAt = (y) => rows.find((r) => y >= r.y && y <= r.y + r.h) || null;
  function hit(e) {
    const r = cv.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top, t = tOf(x);
    if (x < HEAD) return { zone: 'head', x, y, t };
    if (y < RULER) return { zone: 'ruler', x, y, t };
    const row = rowAt(y);
    if (!row) return { zone: 'empty', x, y, t };
    const linked = row.track == null;
    const i = indexAt(items, t);
    let edge = null, best = EDGE + 1;
    const from = Math.max(0, lowerBound(items, tOf(x - EDGE)) - 1);
    for (let k = from; k < items.length; k++) {
      const it = items[k];
      const xa = xOf(it.t), xb = xOf(it.t + durOf(it));
      if (xa > x + EDGE) break;
      const da = Math.abs(x - xa), db = Math.abs(x - xb);
      if (da < best) { best = da; edge = { k, side: 'in', t: it.t }; }
      if (db < best) { best = db; edge = { k, side: 'out', t: it.t + durOf(it) }; }
    }
    if (edge) {   // на самой склейке: левее — конец левого куска, правее — начало правого
      const xe = xOf(edge.t);
      if (edge.side === 'in' && x < xe && edge.k > 0) edge = { k: edge.k - 1, side: 'out', t: edge.t };
      else if (edge.side === 'out' && x > xe && edge.k + 1 < items.length) edge = { k: edge.k + 1, side: 'in', t: edge.t };
    }
    return { zone: 'track', row, linked, i, edge: best <= EDGE ? edge : null, x, y, t };
  }
  const tool = () => o.tool();
  /* Курсоры как в Premiere: у каждого инструмента свой значок; у края клипа — скобка
     (красная — подрезка, жёлтая — подрезка со сдвигом), у склейки для «сдвига» — двойная скобка. */
  const svgCur = (body, hx, hy, fb) => `url("data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'>${body}</svg>`)}") ${hx} ${hy}, ${fb}`;
  const OUT = "stroke='#fff' stroke-width='3.2' stroke-linejoin='round' stroke-linecap='round' fill='none'";
  const bracket = (dir, col) => {   // dir: 1 — «[» (начало клипа), -1 — «]» (конец)
    const x = 12, d = dir * 4;
    const path = `M${x + d} 5H${x}V19H${x + d}`;
    const arr = dir > 0 ? 'M5 12H10M7.5 9.5L10 12L7.5 14.5' : 'M19 12H14M16.5 9.5L14 12L16.5 14.5';
    return svgCur(`<path d='${path}' ${OUT}/><path d='${arr}' ${OUT}/><path d='${path}' stroke='${col}' stroke-width='2' fill='none'/>`
      + `<path d='${arr}' stroke='${col}' stroke-width='1.6' fill='none' stroke-linecap='round'/>`, 12, 12, dir > 0 ? 'w-resize' : 'e-resize');
  };
  const CUR = {
    trimIn: bracket(1, '#e5484d'), trimOut: bracket(-1, '#e5484d'),
    rippleIn: bracket(1, '#f5c518'), rippleOut: bracket(-1, '#f5c518'),
    roll: svgCur(`<path d='M10 5H12V19H10M14 5H12M14 19H12' ${OUT}/><path d='M10 5H12V19H10M14 5H12M14 19H12' stroke='#e5484d' stroke-width='2' fill='none'/>`
      + `<path d='M3 12H7M5 10L3 12L5 14M21 12H17M19 10L21 12L19 14' ${OUT}/><path d='M3 12H7M5 10L3 12L5 14M21 12H17M19 10L21 12L19 14' stroke='#e5484d' stroke-width='1.6' fill='none' stroke-linecap='round'/>`, 12, 12, 'col-resize'),
    razor: svgCur(`<g transform='rotate(-40 12 12)'><rect x='4' y='9' width='16' height='6' rx='1' fill='#fff' stroke='#111' stroke-width='1.2'/><path d='M8 12H16' stroke='#111' stroke-width='1.4'/></g>`
      + `<path d='M3 21L6 18' stroke='#111' stroke-width='1.6'/>`, 3, 21, 'crosshair'),
    slip: svgCur(`<path d='M5 6V18M19 6V18M8 12H16M10 10L8 12L10 14M14 10L16 12L14 14' ${OUT}/><path d='M5 6V18M19 6V18M8 12H16M10 10L8 12L10 14M14 10L16 12L14 14' stroke='#111' stroke-width='1.6' fill='none' stroke-linecap='round'/>`, 12, 12, 'ew-resize'),
  };
  function cursorFor(h) {
    if (!h || h.zone === 'head' || h.zone === 'empty') return tool() === 'razor' ? CUR.razor : 'default';
    if (h.zone === 'ruler') return 'col-resize';
    const tl = tool();
    if (tl === 'hand') return 'grab';
    if (tl === 'zoom') return 'zoom-in';
    if (tl === 'razor') return CUR.razor;
    if (h.edge && h.linked && tl === 'select') return h.edge.side === 'in' ? CUR.trimIn : CUR.trimOut;
    if (h.edge && h.linked && tl === 'ripple') return h.edge.side === 'in' ? CUR.rippleIn : CUR.rippleOut;
    if (h.edge && h.linked && tl === 'roll') return CUR.roll;
    if (tl === 'slip') return h.i >= 0 && h.linked ? CUR.slip : 'default';
    if (tl === 'ripple') return h.i >= 0 ? CUR.rippleOut : 'default';
    if (tl === 'roll') return CUR.roll;
    return 'default';
  }
  // магнит: включён кнопкой (Shift на время перетаскивания — наоборот)
  const snapOn = (e) => ((o.snapping ? o.snapping() : true) !== !!(e && e.shiftKey));
  let snapAt = null;   // где сейчас прилипло — рисуем метку как в Premiere
  function snap(tg, exclude, noHead) {   // прилипание к плейхеду, In/Out и склейкам
    const thr = 9 / pps();
    let best = null, bd = thr;
    const cand = noHead ? [0, total] : [head];
    const mk = o.marks();
    if (mk.in != null) cand.push(mk.in);
    if (mk.out != null) cand.push(mk.out);
    const from = lowerBound(items, tg - thr * 2);
    for (let k = Math.max(0, from - 1); k < Math.min(items.length, from + 3); k++) {
      if (k !== exclude) cand.push(items[k].t, items[k].t + durOf(items[k]));
    }
    for (const c of cand) { const d = Math.abs(c - tg); if (d < bd) { bd = d; best = c; } }
    return best;
  }
  function scrubT(tt, e) {
    tt = Math.min(Math.max(tt, 0), total);
    snapAt = null;
    if (snapOn(e)) { const s = snap(tt, -1, true); if (s != null) { tt = s; snapAt = s; } }
    return tt;
  }
  const frames = (s) => `${s >= 0 ? '+' : '−'}${Math.round(Math.abs(s) * 25)} ${o.frameWord || 'fr'}`;

  cv.addEventListener('mousedown', (e) => { if (e.button === 1) e.preventDefault(); });   // без автопрокрутки браузера
  cv.addEventListener('pointerdown', (e) => {
    if (e.button === 1) {
      e.preventDefault();
      stopGlide();
      drag = { mode: 'hand', x0: e.clientX, v0: view0, middle: true };
      cv.setPointerCapture(e.pointerId);
      cv.style.cursor = 'grabbing';
      return;
    }
    if (e.button !== 0) return;
    const h = hit(e);
    o.tip.classList.remove('on');
    if (h.zone === 'ruler') {
      drag = { mode: 'scrub' };
      cv.setPointerCapture(e.pointerId);
      o.onScrub(scrubT(h.t, e));
      return;
    }
    if (h.zone !== 'track') { if (h.zone === 'empty') o.onSelect(-1, false); return; }
    const tl = tool();
    if (tl === 'hand') {
      drag = { mode: 'hand', x0: e.clientX, v0: view0 };
      cv.setPointerCapture(e.pointerId);
      cv.style.cursor = 'grabbing';
      return;
    }
    if (tl === 'zoom') { zoomAround(e.altKey ? 2 : 0.5, h.t, true); return; }
    if ((tl === 'track_fwd' || tl === 'track_back') && h.linked) {
      if (h.i >= 0) o.onSelectRange(h.i, tl === 'track_fwd' ? 1 : -1, e.shiftKey);
      return;
    }
    if (h.row.id === 'V1' && h.y > h.row.y + h.row.h - 12) {
      const c = o.cuts().find((c) => c.removed.length && Math.abs(xOf(c.t) - h.x) <= 7);
      if (c) { activeCut = c; o.onCutClick(c, e); request(); return; }
    }
    if (o.onPointerStart) o.onPointerStart();
    if (tl === 'razor') {
      if (h.i >= 0 && h.linked) {
        let tt = h.t;
        if (snapOn(e)) { const s = snap(tt, -1); if (s != null) tt = s; }
        const it = items[h.i];
        o.onEdit({ type: 'split', k: h.i, src: it.in + (tt - it.t) });
      }
      return;
    }
    if (h.edge && h.linked && (tl === 'select' || tl === 'ripple' || tl === 'roll')) {
      const k = h.edge.k;
      const canRoll = tl === 'roll' && ((h.edge.side === 'out' && k + 1 < items.length) || (h.edge.side === 'in' && k > 0));
      drag = { mode: canRoll ? 'roll' : 'trim', side: h.edge.side, k: canRoll && h.edge.side === 'in' ? k - 1 : k,
               x0: e.clientX, t0: h.edge.t, hl: h.edge.t, cutT: h.edge.t, moved: false };
      cv.setPointerCapture(e.pointerId);
      request();
      return;
    }
    if (h.i >= 0 && h.linked && (tl === 'slip' || tl === 'slide')) {
      drag = { mode: tl, k: h.i, x0: e.clientX, hl: null };
      cv.setPointerCapture(e.pointerId);
      return;
    }
    const add = e.ctrlKey || e.metaKey || e.shiftKey;
    const onClip = h.i >= 0 && h.linked && (h.row.track == null) && !h.row.cam;
    if (tl === 'select' && (!onClip || e.ctrlKey || e.metaKey)) {
      marq = { x0: h.x, y0: h.y, x1: h.x, y1: h.y, add, moved: false };
      cv.setPointerCapture(e.pointerId);
      if (!add) o.onSelect(-1, false);
      request();
      return;
    }
    if (onClip && !(o.selection().has(h.i) && add)) o.onSelect(h.i, add);
    else if (!onClip) o.onSelect(-1, false);
    if (onClip && tl === 'select') {
      drag = { mode: 'move', k: h.i, x0: e.clientX, t0: items[h.i].t, hl: null, moved: false };
      cv.setPointerCapture(e.pointerId);
    }
    request();
  });
  cv.addEventListener('pointermove', (e) => {
    const h = hit(e);
    hoverT = h.zone === 'track' || h.zone === 'ruler' ? h.t : null;
    if (marq) {
      marq.x1 = h.x; marq.y1 = h.y;
      if (Math.abs(marq.x1 - marq.x0) > 3) marq.moved = true;
      const a = tOf(Math.min(marq.x0, marq.x1)), b = tOf(Math.max(marq.x0, marq.x1));
      const ks = [];
      if (marq.moved) for (let k = Math.max(0, lowerBound(items, a)); k < items.length && items[k].t < b; k++) ks.push(k);
      o.onSelectSet(ks, marq.add);
      request();
      return;
    }
    if (drag && !drag.moved && drag.x0 != null && Math.abs(e.clientX - drag.x0) < 4) return;   // ещё не тянем — это клик
    if (drag) drag.moved = true;
    if (drag) {
      if (drag.mode === 'hand') {
        stopGlide();
        view0 = drag.v0 - (e.clientX - drag.x0) / pps();
        request();
        return;
      }
      if (drag.mode === 'scrub') {
        const x = e.clientX - cv.getBoundingClientRect().left;
        if (x > W - 20) view0 += viewDur * 0.02; else if (x < HEAD + 20) view0 -= viewDur * 0.02;
        o.onScrub(scrubT(h.t, e));
        request();
        return;
      }
      snapAt = null;
      let d = Math.round(((e.clientX - drag.x0) / pps()) * 25) / 25;   // по кадрам
      let op = null;
      const it = items[drag.k];
      if (drag.mode === 'trim' || drag.mode === 'roll') {
        const s = snapOn(e) ? snap(drag.t0 + d, drag.k) : null;
        snapAt = s;
        if (s != null) d = Math.round((s - drag.t0) * 25) / 25;
        if (drag.mode === 'roll') op = { type: 'roll', k: drag.k, d };
        else if (drag.side === 'in') op = { type: 'trimIn', k: drag.k, value: it.in + d };
        else op = { type: 'trimOut', k: drag.k, value: it.out + d };
        // при ripple-подрезке начала таймлайн не двигается слева — склейка остаётся на месте
        drag.hl = drag.t0 + (drag.mode === 'trim' && drag.side === 'in' ? 0 : d);
        drag.label = frames(d);
        o.onEdgeFrame(it.clip, drag.side === 'in' && drag.mode === 'trim' ? it.in + d : it.out + d);
      } else if (drag.mode === 'move') {
        // кусок едет вместе со всем, что правее; предыдущий удлиняется или укорачивается
        if (drag.k > 0) {
          const pv = items[drag.k - 1];
          const s = snapOn(e) ? snap(drag.t0 + d, drag.k, true) : null;
          snapAt = s;
          if (s != null) d = Math.round((s - drag.t0) * 25) / 25;
          op = { type: 'trimOut', k: drag.k - 1, value: pv.out + d };
          drag.hl = drag.t0 + d;
          drag.label = frames(d);
        }
      } else if (drag.mode === 'slip') {
        op = { type: 'slip', k: drag.k, d: -d };
        drag.label = frames(-d);
        o.onEdgeFrame(it.clip, it.in - d);
      } else if (drag.mode === 'slide') {
        const st = it.t + d, en = st + durOf(it);
        const s1 = snapOn(e) ? snap(st, drag.k, true) : null, s2 = snapOn(e) && s1 == null ? snap(en, drag.k, true) : null;
        if (s1 != null) d = Math.round((s1 - it.t) * 25) / 25; else if (s2 != null) d = Math.round((s2 - durOf(it) - it.t) * 25) / 25;
        snapAt = s1 != null ? s1 : s2;
        op = { type: 'slide', k: drag.k, d };
        drag.label = frames(d);
        drag.hl = it.t + d;
      }
      drag.op = op;
      preview = op ? o.previewOp(op) : null;
      request();
      return;
    }
    hover = h.zone === 'track' && h.edge && h.linked && ['select', 'ripple', 'roll'].includes(tool())
      ? { t: h.edge.t, side: tool() === 'roll' ? 'roll' : h.edge.side } : null;
    cv.style.cursor = cursorFor(h);
    if (h.zone === 'track' && h.i >= 0) {
      o.fillTip(o.tip, items[h.i]);
      const r = cv.getBoundingClientRect();
      o.tip.style.left = Math.min(e.clientX + 12, innerWidth - 340) + 'px';
      o.tip.style.top = (r.top - o.tip.offsetHeight - 8) + 'px';
      o.tip.classList.add('on');
    } else o.tip.classList.remove('on');
    request();
  });
  const end = (e) => {
    if (marq) { marq = null; request(); return; }
    if (!drag) return;
    const d = drag;
    drag = null;
    preview = null;
    snapAt = null;
    if (d.mode === 'hand') { cv.style.cursor = d.middle ? cursorFor(hit(e)) : 'grab'; request(); return; }
    if (d.mode === 'scrub') o.onScrubEnd(Math.min(Math.max(hit(e).t, 0), total));
    else if ((d.mode === 'trim' || d.mode === 'roll') && !d.moved) { if (o.onCutAt) o.onCutAt(d.cutT, e); }
    else if (d.op && d.moved) {
      const op = d.op, it = items[op.k];
      const changed = op.d ? Math.abs(op.d) > 1e-4 : it && Math.abs(op.value - (op.type === 'trimIn' ? it.in : it.out)) > 1e-4;
      if (changed) o.onEdit(op);
    }
    if (o.onDragEnd) o.onDragEnd();
    request();
  };
  cv.addEventListener('pointerup', end);
  cv.addEventListener('pointercancel', end);
  cv.addEventListener('pointerleave', () => { o.tip.classList.remove('on'); hoverT = null; hover = null; request(); });
  cv.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    const h = hit(e);
    if (h.zone === 'track' && h.i >= 0) o.onContext(items[h.i], e, h.i);
  });
  cv.addEventListener('dblclick', (e) => { const h = hit(e); if (h.zone === 'track' && h.i >= 0) o.onSeek(h.t); });
  // колесо как в Premiere: прокрутка влево-вправо, Alt + колесо — масштаб у курсора
  cv.addEventListener('wheel', (e) => {
    if (e.ctrlKey) return;              // Ctrl + колесо — масштаб интерфейса
    e.preventDefault();
    cancelAnimationFrame(anim);
    const r = cv.getBoundingClientRect();
    const g = goal || { v0: view0, vd: viewDur };
    const unit = e.deltaMode === 1 ? 40 : 1;
    if (e.altKey) {
      // точка под курсором остаётся на месте, как в Premiere
      const fx = (e.clientX - r.left - HEAD) / TW();
      const anchor = g.v0 + fx * g.vd;
      const nd = Math.min(Math.max(g.vd * Math.exp((e.deltaY || e.deltaX) * unit * 0.0022), Math.min(MIN_DUR, total)), total);
      glideTo(anchor - fx * nd, nd);
    } else {
      const d = (Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY) * unit;
      glideTo(g.v0 + (d / TW()) * g.vd, g.vd);
    }
  }, { passive: false });

  // мини-карта как полоса прокрутки
  let mmDrag = null;
  o.mmWrap.addEventListener('pointerdown', (e) => {
    const r = o.mmWrap.getBoundingClientRect();
    const t = (e.clientX - r.left) / r.width * total;
    if (t < view0 || t > view0 + viewDur) { view0 = t - viewDur / 2; request(); }
    mmDrag = { x: e.clientX, v0: view0 };
    o.mmWrap.setPointerCapture(e.pointerId);
  });
  o.mmWrap.addEventListener('pointermove', (e) => {
    if (!mmDrag) return;
    view0 = mmDrag.v0 + (e.clientX - mmDrag.x) / o.mmWrap.getBoundingClientRect().width * total;
    request();
  });
  o.mmWrap.addEventListener('pointerup', () => { mmDrag = null; });
  o.mmWrap.addEventListener('wheel', (e) => { e.preventDefault(); view0 += (e.deltaY || e.deltaX) / MW * total * 0.5; request(); }, { passive: false });
  let zDrag = false;
  const zoomFromSlider = (e) => {
    const r = o.slider.getBoundingClientRect();
    const pc = Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1);
    const nd = total / Math.pow(Math.max(total / Math.min(MIN_DUR, total), 1.0001), pc);
    zoomAround(nd / viewDur, Math.min(Math.max(head, view0), view0 + viewDur), false);
  };
  o.slider.addEventListener('pointerdown', (e) => { zDrag = true; o.slider.setPointerCapture(e.pointerId); zoomFromSlider(e); });
  o.slider.addEventListener('pointermove', (e) => { if (zDrag) zoomFromSlider(e); });
  o.slider.addEventListener('pointerup', () => { zDrag = false; });

  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => setTimeout(() => { readColors(); request(); }, 50));
  readColors();

  return {
    setData(newItems, newTotal, _md, _alt, keepView) {
      const oldTotal = total;
      items = newItems; total = Math.max(newTotal, 0.001);
      if (!keepView || (view0 === 0 && viewDur >= oldTotal - 1e-6)) { view0 = 0; viewDur = total; }
      mmDirty = true;
      request();
    },
    setHead(t, follow) {
      head = t;
      if (follow && !drag && (t > view0 + viewDur * 0.97 || t < view0)) { stopGlide(); view0 = t - viewDur * 0.08; }
      request();
    },
    view() { return { v0: (goal ? goal.v0 : view0), vd: (goal ? goal.vd : viewDur) }; },
    setView(v0, vd) { stopGlide(); cancelAnimationFrame(anim); view0 = v0; viewDur = vd; request(); },
    zoomIn() { zoomAround(0.5, Math.min(Math.max(head, view0), view0 + viewDur), true); },
    zoomOut() { zoomAround(2, Math.min(Math.max(head, view0), view0 + viewDur), true); },
    fit() { animateTo(0, total); },
    reveal(t) { if (t < view0 || t > view0 + viewDur) animateTo(t - viewDur * 0.2, viewDur); },
    theme() { readColors(); request(); },
    setActiveCut(c) { activeCut = c; request(); },
    redraw() { mmDirty = true; request(); },
    cutX(t) { return cv.getBoundingClientRect().left + xOf(t); },
  };
}
