/* Яйцерез — ручной монтаж: куски по порядку (как секвенция в Premiere), операции и история (Ctrl+Z).
   Таймлайн «магнитный»: дыр нет, любое удаление и подрезка сдвигают всё, что правее (ripple). */
'use strict';

const Edit = (() => {
  const FPS = 25;
  const FRAME = 1 / FPS;
  const MIN = 2 * FRAME;               // кусок не короче двух кадров
  const r3 = (x) => Math.round(x * 1000) / 1000;
  const snapF = (x) => Math.round(x * FPS) / FPS;
  const clone = (edl) => edl.map((p) => ({ ...p }));   // у куска могут быть метка цвета (lab) и зум (z)
  let srcDur = () => Infinity;          // длительность исходника клипа (задаётся из приложения)

  function setSourceDurations(fn) { srcDur = fn; }

  /** Разрезать кусок k в момент исходника tSrc. */
  function split(edl, k, tSrc) {
    const p = edl[k];
    if (!p || tSrc <= p.in + MIN || tSrc >= p.out - MIN) return edl;
    const e = clone(edl);
    e.splice(k, 1, { ...p, out: r3(tSrc) }, { ...p, in: r3(tSrc) });
    return e;
  }
  /** Удалить куски со сдвигом (ripple delete). */
  function rippleDelete(edl, ks) {
    const set = new Set(ks);
    return clone(edl).filter((_, i) => !set.has(i));
  }
  /** Начало куска (ripple): всё правее сдвигается. */
  function trimIn(edl, k, newIn) {
    const e = clone(edl), p = e[k];
    if (!p) return edl;
    p.in = r3(Math.min(Math.max(0, newIn), p.out - MIN));
    return e;
  }
  /** Конец куска (ripple). */
  function trimOut(edl, k, newOut) {
    const e = clone(edl), p = e[k];
    if (!p) return edl;
    p.out = r3(Math.max(Math.min(srcDur(p.clip), newOut), p.in + MIN));
    return e;
  }
  /** Rolling: склейка между k и k+1 едет на d, общая длина не меняется. */
  function roll(edl, k, d) {
    const e = clone(edl), a = e[k], b = e[k + 1];
    if (!a || !b) return edl;
    d = Math.max(d, a.in + MIN - a.out, -b.in);
    d = Math.min(d, srcDur(a.clip) - a.out, b.out - MIN - b.in);
    a.out = r3(a.out + d);
    b.in = r3(b.in + d);
    return e;
  }
  /** Slip: содержимое куска сдвигается внутри, место и длина на таймлайне те же. */
  function slip(edl, k, d) {
    const e = clone(edl), p = e[k];
    if (!p) return edl;
    d = Math.max(d, -p.in);
    d = Math.min(d, srcDur(p.clip) - p.out);
    p.in = r3(p.in + d);
    p.out = r3(p.out + d);
    return e;
  }
  /** Slide: кусок едет по таймлайну, соседи слева и справа подстраиваются. */
  function slide(edl, k, d) {
    const e = clone(edl), prev = e[k - 1], next = e[k + 1];
    if (!prev || !next) return edl;
    d = Math.max(d, prev.in + MIN - prev.out, -next.in);
    d = Math.min(d, srcDur(prev.clip) - prev.out, next.out - MIN - next.in);
    prev.out = r3(prev.out + d);
    next.in = r3(next.in + d);
    return e;
  }
  /** Вырезать отрезок таймлайна [g0, g1) со сдвигом (Extract). */
  function extract(edl, g0, g1) {
    if (g1 <= g0) return edl;
    const out = [];
    let t = 0;
    for (const p of edl) {
      const d = p.out - p.in, a = t, b = t + d;
      t = b;
      if (b <= g0 || a >= g1) { out.push({ ...p }); continue; }
      if (a < g0) out.push({ ...p, out: r3(p.in + (g0 - a)) });
      if (b > g1) out.push({ ...p, in: r3(p.in + (g1 - a)) });
    }
    return out.filter((p) => p.out - p.in >= FRAME);
  }
  /** Убрать из монтажа отрезок исходника (фраза, слово). */
  function removeSource(edl, clip, a, b) {
    const out = [];
    for (const p of edl) {
      if (p.clip !== clip || p.out <= a || p.in >= b) { out.push({ ...p }); continue; }
      if (p.in < a - FRAME) out.push({ ...p, out: r3(a) });
      if (p.out > b + FRAME) out.push({ ...p, in: r3(b) });
    }
    return out;
  }
  /** Вставить отрезки исходника на их место по порядку записи (вернуть дубль). */
  function insertSource(edl, ranges) {
    let e = clone(edl);
    for (const [clip, a, b] of ranges) {
      e = removeSource(e, clip, a, b);   // без наложений
      let k = e.findIndex((p) => p.clip > clip || (p.clip === clip && p.in >= a));
      if (k < 0) k = e.length;
      e.splice(k, 0, { clip, in: r3(a), out: r3(b) });
    }
    // соседние куски одного клипа встык — склеиваем
    const out = [];
    for (const p of e) {
      const last = out[out.length - 1];
      if (last && last.clip === p.clip && Math.abs(last.out - p.in) < 0.005 && last.lab === p.lab && JSON.stringify(last.z) === JSON.stringify(p.z)) last.out = p.out;
      else out.push({ ...p });
    }
    return out;
  }
  /** Убрать склейку: два соседних куска одного клипа снова становятся одним (пауза между ними возвращается). */
  function joinCut(edl, k) {
    const a = edl[k], b = edl[k + 1];
    if (!a || !b || a.clip !== b.clip || b.in < a.out - 0.005) return edl;
    const e = clone(edl);
    e.splice(k, 2, { ...a, out: b.out });
    return e;
  }
  /** Поставить свойство (метку, зум) выбранным кускам. */
  function setAttr(edl, ks, key, val) {
    const e = clone(edl);
    for (const k of ks) if (e[k]) { if (val == null) delete e[k][key]; else e[k][key] = val; }
    return e;
  }
  /* Ручная правка поверх нового автомонтажа: что человек убрал — убираем, что вернул — возвращаем.
     Сравниваем по исходнику, поэтому работа сохраняется, даже если склейки сдвинулись от настроек. */
  function ranges(edl) {
    const by = {};
    for (const p of edl) (by[p.clip] = by[p.clip] || []).push([p.in, p.out]);
    for (const c of Object.keys(by)) {
      const arr = by[c].sort((x, y) => x[0] - y[0]), m = [];
      for (const r of arr) { const l = m[m.length - 1]; if (l && r[0] <= l[1] + 0.002) l[1] = Math.max(l[1], r[1]); else m.push([...r]); }
      by[c] = m;
    }
    return by;
  }
  function minus(A, B) {
    const out = [];
    for (const c of Object.keys(A)) {
      const bs = B[c] || [];
      for (const [a0, a1] of A[c]) {
        let cur = a0;
        for (const [b0, b1] of bs) {
          if (b1 <= cur || b0 >= a1) continue;
          if (b0 > cur) out.push([+c, cur, b0]);
          cur = Math.max(cur, b1);
        }
        if (cur < a1) out.push([+c, cur, a1]);
      }
    }
    return out.filter((r) => r[2] - r[1] > 0.03);
  }
  function rebase(oldAuto, manual, newAuto) {
    const RO = ranges(oldAuto), RM = ranges(manual);
    const removed = minus(RO, RM), added = minus(RM, RO);
    let e = clone(newAuto);
    for (const [c, a, b] of removed) e = removeSource(e, c, a, b);
    if (added.length) e = insertSource(e, added);
    // метки и зумы — с тех кусков ручного монтажа, что стоят на том же месте исходника
    for (const p of e) {
      const mid = (p.in + p.out) / 2;
      const m = manual.find((q) => q.clip === p.clip && q.in <= mid && q.out >= mid);
      if (m) for (const [k, v] of Object.entries(m)) if (!['clip', 'in', 'out'].includes(k)) p[k] = v;
    }
    return e.filter((p) => p.out - p.in >= FRAME);
  }
  /** Индекс куска и время исходника в момент таймлайна g. */
  function at(edl, g) {
    let t = 0;
    for (let k = 0; k < edl.length; k++) {
      const d = edl[k].out - edl[k].in;
      if (g < t + d || k === edl.length - 1) return { k, src: edl[k].in + Math.min(Math.max(g - t, 0), d), t0: t };
      t += d;
    }
    return { k: -1, src: 0, t0: 0 };
  }
  function starts(edl) {
    const s = [];
    let t = 0;
    for (const p of edl) { s.push(t); t += p.out - p.in; }
    s.push(t);
    return s;
  }

  /* ---------- история: Ctrl+Z / Ctrl+Shift+Z ---------- */
  const undo = [], redo = [];
  function snapshot(state) { return JSON.stringify(state); }
  function push(state) {
    undo.push(snapshot(state));
    if (undo.length > 300) undo.shift();
    redo.length = 0;
  }
  function back(current) {
    if (!undo.length) return null;
    redo.push(snapshot(current));
    return JSON.parse(undo.pop());
  }
  function forward(current) {
    if (!redo.length) return null;
    undo.push(snapshot(current));
    return JSON.parse(redo.pop());
  }
  function clearHistory() { undo.length = 0; redo.length = 0; }

  return {
    FPS, FRAME, MIN, snapF, setSourceDurations, split, rippleDelete, trimIn, trimOut, roll, slip, slide,
    extract, removeSource, insertSource, joinCut, setAttr, rebase, at, starts, push, back, forward, clearHistory,
    canUndo: () => undo.length > 0, canRedo: () => redo.length > 0,
  };
})();

