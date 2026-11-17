/* Яйцерез — таймлайн на canvas с зумом и мини-картой.
   Рисуется только видимая часть; куски уже пикселя склеиваются, поэтому тысячи фрагментов
   на многочасовом монтаже не тормозят. */
'use strict';

function createTimeline(o) {
  const cv = o.canvas, ctx = cv.getContext('2d');
  const mm = o.mmCanvas, mctx = mm.getContext('2d');
  let items = [], total = 1, mainDur = 0, altStart = null;
  let view0 = 0, viewDur = 1, head = 0, W = 0, H = 0, MW = 0, MH = 0, dpr = 1, hoverT = null, scrub = false;
  let activeCut = null, edgeHover = null, trimDrag = null;
  let colors = {}, dirty = true, mmDirty = true, anim = null;
  const MIN_DUR = 2;
  const RULER = 20;

  function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
  function readColors() {
    colors = {
      clip: [css('--clip-1'), css('--clip-2'), css('--clip-3'), css('--clip-4')],
      alt: css('--alt'), text: css('--text'), text2: css('--text-2'), text3: css('--text-3'),
      border: css('--border'), head: css('--c-red'), bg: css('--bg-callout'), bg2: css('--bg-menu'), label: css('--tl-label'),
    };
    dirty = mmDirty = true;
  }
  const colorOf = (it) => (it.kind === 'alt' ? colors.alt : colors.clip[it.clip % 4]);

  function resize() {
    dpr = window.devicePixelRatio || 1;
    const r = cv.getBoundingClientRect(), m = mm.getBoundingClientRect();
    W = r.width; H = r.height; MW = m.width; MH = m.height;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    mm.width = Math.round(MW * dpr); mm.height = Math.round(MH * dpr);
    dirty = mmDirty = true;
  }
  new ResizeObserver(() => { resize(); request(); }).observe(cv);

  function clampView() {
    viewDur = Math.min(Math.max(viewDur, Math.min(MIN_DUR, total)), total);
    view0 = Math.min(Math.max(view0, 0), Math.max(0, total - viewDur));
  }
  // первый кусок, который заканчивается после t
  function lowerBound(t) {
    let lo = 0, hi = items.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1, it = items[mid];
      if (it.t + (it.out - it.in) < t) lo = mid + 1; else hi = mid;
    }
    return lo;
  }
  function itemAt(t) {
    const i = lowerBound(t);
    const it = items[i];
    return it && t >= it.t && t <= it.t + (it.out - it.in) ? it : null;
  }

  function step(sec) {
    const steps = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600];
    return steps.find((s) => s >= sec) || 7200;
  }
  function clock(t) {
    t = Math.max(0, t);
    const hh = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = Math.floor(t % 60);
    const frac = viewDur < 20 ? '.' + Math.floor((t % 1) * 10) : '';
    return (hh ? `${hh}:${String(m).padStart(2, '0')}` : `${m}`) + `:${String(s).padStart(2, '0')}${frac}`;
  }

  function drawRuns(c, w, y, h, x0v, durv, from, minW) {
    // склейка мелких кусков одного цвета в один прямоугольник
    let rs = -1, re = -1, rc = null;
    const flush = () => { if (rc) { c.fillStyle = rc; c.fillRect(rs, y, Math.max(1, re - rs), h); } };
    for (let i = from; i < items.length; i++) {
      const it = items[i];
      const x0 = (it.t - x0v) / durv * w, x1 = (it.t + it.out - it.in - x0v) / durv * w;
      if (x0 > w) break;
      const col = colorOf(it);
      if (x1 - x0 < minW && col === rc && x0 <= re + 1) { re = Math.max(re, x1); continue; }
      flush();
      rs = x0; re = x1 - (x1 - x0 >= minW ? 1 : 0); rc = col;
    }
    flush();
  }

  function draw() {
    if (!W) return;
    clampView();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    // линейка
    const pxPerSec = W / viewDur;
    const st = step(80 / pxPerSec);
    ctx.font = '11px ui-sans-serif, "Segoe UI", sans-serif';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = colors.text3;
    ctx.strokeStyle = colors.border;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let tt = Math.floor(view0 / st) * st; tt <= view0 + viewDur; tt += st) {
      const x = Math.round((tt - view0) * pxPerSec) + 0.5;
      ctx.moveTo(x, RULER - 6); ctx.lineTo(x, RULER);
      ctx.fillText(clock(tt), x + 4, RULER / 2 - 1);
      const sub = st / 5;
      for (let k = 1; k < 5 && pxPerSec * sub > 6; k++) {
        const xs = Math.round((tt + k * sub - view0) * pxPerSec) + 0.5;
        ctx.moveTo(xs, RULER - 3); ctx.lineTo(xs, RULER);
      }
    }
    ctx.stroke();
    // куски
    const y = RULER + 4, h = H - RULER - 10;
    const from = lowerBound(view0);
    drawRuns(ctx, W, y, h, view0, viewDur, from, 4);
    // подписи на широких кусках
    ctx.fillStyle = colors.label;
    ctx.font = '12px ui-sans-serif, "Segoe UI", sans-serif';
    for (let i = from; i < items.length; i++) {
      const it = items[i];
      const x0 = (it.t - view0) * pxPerSec, x1 = (it.t + it.out - it.in - view0) * pxPerSec;
      if (x0 > W) break;
      if (x1 - x0 < 46) continue;
      const label = o.label(it);
      if (!label) continue;
      ctx.save();
      ctx.beginPath();
      ctx.rect(Math.max(x0, 0) + 6, y, Math.min(x1, W) - Math.max(x0, 0) - 12, h);
      ctx.clip();
      ctx.fillText(label, Math.max(x0, 0) + 6, y + h / 2);
      ctx.restore();
    }
    // разрыв перед запасными
    if (altStart != null) {
      const gx0 = (mainDur - view0) * pxPerSec, gx1 = (altStart - view0) * pxPerSec;
      if (gx1 > 0 && gx0 < W && gx1 - gx0 > 14) {
        ctx.fillStyle = colors.text3;
        ctx.textAlign = 'center';
        ctx.fillText('⋯', (gx0 + gx1) / 2, y + h / 2);
        ctx.textAlign = 'left';
      }
    }
    // склейки: ромбик снизу, если в этом месте что-то вырезано (клик — карточка склейки)
    const cuts = o.cuts ? o.cuts() : [];
    for (const c of cuts) {
      const x = Math.round((c.t - view0) * pxPerSec) + 0.5;
      if (x < -8 || x > W + 8) continue;
      if (c.removed.length) {
        ctx.fillStyle = c === activeCut ? colors.head : colors.text2;
        ctx.beginPath(); ctx.moveTo(x, H - 11); ctx.lineTo(x + 4.5, H - 6); ctx.lineTo(x, H - 1); ctx.lineTo(x - 4.5, H - 6); ctx.fill();
        if (pxPerSec * 2 > 40) {
          ctx.font = '10px ui-sans-serif, "Segoe UI", sans-serif';
          ctx.fillText(String(c.removed.length), x + 7, H - 6);
        }
      }
      if (c === activeCut || c === edgeHover) {
        ctx.fillStyle = colors.head;
        ctx.fillRect(x - 1, y, 2, h);
      }
    }
    if (trimDrag) {
      const gx = Math.round((trimDrag.t0 + trimDrag.delta - view0) * pxPerSec) + 0.5;
      ctx.strokeStyle = colors.head; ctx.setLineDash([3, 3]); ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(gx, RULER); ctx.lineTo(gx, H); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = colors.bg2;
      const lab = (trimDrag.delta >= 0 ? '+' : '−') + Math.abs(trimDrag.delta).toFixed(2);
      ctx.font = '11px ui-sans-serif, "Segoe UI", sans-serif';
      const tw = ctx.measureText(lab).width + 8;
      ctx.fillRect(gx + 4, RULER + 2, tw, 16); ctx.fillStyle = colors.text; ctx.fillText(lab, gx + 8, RULER + 10);
    }
    // курсор мыши — тонкая линия со временем, как в монтажке
    if (hoverT != null && !scrub) {
      const mx = Math.round((hoverT - view0) * pxPerSec) + 0.5;
      ctx.strokeStyle = colors.text3;
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(mx, RULER); ctx.lineTo(mx, H); ctx.stroke();
      const label = clock(hoverT);
      ctx.font = '11px ui-sans-serif, "Segoe UI", sans-serif';
      const tw = ctx.measureText(label).width + 8;
      const lx = Math.min(Math.max(mx - tw / 2, 0), W - tw);
      ctx.fillStyle = colors.bg2;
      ctx.fillRect(lx, 2, tw, RULER - 5);
      ctx.fillStyle = colors.text;
      ctx.fillText(label, lx + 4, RULER / 2 - 1);
    }
    // плейхед
    const hx = Math.round((head - view0) * pxPerSec);
    if (hx >= -2 && hx <= W + 2) {
      ctx.fillStyle = colors.head;
      ctx.fillRect(hx - 1, 0, 2, H);
      ctx.beginPath(); ctx.moveTo(hx - 5, 0); ctx.lineTo(hx + 5, 0); ctx.lineTo(hx, 6); ctx.fill();
    }
  }

  function drawMini() {
    if (!MW) return;
    mctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    mctx.clearRect(0, 0, MW, MH);
    mctx.globalAlpha = 0.85;
    drawRuns(mctx, MW, 3, MH - 6, 0, total, 0, 2);
    mctx.globalAlpha = 1;
  }

  function placeView() {
    o.mmView.style.left = (view0 / total * 100) + '%';
    o.mmView.style.width = `max(8px, ${viewDur / total * 100}%)`;
    const pos = Math.log(total / viewDur) / Math.log(Math.max(total / Math.min(MIN_DUR, total), 1.0001));
    const p = Math.min(Math.max(pos, 0), 1) * 100;
    o.slider.querySelector('.fill').style.width = p + '%';
    o.slider.querySelector('.knob').style.left = p + '%';
  }
  let rq = false;
  function request() {
    if (rq) return;
    rq = true;
    requestAnimationFrame(() => {
      rq = false;
      if (mmDirty) { drawMini(); mmDirty = false; }
      draw();
      placeView();
    });
  }

  function animateTo(v0, vd) {
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
  function zoomAround(factor, tAnchor, smooth) {
    const nd = Math.min(Math.max(viewDur * factor, Math.min(MIN_DUR, total)), total);
    const rel = (tAnchor - view0) / viewDur;
    const n0 = tAnchor - rel * nd;
    if (smooth) animateTo(n0, nd); else { view0 = n0; viewDur = nd; request(); }
  }
  const timeAtX = (x) => view0 + x / W * viewDur;

  // --- мышь на основном таймлайне ---
  cv.addEventListener('wheel', (e) => {
    e.preventDefault();
    cancelAnimationFrame(anim);
    const r = cv.getBoundingClientRect();
    if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
      view0 += (e.shiftKey ? e.deltaY : e.deltaX) / W * viewDur;
      request();
    } else {
      zoomAround(Math.exp(e.deltaY * 0.0018), timeAtX(e.clientX - r.left), false);
    }
    hover(e);
  }, { passive: false });
  const tAtEvent = (e) => { const r = cv.getBoundingClientRect(); return Math.min(Math.max(timeAtX(e.clientX - r.left), 0), total); };
  function cutNear(e, tol) {
    if (!o.cuts) return null;
    const r = cv.getBoundingClientRect(), x = e.clientX - r.left;
    let best = null, bd = tol;
    for (const c of o.cuts()) {
      const d = Math.abs((c.t - view0) / viewDur * W - x);
      if (d <= bd) { bd = d; best = c; }
    }
    return best;
  }
  const canTrim = () => W / viewDur > 25;   // подрезка краёв — когда приблизили (больше 25 px на секунду)
  cv.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    const r = cv.getBoundingClientRect(), y = e.clientY - r.top;
    const near = cutNear(e, 7);
    if (near && y > H - 14) { activeCut = near; o.onCutClick(near, e); request(); return; }
    if (near && canTrim() && y > RULER) {
      const x = e.clientX - r.left, cx = (near.t - view0) / viewDur * W;
      trimDrag = { cut: near, side: x < cx ? 'left' : 'right', x0: e.clientX, t0: near.t, delta: 0 };
      cv.setPointerCapture(e.pointerId);
      request();
      return;
    }
    scrub = true;
    cv.setPointerCapture(e.pointerId);
    o.tip.classList.remove('on');
    o.onScrub(tAtEvent(e));
  });
  cv.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    const it = itemAt(tAtEvent(e));
    if (it && o.onContext) o.onContext(it, e);
  });
  cv.addEventListener('pointermove', (e) => {
    hoverT = tAtEvent(e);
    if (trimDrag) {
      trimDrag.delta = (e.clientX - trimDrag.x0) / W * viewDur;
      request();
      return;
    }
    const r0 = cv.getBoundingClientRect(), y0 = e.clientY - r0.top;
    const near = cutNear(e, 7);
    edgeHover = near && canTrim() && y0 > RULER && y0 <= H - 14 ? near : null;
    cv.style.cursor = near && y0 > H - 14 && near.removed.length ? 'pointer' : edgeHover ? 'col-resize' : '';
    if (scrub) {
      // у края — прокручиваем вид, чтобы можно было тянуть дальше
      const x = e.clientX - cv.getBoundingClientRect().left;
      if (x > W - 20) view0 += viewDur * 0.02; else if (x < 20) view0 -= viewDur * 0.02;
      o.onScrub(tAtEvent(e));
    } else hover(e);
    request();
  });
  const endScrub = (e) => {
    if (trimDrag) {
      const d = trimDrag;
      trimDrag = null;
      if (Math.abs(d.delta) > 0.005) o.onTrim(d.cut, d.side, d.delta);
      request();
      return;
    }
    if (!scrub) return; scrub = false; o.onScrubEnd(tAtEvent(e));
  };
  cv.addEventListener('pointerup', endScrub);
  cv.addEventListener('pointercancel', endScrub);
  cv.addEventListener('pointerleave', () => { o.tip.classList.remove('on'); hoverT = null; request(); });
  function hover(e) {
    const r = cv.getBoundingClientRect();
    const it = itemAt(timeAtX(e.clientX - r.left));
    if (!it || e.clientY - r.top < RULER) { o.tip.classList.remove('on'); return; }
    o.fillTip(o.tip, it);
    o.tip.style.left = Math.min(e.clientX + 12, innerWidth - 340) + 'px';
    o.tip.style.top = (r.top - o.tip.offsetHeight - 8) + 'px';
    o.tip.classList.add('on');
  }

  // --- мини-карта ---
  let mmDrag = null;
  o.mmWrap.addEventListener('pointerdown', (e) => {
    const r = o.mmWrap.getBoundingClientRect();
    const t = (e.clientX - r.left) / r.width * total;
    if (t < view0 || t > view0 + viewDur) { view0 = t - viewDur / 2; request(); }
    mmDrag = { x: e.clientX, v0: view0 };
    o.mmWrap.setPointerCapture(e.pointerId);
    o.mmWrap.classList.add('drag');
  });
  o.mmWrap.addEventListener('pointermove', (e) => {
    if (!mmDrag) return;
    const r = o.mmWrap.getBoundingClientRect();
    view0 = mmDrag.v0 + (e.clientX - mmDrag.x) / r.width * total;
    request();
  });
  o.mmWrap.addEventListener('pointerup', () => { mmDrag = null; o.mmWrap.classList.remove('drag'); });
  o.mmWrap.addEventListener('wheel', (e) => {
    e.preventDefault();
    view0 += (Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY) / MW * total * 0.5;
    request();
  }, { passive: false });

  // --- ползунок масштаба ---
  let zDrag = false;
  const zoomFromSlider = (e) => {
    const r = o.slider.getBoundingClientRect();
    const p = Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1);
    const nd = total / Math.pow(Math.max(total / Math.min(MIN_DUR, total), 1.0001), p);
    zoomAround(nd / viewDur, Math.min(Math.max(head, view0), view0 + viewDur), false);
  };
  o.slider.addEventListener('pointerdown', (e) => { zDrag = true; o.slider.setPointerCapture(e.pointerId); zoomFromSlider(e); });
  o.slider.addEventListener('pointermove', (e) => { if (zDrag) zoomFromSlider(e); });
  o.slider.addEventListener('pointerup', () => { zDrag = false; });

  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => setTimeout(() => { readColors(); request(); }, 50));
  readColors();

  return {
    setData(newItems, newTotal, md, as, keepView) {
      const oldTotal = total;
      items = newItems; total = Math.max(newTotal, 0.001); mainDur = md; altStart = as;
      if (!keepView || view0 === 0 && viewDur >= oldTotal - 1e-6) { view0 = 0; viewDur = total; }
      mmDirty = true;
      request();
    },
    setHead(t, follow) {
      head = t;
      if (follow && (t > view0 + viewDur * 0.97 || t < view0)) {
        view0 = t - viewDur * 0.08;
      }
      request();
    },
    zoomIn() { zoomAround(0.5, Math.min(Math.max(head, view0), view0 + viewDur), true); },
    zoomOut() { zoomAround(2, Math.min(Math.max(head, view0), view0 + viewDur), true); },
    fit() { animateTo(0, total); },
    reveal(t) { if (t < view0 || t > view0 + viewDur) animateTo(t - viewDur * 0.2, viewDur); },
    theme() { readColors(); request(); },
    setActiveCut(c) { activeCut = c; request(); },
    redraw() { request(); },
    viewRange() { return [view0, viewDur, W]; },
    cutX(t) { const r = cv.getBoundingClientRect(); return r.left + (t - view0) / viewDur * W; },
  };
}