/* ---------- горячие клавиши: наборы как в Premiere Pro и DaVinci Resolve + свои ---------- */
const Keys = (() => {
  // Клавиши пишем по физическому положению (KeyC и т. п.) — работают и в русской раскладке.
  const ACTIONS = [
    ['play', 'k_play'], ['play_fwd', 'k_play_fwd'], ['stop', 'k_stop'], ['play_back', 'k_play_back'],
    ['frame_back', 'k_frame_back'], ['frame_fwd', 'k_frame_fwd'], ['frames_back', 'k_frames_back'], ['frames_fwd', 'k_frames_fwd'],
    ['prev_edit', 'k_prev_edit'], ['next_edit', 'k_next_edit'], ['go_start', 'k_go_start'], ['go_end', 'k_go_end'],
    ['tool_select', 'k_tool_select'], ['tool_razor', 'k_tool_razor'], ['tool_ripple', 'k_tool_ripple'],
    ['tool_roll', 'k_tool_roll'], ['tool_slip', 'k_tool_slip'],
    ['tool_hand', 'k_tool_hand'], ['snap', 'k_snap'], ['zoom_panel', 'k_zoom_panel'],
    ['label_1', 'k_label_1'], ['label_2', 'k_label_2'], ['label_3', 'k_label_3'], ['label_4', 'k_label_4'], ['label_5', 'k_label_5'], ['label_6', 'k_label_6'], ['label_clear', 'k_label_clear'],
    ['split', 'k_split'], ['ripple_delete', 'k_ripple_delete'], ['trim_start', 'k_trim_start'], ['trim_end', 'k_trim_end'],
    ['mark_in', 'k_mark_in'], ['mark_out', 'k_mark_out'], ['clear_marks', 'k_clear_marks'], ['extract', 'k_extract'],
    ['undo', 'k_undo'], ['redo', 'k_redo'], ['select_all', 'k_select_all'], ['deselect', 'k_deselect'],
    ['zoom_in', 'k_zoom_in'], ['zoom_out', 'k_zoom_out'], ['zoom_fit', 'k_zoom_fit'],
    ['find', 'k_find'], ['export', 'k_export'], ['ui_zoom_in', 'k_ui_zoom_in'], ['ui_zoom_out', 'k_ui_zoom_out'], ['ui_zoom_reset', 'k_ui_zoom_reset'],
    ['save_project', 'k_save_project'], ['save_project_as', 'k_save_project_as'], ['open_project', 'k_open_project'],
  ];
  const PRESETS = {
    premiere: {
      play: ['Space'], play_fwd: ['L'], stop: ['K'], play_back: ['J'],
      frame_back: ['ArrowLeft'], frame_fwd: ['ArrowRight'], frames_back: ['Shift+ArrowLeft'], frames_fwd: ['Shift+ArrowRight'],
      prev_edit: ['ArrowUp'], next_edit: ['ArrowDown'], go_start: ['Home'], go_end: ['End'],
      tool_select: ['V'], tool_razor: ['C'], tool_ripple: ['B'], tool_roll: ['N'], tool_slip: ['Y'],
      tool_hand: ['H'], snap: ['S'], zoom_panel: ['Shift+T'], label_1: ['Alt+1'], label_2: ['Alt+2'], label_3: ['Alt+3'], label_4: ['Alt+4'], label_5: ['Alt+5'], label_6: ['Alt+6'], label_clear: ['Alt+0'],
      split: ['Ctrl+K'], ripple_delete: ['Shift+Delete', 'Delete', 'Backspace'], trim_start: ['Q'], trim_end: ['W'],
      mark_in: ['I'], mark_out: ['O'], clear_marks: ['Ctrl+Shift+X'], extract: ["'"],
      undo: ['Ctrl+Z'], redo: ['Ctrl+Shift+Z'], select_all: ['Ctrl+A'], deselect: ['Ctrl+Shift+A', 'Escape'],
      zoom_in: ['='], zoom_out: ['-'], zoom_fit: ['\\'],
      find: ['Ctrl+F'], export: ['Ctrl+M'], ui_zoom_in: ['Ctrl+='], ui_zoom_out: ['Ctrl+-'], ui_zoom_reset: ['Ctrl+0'],
      save_project: ['Ctrl+S'], save_project_as: ['Ctrl+Shift+S'], open_project: ['Ctrl+O'],
    },
    resolve: {
      play: ['Space'], play_fwd: ['L'], stop: ['K'], play_back: ['J'],
      frame_back: ['ArrowLeft'], frame_fwd: ['ArrowRight'], frames_back: ['Shift+ArrowLeft'], frames_fwd: ['Shift+ArrowRight'],
      prev_edit: ['ArrowUp'], next_edit: ['ArrowDown'], go_start: ['Home'], go_end: ['End'],
      tool_select: ['A'], tool_razor: ['B'], tool_ripple: ['T'], tool_roll: ['U'], tool_slip: ['S'],
      tool_hand: ['H'], snap: ['N'], zoom_panel: ['Shift+T'], label_1: ['Alt+1'], label_2: ['Alt+2'], label_3: ['Alt+3'], label_4: ['Alt+4'], label_5: ['Alt+5'], label_6: ['Alt+6'], label_clear: ['Alt+0'],
      split: ['Ctrl+B', 'Ctrl+\\'], ripple_delete: ['Shift+Delete', 'Delete', 'Backspace'], trim_start: ['Shift+['], trim_end: ['Shift+]'],
      mark_in: ['I'], mark_out: ['O'], clear_marks: ['Alt+X'], extract: ['Shift+Backspace'],
      undo: ['Ctrl+Z'], redo: ['Ctrl+Shift+Z'], select_all: ['Ctrl+A'], deselect: ['Ctrl+Shift+A', 'Escape'],
      zoom_in: ['Ctrl+='], zoom_out: ['Ctrl+-'], zoom_fit: ['Shift+Z'],
      find: ['Ctrl+F'], export: ['Ctrl+Shift+E'], ui_zoom_in: ['Ctrl+Alt+='], ui_zoom_out: ['Ctrl+Alt+-'], ui_zoom_reset: ['Ctrl+Alt+0'],
      save_project: ['Ctrl+S'], save_project_as: ['Ctrl+Shift+S'], open_project: ['Ctrl+O'],
    },
  };
  const CODE = {
    Space: 'Space', Escape: 'Escape', Delete: 'Delete', Backspace: 'Backspace', Home: 'Home', End: 'End', Enter: 'Enter', Tab: 'Tab',
    ArrowLeft: 'ArrowLeft', ArrowRight: 'ArrowRight', ArrowUp: 'ArrowUp', ArrowDown: 'ArrowDown',
    Equal: '=', Minus: '-', NumpadAdd: '=', NumpadSubtract: '-', Backslash: '\\', Quote: "'", Semicolon: ';',
    BracketLeft: '[', BracketRight: ']', Comma: ',', Period: '.', Slash: '/', Backquote: '`',
  };
  function combo(e) {
    let k = CODE[e.code];
    if (!k && /^Key[A-Z]$/.test(e.code)) k = e.code.slice(3);
    if (!k && /^Digit\d$/.test(e.code)) k = e.code.slice(5);
    if (!k && /^Numpad\d$/.test(e.code)) k = e.code.slice(6);
    if (!k && /^F\d+$/.test(e.code)) k = e.code;
    if (!k || ['Control', 'Shift', 'Alt', 'Meta'].includes(e.key)) return null;
    return (e.ctrlKey || e.metaKey ? 'Ctrl+' : '') + (e.altKey ? 'Alt+' : '') + (e.shiftKey ? 'Shift+' : '') + k;
  }
  const pretty = (c) => c.replace('ArrowLeft', '←').replace('ArrowRight', '→').replace('ArrowUp', '↑').replace('ArrowDown', '↓')
    .replace('Space', t('kbd_space')).replace('Backspace', '⌫').replace('Escape', 'Esc');
  let map = {};       // действие → [комбинации]
  let reverse = {};   // комбинация → действие
  function use(presetName, custom) {
    map = presetName === 'custom' && custom ? JSON.parse(JSON.stringify(custom)) : JSON.parse(JSON.stringify(PRESETS[presetName] || PRESETS.premiere));
    reverse = {};
    for (const [a, list] of Object.entries(map)) for (const c of list || []) reverse[c] = a;
  }
  use('premiere');
  return {
    ACTIONS, PRESETS, combo, pretty, use,
    action: (e) => { const c = combo(e); return c ? reverse[c] : null; },
    keysOf: (a) => map[a] || [],
    map: () => JSON.parse(JSON.stringify(map)),
    label: (a) => (map[a] && map[a][0] ? pretty(map[a][0]) : ''),
  };
})();
