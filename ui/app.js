/* Яйцерез — интерфейс */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'style') el.style.cssText = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(kid));
  return el;
};

const ICON = {
  video: '<svg viewBox="0 0 16 16" width="16" height="16"><rect x="1.5" y="3.5" width="9" height="9" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M10.5 7l4-2.2v6.4l-4-2.2z" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>',
  mic: '<svg viewBox="0 0 16 16" width="16" height="16"><rect x="5.5" y="1.5" width="5" height="8.5" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M3 7.5a5 5 0 0010 0M8 12.5v2" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
  x: '<svg viewBox="0 0 16 16" width="14" height="14"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
  play: '<svg viewBox="0 0 16 16" width="16" height="16"><path d="M4.5 2.8v10.4L13 8z" fill="currentColor"/></svg>',
  pause: '<svg viewBox="0 0 16 16" width="16" height="16"><rect x="3.5" y="2.8" width="3" height="10.4" rx="0.8" fill="currentColor"/><rect x="9.5" y="2.8" width="3" height="10.4" rx="0.8" fill="currentColor"/></svg>',
  chev: '<svg viewBox="0 0 12 12" width="10" height="10"><path d="M3 4.5l3 3 3-3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  check: '<svg viewBox="0 0 12 12" width="11" height="11"><path d="M2.5 6.2l2.3 2.3L9.6 3.6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  sun: '<svg viewBox="0 0 16 16" width="16" height="16"><circle cx="8" cy="8" r="3" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
  moon: '<svg viewBox="0 0 16 16" width="16" height="16"><path d="M13.5 9.5A5.5 5.5 0 016.5 2.5a5.5 5.5 0 107 7z" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>',
  auto: '<svg viewBox="0 0 16 16" width="16" height="16"><circle cx="8" cy="8" r="5.8" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M8 2.2a5.8 5.8 0 010 11.6z" fill="currentColor"/></svg>',
  screen: '<svg viewBox="0 0 16 16" width="16" height="16"><rect x="1.5" y="2.5" width="13" height="9" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M5.5 14h5M8 11.5V14" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
  eye: '<svg viewBox="0 0 16 16" width="15" height="15"><path d="M1.5 8s2.4-4.5 6.5-4.5S14.5 8 14.5 8s-2.4 4.5-6.5 4.5S1.5 8 1.5 8z" fill="none" stroke="currentColor" stroke-width="1.3"/><circle cx="8" cy="8" r="2" fill="currentColor"/></svg>',
  eyeOff: '<svg viewBox="0 0 16 16" width="15" height="15"><path d="M1.5 8s2.4-4.5 6.5-4.5S14.5 8 14.5 8s-2.4 4.5-6.5 4.5S1.5 8 1.5 8z" fill="none" stroke="currentColor" stroke-width="1.3" opacity=".5"/><path d="M3 13L13 3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
  vol: '<svg viewBox="0 0 16 16" width="16" height="16"><path d="M2.5 6h2.2L8 3.2v9.6L4.7 10H2.5z" fill="currentColor"/><path d="M10.3 5.6a3.4 3.4 0 010 4.8M12 3.9a5.8 5.8 0 010 8.2" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
  mute: '<svg viewBox="0 0 16 16" width="16" height="16"><path d="M2.5 6h2.2L8 3.2v9.6L4.7 10H2.5z" fill="currentColor"/><path d="M10.5 6l3.5 4M14 6l-3.5 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
};

/* ---------- мост к Python ---------- */
const MOCKED = /[?&]mock/.test(location.search);
const ready = new Promise((res) => {
  if (window.pywebview && window.pywebview.api) return res();
  window.addEventListener('pywebviewready', () => res());
  if (MOCKED) setTimeout(() => { window.pywebview = { api: Mock.api }; res(); }, 30);
});
async function api(name, ...args) {
  await ready;
  return window.pywebview.api[name](...args);
}

/* ---------- состояние ---------- */
const S = {
  settings: {}, files: [], model: null, version: '', modelState: 'loading', busy: false, busyFrac: 0, cachePath: null,
  analysis: null, plan: null, overrides: {}, wordOverrides: {}, trims: {}, filter: 'all', view: 'files', follow: true,
  ready: [], proxyDone: 0,
};

/* ---------- форматирование ---------- */
const pad2 = (n) => String(n).padStart(2, '0');
function clock(t) {
  t = Math.max(0, t || 0);
  const m = Math.floor(t / 60), s = Math.floor(t % 60);
  return m >= 60 ? `${Math.floor(m / 60)}:${pad2(m % 60)}:${pad2(s)}` : `${m}:${pad2(s)}`;
}
function human(sec) {
  sec = Math.round(sec || 0);
  if (sec < 60) return `${sec} ${t('u_s')}`;
  const m = Math.floor(sec / 60), s = sec % 60;
  if (m < 60) return s ? `${m} ${t('u_min')} ${s} ${t('u_s')}` : `${m} ${t('u_min')}`;
  return `${Math.floor(m / 60)} ${t('u_h')} ${m % 60} ${t('u_min')}`;
}
const secFmt = (v) => (LANG === 'ru' ? v.toFixed(2).replace('.', ',') : v.toFixed(2)) + ' ' + t('sec');

/* ---------- тема и язык ---------- */
const THEMES = ['system', 'light', 'dark'];
function applyTheme(th) {
  const dark = th === 'dark' || (th === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  try { localStorage.setItem('theme', th); } catch (e) { /* нет хранилища */ }
  if (window.TL) TL.theme();
}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => applyTheme(S.settings.theme || 'system'));

function segControl(box, options, value, onPick) {
  box.innerHTML = '';
  for (const [val, label] of options) {
    const b = h('button', { class: val === value ? 'on' : '' }, label);
    b.addEventListener('click', () => { box.querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b)); onPick(val); });
    box.append(b);
  }
}
function renderAppSettings() {
  segControl($('#langSeg'), [['ru', 'Русский'], ['en', 'English']], LANG, (l) => setLang(l, true));
  segControl($('#themeSeg'), THEMES.map((th) => [th, t('theme_' + th)]), S.settings.theme || 'system', (th) => {
    S.settings.theme = th; applyTheme(th); api('save_settings', { theme: th });
  });
  renderModelCallout();
  $('#aboutLine').textContent = t('about', 'v' + (S.version || ''));
}
function fmtBytes(n) {
  const u = LANG === 'ru' ? ['Б', 'КБ', 'МБ', 'ГБ'] : ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0).replace('.', LANG === 'ru' ? ',' : '.')} ${u[i]}`;
}
async function loadCacheInfo() {
  const c = await api('cache_info');
  if (!c) return;
  S.cachePath = c.path;
  $('#cacheDesc').textContent = t('cache_desc', c.path, fmtBytes(c.size));
}
$('#cacheOpen').addEventListener('click', () => S.cachePath && api('open_folder', S.cachePath));
$('#cacheClear').addEventListener('click', async () => {
  const c = await api('clear_cache');
  if (!c) { toast(t('busy_clear'), { error: true }); return; }
  $('#cacheDesc').textContent = t('cache_desc', c.path, fmtBytes(c.size));
  toast(t('cleared'));
});

function setLang(l, save) {
  LANG = l === 'en' ? 'en' : 'ru';
  try { localStorage.setItem('lang', LANG); } catch (e) { /* нет хранилища */ }
  applyStaticText();
  if (save) api('set_lang', LANG);
  // перерисовать всё, что зависит от языка
  renderSettings($('#settings'), SETTINGS_MAIN, onMainSetting);
  renderFiles();
  renderAppSettings();
  renderModelState();
  if (S.cachePath) loadCacheInfo();
  if (S.analysis) {
    renderSettings($('#liveSettings'), SETTINGS_LIVE, onLiveSetting);
    renderResult(true);
  }
  if (S.view === 'progress') renderSteps(true);
}

/* ---------- статус в боковой панели ---------- */
function renderModelState() {
  const el = $('#wstat');
  let st = S.modelState || 'loading', text;
  if (S.busy) { st = 'busy'; text = t('m_busy', Math.round((S.busyFrac || 0) * 100)); }
  else text = t({ loading: 'm_loading', ready: 'm_ready', error: 'm_error' }[st]);
  el.dataset.s = st;
  $('#wstatText').textContent = text;
  el.title = st === 'error' ? (S.modelError || '') : '';
}

/* ---------- окно без рамки: перетаскивание, ресайз, кнопки ---------- */
document.querySelectorAll('.resize').forEach((el) => el.addEventListener('mousedown', (e) => {
  if (e.button !== 0) return; e.preventDefault(); api('win_resize', el.dataset.e);
}));
const NO_DRAG = 'button, input, .item, .menu, a, .seg, .switch';
function dragZone(el) {
  el.addEventListener('mousedown', (e) => {
    if (e.button !== 0 || e.target.closest(NO_DRAG)) return;
    e.preventDefault(); api('win_drag');
  });
  el.addEventListener('dblclick', (e) => { if (!e.target.closest(NO_DRAG)) toggleMax(); });
}
dragZone($('#topbar')); dragZone($('#ws'));
async function toggleMax() {
  const maxed = await api('win_toggle_max');
  document.body.classList.toggle('maxed', !!maxed);
  $('#maxIcon').innerHTML = maxed
    ? '<rect x="2.5" y=".5" width="7" height="7" rx="1.5" fill="none" stroke="currentColor"/><path d="M.5 3v5a1.5 1.5 0 0 0 1.5 1.5h5" fill="none" stroke="currentColor"/>'
    : '<rect x=".5" y=".5" width="9" height="9" rx="1.5" fill="none" stroke="currentColor"/>';
}
document.querySelectorAll('.winctl button').forEach((b) => b.addEventListener('click', () => {
  if (b.dataset.w === 'min') api('win_min');
  if (b.dataset.w === 'max') toggleMax();
  if (b.dataset.w === 'close') api('win_close');
}));

/* ---------- навигация ---------- */
document.querySelectorAll('.nav .item').forEach((it) => it.addEventListener('click', () => {
  const go = it.dataset.go;
  if (go === 'files') show(S.busy ? 'progress' : 'files');
  else if (go === 'result') { if (S.analysis) show('result'); }
  else if (go === 'settings') show('settings');
}));

/* ---------- меню ---------- */
const menu = $('#menu');
function openMenu(anchor, title, items) {
  menu.innerHTML = '';
  if (title) menu.append(h('div', { class: 'menu-title' }, title));
  for (const it of items) {
    const row = h('div', { class: 'menu-item' + (it.on ? ' hl' : '') });
    if (it.icon) row.append(h('span', { html: it.icon, style: 'display:inline-flex;color:var(--text-2)' }));
    row.append(it.tag ? h('span', { class: 'tag ' + it.tag }, it.label) : h('span', {}, it.label));
    if (it.on) row.append(h('span', { class: 'tick', html: ICON.check }));
    else if (it.sub) row.append(h('span', { class: 'sub' }, it.sub));
    row.addEventListener('click', (e) => { e.stopPropagation(); closeMenu(); it.fn(); });
    menu.append(row);
  }
  menu.hidden = false;
  const r = anchor.getBoundingClientRect();
  const mw = menu.offsetWidth, mh = menu.offsetHeight;
  let x = r.left, y = r.bottom + 4;
  if (x + mw > innerWidth - 8) x = Math.max(8, r.right - mw);
  if (y + mh > innerHeight - 8) y = Math.max(8, r.top - mh - 4);
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
  menu.style.animation = 'none'; void menu.offsetWidth; menu.style.animation = '';
}
function closeMenu() { menu.hidden = true; }
document.addEventListener('mousedown', (e) => { if (!menu.hidden && !menu.contains(e.target)) closeMenu(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenu(); });

/* ---------- уведомления ---------- */
function toast(text, opts = {}) {
  const el = h('div', { class: 'toast' + (opts.error ? ' error' : '') }, h('span', {}, text));
  const kill = () => { el.classList.add('out'); setTimeout(() => el.remove(), 220); };
  if (opts.action) el.append(h('button', { onclick: () => { opts.action.fn(); kill(); } }, opts.action.label));
  $('#toasts').append(el);
  setTimeout(kill, opts.ms || 4200);
}

/* ---------- экраны ---------- */
const VIEWS = ['files', 'progress', 'result', 'settings'];
function show(view) {
  if (S.view === view) return;
  S.view = view;
  for (const v of VIEWS) {
    const el = $('#view-' + v);
    if (v === view) { el.hidden = false; el.style.animation = 'none'; void el.offsetWidth; el.style.animation = ''; }
    else el.hidden = true;
  }
  const nav = view === 'progress' ? 'files' : view;
  document.querySelectorAll('.nav .item').forEach((it) => it.classList.toggle('on', it.dataset.go === nav));
  $('#navResult').classList.toggle('disabled', !S.analysis);
  $('#views').scrollTop = 0;
  if (view !== 'result') Player.pause();
  if (view === 'settings') loadCacheInfo();
  if (view === 'result' && window.TL) requestAnimationFrame(() => TL.theme());
}
$('#views').addEventListener('scroll', (e) => $('#topbar').classList.toggle('scrolled', e.target.scrollTop > 4));

/* ---------- настройки ---------- */
const SETTINGS_MAIN = [
  { key: 'remove_silence', type: 'toggle', label: 's_silence', desc: 's_silence_d', children: [
    { key: 'pause', type: 'slider', label: 's_pause', desc: 's_pause_d', min: -0.3, max: 1, step: 0.01, fmt: 'pause', marks: [0] },
    { key: 'equalize', type: 'toggle', label: 's_equal', desc: 's_equal_d', childrenWhenOff: true, children: [
      { key: 'max_pause', type: 'slider', label: 's_max_pause', min: 0.15, max: 2, step: 0.05 },
    ] },
    { key: 'pause_place', type: 'seg', label: 's_place', desc: 's_place_d', options: [['auto', 's_place_auto'], ['tail', 's_place_tail'], ['split', 's_place_split'], ['head', 's_place_head']] },
    { key: 'cut_breaths', type: 'toggle', label: 's_breaths', desc: 's_breaths_d', children: [
      { key: 'breath_sens', type: 'slider', label: 's_bsens', min: 0, max: 1, step: 0.05, fmt: 'pct' },
    ] },
  ] },
  { key: 'drop_bad_takes', type: 'toggle', label: 's_takes', desc: 's_takes_d', children: [
    { key: 'smart_takes', type: 'toggle', label: 's_smart', desc: 's_smart_d' },
    { key: 'keep_alternates', type: 'toggle', label: 's_alts', desc: 's_alts_d' },
    { key: 'prefer_take', type: 'seg', label: 's_prefer', options: [['last', 's_prefer_last'], ['first', 's_prefer_first']] },
  ] },
  { key: 'cut_profanity', type: 'toggle', label: 's_prof', desc: 's_prof_d' },
  { key: 'cut_fillers', type: 'toggle', label: 's_fill', desc: 's_fill_d' },
  { key: 'cut_words', type: 'words', label: 's_words', desc: 's_words_d' },
  { key: 'screen_enabled', type: 'toggle', label: 's_screen', desc: 's_screen_d' },
  { key: 'camera_audio', type: 'select', label: 's_cam', desc: 's_cam_d', options: [['muted', 's_cam_muted'], ['on', 's_cam_on'], ['off', 's_cam_off']] },
  { key: 'keep_silent_clips', type: 'toggle', label: 's_silent', desc: 's_silent_d' },
  { key: 'language', type: 'select', label: 's_lang', options: [['ru', 's_lang_ru'], ['en', 's_lang_en'], ['auto', 's_lang_auto']] },
];
const byKey = (k) => SETTINGS_MAIN.find((d) => d.key === k);
// в окне монтажа — всё, что пересчитывается мгновенно (кроме «понимать перефразы» — это нужно до обработки)
const SETTINGS_LIVE = [
  byKey('remove_silence'),
  { ...byKey('drop_bad_takes'), children: byKey('drop_bad_takes').children.filter((c) => c.key !== 'smart_takes') },
  byKey('cut_profanity'), byKey('cut_fillers'), byKey('cut_words'), byKey('keep_silent_clips'),
];

function wordsEditor(d, onChange) {
  const box = h('div', { class: 'chips' });
  const input = h('input', { class: 'chip-input', placeholder: t('words_add'), spellcheck: 'false' });
  const render = () => {
    box.innerHTML = '';
    for (const w of S.settings[d.key] || []) {
      const x = h('button', { class: 'chip-x', html: ICON.x, title: t('remove') });
      x.addEventListener('click', () => {
        S.settings[d.key] = (S.settings[d.key] || []).filter((z) => z !== w);
        render(); onChange(d.key);
      });
      box.append(h('span', { class: 'chip-word' }, w, x));
    }
    box.append(input);
  };
  input.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ',') return;
    e.preventDefault();
    const v = input.value.trim().toLowerCase();
    if (!v) return;
    const list = S.settings[d.key] || [];
    if (!list.includes(v)) S.settings[d.key] = [...list, v];
    input.value = '';
    render(); input.focus(); onChange(d.key);
  });
  render();
  return box;
}

function renderSettings(box, defs, onChange) {
  box.innerHTML = '';
  const subs = [];
  const build = (parent, list) => {
    for (const d of list) {
      let row;
      const v = S.settings[d.key];
      const text = h('div', { class: 'set-text' }, h('div', { class: 'set-label' }, t(d.label)), d.desc ? h('div', { class: 'set-desc' }, t(d.desc)) : null);
      if (d.type === 'toggle') {
        const sw = h('div', { class: 'switch' + (v ? ' on' : '') });
        row = h('div', { class: 'set-row click' }, text, sw);
        row.addEventListener('click', () => {
          S.settings[d.key] = !S.settings[d.key];
          sw.classList.toggle('on', S.settings[d.key]);
          syncSubs();
          onChange(d.key);
        });
      } else if (d.type === 'slider') {
        row = h('div', { class: 'slider-row' }, text);
        row.append(slider(d, (val, final) => { S.settings[d.key] = val; onChange(d.key, !final); }));
      } else if (d.type === 'seg') {
        const seg = h('div', { class: 'seg' });
        for (const [val, lab] of d.options) {
          const b = h('button', { class: v === val ? 'on' : '' }, t(lab));
          b.addEventListener('click', () => {
            S.settings[d.key] = val;
            seg.querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b));
            onChange(d.key);
          });
          seg.append(b);
        }
        row = h('div', { class: 'set-row' + (d.desc ? ' col' : '') }, text, seg);
      } else if (d.type === 'select') {
        const cur = () => t((d.options.find((o) => o[0] === S.settings[d.key]) || d.options[0])[1]);
        const btn = h('button', { class: 'select' }, h('span', {}, cur()), h('span', { html: ICON.chev }));
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          openMenu(btn, t(d.label), d.options.map(([val, lab]) => ({
            label: t(lab), on: S.settings[d.key] === val,
            fn: () => { S.settings[d.key] = val; btn.firstChild.textContent = t(lab); onChange(d.key); },
          })));
        });
        row = h('div', { class: 'set-row click', onclick: () => btn.click() }, text, btn);
      } else if (d.type === 'words') {
        row = h('div', { class: 'set-row col' }, text, wordsEditor(d, onChange));
      }
      parent.append(row);
      if (d.children) {
        const sub = h('div', { class: 'set-sub' });
        build(sub, d.children);
        parent.append(sub);
        subs.push([d.key, sub, !!d.childrenWhenOff]);
      }
    }
  };
  // раскрытие вложенных блоков: анимируем высоту, а в покое высота не ограничена — так вложенный блок
  // внутри блока не обрезается, когда раскрывается
  const syncSubs = (animate = true) => {
    for (const [key, sub, inverted] of subs) {
      const open = inverted ? !S.settings[key] : !!S.settings[key];
      const isClosed = sub.classList.contains('closed');
      if (open && isClosed) {
        sub.style.maxHeight = animate ? sub.scrollHeight + 'px' : 'none';
        sub.classList.remove('closed');
        if (animate) setTimeout(() => { if (!sub.classList.contains('closed')) sub.style.maxHeight = 'none'; }, 300);
      } else if (!open && !isClosed) {
        sub.style.maxHeight = sub.scrollHeight + 'px';
        void sub.offsetHeight;
        sub.classList.add('closed');
      } else if (open) {
        sub.style.maxHeight = 'none';
      }
    }
  };
  build(box, defs);
  for (const [key, sub, inverted] of subs) {
    const open = inverted ? !S.settings[key] : !!S.settings[key];
    sub.classList.toggle('closed', !open);
    sub.style.maxHeight = open ? 'none' : '0px';
  }
}

function slider(d, onInput) {
  const el = h('div', { class: 'slider' }, h('div', { class: 'track' }), h('div', { class: 'fill' }), h('div', { class: 'knob' }));
  for (const m of d.marks || []) el.append(h('div', { class: 'mark', style: `left:${(m - d.min) / (d.max - d.min) * 100}%` }));
  const val = h('div', { class: 'slider-val' });
  const wrap = h('div', { class: 'slider-wrap' }, el, val);
  const set = (v) => {
    v = Math.min(d.max, Math.max(d.min, Math.round(v / d.step) * d.step));
    v = +v.toFixed(3);
    const p = (v - d.min) / (d.max - d.min) * 100;
    el.querySelector('.fill').style.width = p + '%';
    el.querySelector('.knob').style.left = p + '%';
    val.textContent = d.fmt === 'pct' ? Math.round(v * 100) + '%'
      : d.fmt === 'pause' ? (Math.abs(v) < 0.005 ? t('p_butt') : v < 0 ? t('p_overlap', secFmt(-v)) : secFmt(v))
      : secFmt(v);
    return v;
  };
  let cur = set(S.settings[d.key] ?? d.min);
  const fromEvent = (e) => {
    const r = el.getBoundingClientRect();
    return d.min + (Math.min(Math.max(e.clientX - r.left, 0), r.width) / r.width) * (d.max - d.min);
  };
  const move = (e) => { const v = set(fromEvent(e)); if (v !== cur) { cur = v; onInput(v, false); } };
  el.addEventListener('pointerdown', (e) => { el.setPointerCapture(e.pointerId); el.classList.add('drag'); move(e); });
  el.addEventListener('pointermove', (e) => { if (el.classList.contains('drag')) move(e); });
  el.addEventListener('pointerup', () => { el.classList.remove('drag'); onInput(cur, true); });
  el.addEventListener('wheel', (e) => {
    e.preventDefault();
    const v = set(cur + (e.deltaY < 0 ? d.step : -d.step));
    if (v !== cur) { cur = v; onInput(v, true); }
  }, { passive: false });
  return wrap;
}

/* ---------- экран 1: файлы ---------- */
function renderFiles() {
  const rows = $('#fileRows');
  const has = S.files.length > 0;
  $('#dropEmpty').hidden = has;
  $('#fileTable').hidden = !has;
  rows.innerHTML = '';
  const ORD = { video: 0, screen: 1, audio: 2 };
  const sorted = [...S.files].sort((a, b) => (a.kind === b.kind ? a.name.localeCompare(b.name, undefined, { numeric: true }) : ORD[a.kind] - ORD[b.kind]));
  const frag = document.createDocumentFragment();
  sorted.forEach((f, i) => {
    const KT = { video: ['blue', 'kind_video'], screen: ['purple', 'kind_screen'], audio: ['orange', 'kind_audio'] }[f.kind] || ['gray', 'kind_video'];
    const kindTag = h('span', { class: 'tag click ' + KT[0] }, t(KT[1]));
    kindTag.addEventListener('click', (e) => {
      e.stopPropagation();
      openMenu(kindTag, t('file_type'), [
        { label: t('kind_video'), tag: 'blue', on: f.kind === 'video', fn: () => setKind(f, 'video') },
        { label: t('kind_screen'), tag: 'purple', sub: t('kind_screen_d'), on: f.kind === 'screen', fn: () => setKind(f, 'screen') },
        { label: t('kind_audio'), tag: 'orange', on: f.kind === 'audio', fn: () => setKind(f, 'audio') },
      ]);
    });
    const x = h('button', { class: 'icon-btn x', title: t('remove'), html: ICON.x });
    const row = h('div', { class: 'db-row', style: `animation-delay:${Math.min(i, 12) * 18}ms` },
      h('div', { class: 'name', title: f.path }, h('span', { html: f.kind === 'audio' ? ICON.mic : f.kind === 'screen' ? ICON.screen : ICON.video, style: 'display:inline-flex' }), h('span', { class: 'ell' }, f.name)),
      h('div', {}, kindTag),
      h('div', { class: 'info' }, fileInfo(f) + (f.noaudio && f.kind === 'video' ? ' · ' + t('no_audio') : '')),
      h('div', { class: 'dur' }, clock(f.duration)),
      h('div', {}, x));
    x.addEventListener('click', () => {
      row.classList.add('leaving');
      setTimeout(() => { S.files = S.files.filter((z) => z.id !== f.id); api('remove_file', f.id); renderFiles(); }, 170);
    });
    frag.append(row);
  });
  rows.append(frag);
  const videos = S.files.filter((f) => f.kind === 'video').length;
  const mics = S.files.filter((f) => f.kind === 'audio').length;
  const scrN = S.files.filter((f) => f.kind === 'screen').length;
  const total = S.files.filter((f) => f.kind === 'video').reduce((a, f) => a + f.duration, 0);
  $('#startBtn').disabled = videos === 0;
  $('#startHint').textContent = videos === 0 ? t('hint_none')
    : t('files_hint', videos, mics) + (scrN ? t('hint_screens', scrN) : '') + ' · ' + human(total) + (mics ? '' : t('hint_nomic'));
}
function fileInfo(f) {
  if (f.w == null) return f.info || '';
  if ((f.kind === 'video' || f.kind === 'screen') && !f.noVideo) return `${f.w}×${f.h} · ${+f.fps.toFixed(3)} ${t('u_fps')}`;
  const ch = f.ch === 1 ? t('mono') : f.ch === 2 ? t('stereo') : `${f.ch} ch`;
  return `${(f.sr / 1000).toLocaleString(LANG)} ${t('u_khz')} · ${ch}`;
}
async function setKind(f, kind) {
  if ((kind === 'video' || kind === 'screen') && f.noVideo) { toast(t('no_video_in_file'), { error: true }); return; }
  f.kind = kind;
  await api('set_kind', f.id, kind);
  renderFiles();
}
async function pick() { addResult(await api('pick_files')); }
function addResult(res) {
  $('#dragOverlay').classList.remove('on');
  if (!res) return;
  S.files.push(...res.added);
  renderFiles();
  if (res.added.length) toast(t('added', res.added.length));
  else if (!res.errors.length) toast(t('nothing_added'));
  for (const e of res.errors.slice(0, 3)) toast(e, { error: true });
}
document.querySelectorAll('[data-action="pick"]').forEach((b) => b.addEventListener('click', pick));

// перетаскивание: пути файлов получает Python, здесь только подсветка
let dragDepth = 0;
window.addEventListener('dragenter', (e) => {
  e.preventDefault();
  if (S.view === 'progress') return;
  dragDepth++;
  $('#dragOverlay [data-i]').textContent = t(S.view === 'result' ? 'drop_track' : 'drop_release');
  $('#dragOverlay').classList.add('on');
}, true);
window.addEventListener('dragleave', () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $('#dragOverlay').classList.remove('on'); }, true);
window.addEventListener('dragover', (e) => e.preventDefault(), true);
window.addEventListener('drop', async (e) => {
  e.preventDefault(); dragDepth = 0; $('#dragOverlay').classList.remove('on');
  const files = e.dataTransfer && e.dataTransfer.files;
  if (!files || !files.length) return;
  // WebView2 отдаёт настоящие пути файлов только через это сообщение (как в VoiceType)
  try { window.chrome.webview.postMessageWithAdditionalObjects('FilesDropped', files); } catch (err) { /* обычный браузер */ }
  if (S.view === 'result' && S.analysis) { tracksAdded(await api('add_tracks_dropped')); return; }
  if (S.view !== 'files') show('files');
  addResult(await api('take_dropped'));
}, true);

/* ---------- экран 2: обработка ---------- */
const STEPS = ['sync', 'speech', 'takes'];
const stepState = {};
function renderSteps(keep) {
  const box = $('#steps');
  box.innerHTML = '';
  for (const id of STEPS) {
    const st = keep && stepState[id] || { cls: 'wait', frac: 0, msg: t('st_' + id + '_d') };
    if (!keep) stepState[id] = st;
    box.append(h('div', { class: 'step ' + st.cls, id: 'step-' + id },
      h('div', { class: 'check', html: ICON.check }),
      h('div', { class: 'step-body' }, h('div', { class: 'step-title' }, t('st_' + id)), h('div', { class: 'step-msg' }, st.msg),
        h('div', { class: 'bar' }, h('i', { style: `width:${st.frac * 100}%` })))));
  }
}
async function start() {
  renderSteps(false);
  $('#progressMsg').textContent = t('preparing');
  S.busy = true; S.busyFrac = 0; renderModelState();
  show('progress');
  const ok = await api('start', S.settings);
  if (!ok) toast(t('busy'));
}
$('#startBtn').addEventListener('click', start);
$('#cancelBtn').addEventListener('click', () => { $('#progressMsg').textContent = t('stopping'); api('cancel'); });

/* ---------- экран 3: результат ---------- */
const STATUS_TAG = { main: 'green', alt: 'yellow', bad: 'red' };
const phraseStatus = (p) => (S.plan && S.plan.statuses[p.id]) || p.auto;
function reasonText(p) {
  if (S.overrides[p.id] != null) return t('r_manual');
  const r = p.reason;
  if (!r) return '';
  return t('r_' + r[0], ...r.slice(1));
}

let clipIndex = []; // по клипам: фразы, отсортированные по началу — для быстрого поиска текущей фразы
function indexPhrases() {
  clipIndex = S.analysis.clips.map(() => []);
  for (const p of S.analysis.phrases) clipIndex[p.clip].push(p);
  for (const arr of clipIndex) arr.sort((a, b) => a.start - b.start);
}
function phraseAt(clip, tt) {
  const arr = clipIndex[clip];
  if (!arr) return null;
  let lo = 0, hi = arr.length - 1, best = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (arr[m].start - 0.15 <= tt) { best = m; lo = m + 1; } else hi = m - 1; }
  const p = arr[best];
  return p && tt <= p.end + 0.2 ? p : null;
}

function renderResult(full) {
  const an = S.analysis, plan = S.plan, st = plan.stats;
  const stats = $('#stats');
  stats.innerHTML = '';
  stats.append(
    h('span', {}, t('footage', human(st.original))), h('span', { class: 'arrow' }, '→'), h('b', {}, t('edited', human(st.result))),
    h('span', { class: 'arrow' }, '·'),
    h('span', { class: 'tag green' }, t('n_main', st.main)),
    st.alt ? h('span', { class: 'tag yellow' }, t('n_alt', st.alt)) : null,
    st.bad ? h('span', { class: 'tag red' }, t('n_bad', st.bad)) : null,
  );
  const bad = an.clips.filter((c) => !c.sync.ok);
  const w = $('#syncWarn');
  if (an.mics.length && bad.length) {
    w.hidden = false;
    w.innerHTML = '';
    w.append(h('span', { class: 'emoji' }, '⚠️'), h('div', {}, h('b', {}, t('unsynced')), bad.map((c) => c.name).join(', '), h('div', {}, t('unsynced_d'))));
  } else w.hidden = true;
  const lg = $('#tlLegend');
  lg.innerHTML = '';
  const used = [...new Set(plan.timeline.filter((x) => x.kind === 'main').map((x) => x.clip))];
  for (const c of used.slice(0, 5)) lg.append(h('span', {}, h('i', { style: `background:var(--clip-${(c % 4) + 1})` }), an.clips[c].name));
  if (used.length > 5) lg.append(h('span', { class: 'more' }, `+${used.length - 5}`));
  if (plan.alt_start != null) lg.append(h('span', {}, h('i', { style: 'background:var(--alt)' }), t('alt_tl')));
  computeCuts();
  TL.setData(plan.timeline, plan.duration, plan.main_duration, plan.alt_start, !full);
  Player.setPlan(plan);
  renderProxyNote();
  renderTracks();
  if (full) buildPhrases(); else updatePhrases();
  refreshCutCard();
}

/* ---------- склейки: где что вырезано ---------- */
let CUTS = [];
function computeCuts() {
  CUTS = [];
  const its = S.plan.timeline.filter((x) => x.kind === 'main');
  for (let k = 0; k + 1 < its.length; k++) {
    const a = its[k], b = its[k + 1];
    const removed = [];
    if (a.phrases.length && b.phrases.length) {
      const lo = Math.max(...a.phrases), hi = Math.min(...b.phrases);
      for (let id = lo + 1; id < hi; id++) {
        const p = S.analysis.phrases[id];
        if (p && phraseStatus(p) !== 'main') removed.push(id);
      }
    }
    CUTS.push({ t: b.t, a, b, removed, key: (a.ko || '') + '|' + (b.ki || '') });
  }
}

/* ---------- карточка склейки: подрезка краёв и вырезанные дубли ---------- */
let cutOpen = null;
const FRAME = 0.04;
function closeCutCard() { cutOpen = null; $('#cutCard').hidden = true; if (window.TL) TL.setActiveCut(null); }
function refreshCutCard() {
  if (!cutOpen) return;
  // остаёмся на той склейке, где лежат ещё не возвращённые варианты из открытой карточки
  const prev = new Set(cutOpen.removed);
  let c = null, best = 0;
  for (const x of CUTS) { const n = x.removed.filter((id) => prev.has(id)).length; if (n > best) { best = n; c = x; } }
  c = c || CUTS.find((x) => x.key === cutOpen.key) || CUTS.find((x) => x.a.ko === cutOpen.a.ko);
  if (!c) { closeCutCard(); return; }
  openCutCard(c);
}
function trimFmt(v) { return (v > 0 ? '+' : v < 0 ? '−' : '') + secFmt(Math.abs(v || 0)); }
function setTrim(key, delta) {
  if (!key) return;
  const v = +((S.trims[key] || 0) + delta).toFixed(3);
  if (Math.abs(v) < 0.001) delete S.trims[key]; else S.trims[key] = v;
  replan();
}
function openCutCard(c, ev) {
  cutOpen = c;
  TL.setActiveCut(c);
  const card = $('#cutCard');
  card.innerHTML = '';
  const close = h('button', { class: 'icon-btn', html: ICON.x, title: t('close') });
  close.addEventListener('click', closeCutCard);
  card.append(h('div', { class: 'cc-head' }, h('b', {}, t('cut_title', clock(c.t))), close));
  const trimRow = (label, key) => {
    const val = h('span', { class: 'cc-val' }, trimFmt(S.trims[key] || 0));
    const minus = h('button', { class: 'btn btn-secondary btn-sm', title: t('frame_hint') }, '−');
    const plus = h('button', { class: 'btn btn-secondary btn-sm', title: t('frame_hint') }, '+');
    minus.addEventListener('click', (e) => setTrim(key, -(e.shiftKey ? 5 : 1) * FRAME));
    plus.addEventListener('click', (e) => setTrim(key, (e.shiftKey ? 5 : 1) * FRAME));
    return h('div', { class: 'cc-row' }, h('span', { class: 'cc-label' }, label), minus, val, plus);
  };
  card.append(trimRow(t('cut_left'), c.a.ko), trimRow(t('cut_right'), c.b.ki));
  const listen = h('button', { class: 'btn btn-secondary btn-sm' }, h('span', { html: ICON.play, style: 'display:inline-flex' }), t('cut_listen'));
  listen.addEventListener('click', () => { Player.seek(Math.max(0, c.t - 2), true); Player.forcePlay(); });
  const reset = h('button', { class: 'btn btn-ghost btn-sm' }, t('cut_reset'));
  reset.addEventListener('click', () => { delete S.trims[c.a.ko]; delete S.trims[c.b.ki]; replan(); });
  card.append(h('div', { class: 'cc-actions' }, listen, reset));
  if (c.removed.length) {
    const playAll = h('button', { class: 'chip' }, t('cut_play_all'));
    playAll.addEventListener('click', () => Player.playQueue(c.removed.map((id) => S.analysis.phrases[id])));
    card.append(h('div', { class: 'cc-sub' }, h('span', {}, t('cut_removed', c.removed.length)), playAll));
    const list = h('div', { class: 'cc-list' });
    for (const id of c.removed) {
      const p = S.analysis.phrases[id];
      const st = phraseStatus(p);
      const play = h('button', { class: 'icon-btn', html: ICON.play, title: t('wm_play') });
      play.addEventListener('click', () => Player.playPhrase(p));
      const tag = h('span', { class: 'tag click ' + STATUS_TAG[st] }, t('status_' + st));
      tag.addEventListener('click', (e) => { e.stopPropagation(); statusMenu(tag, p); });
      const back = h('button', { class: 'btn btn-secondary btn-sm' }, t('restore'));
      back.addEventListener('click', () => { if (p.auto === 'main') delete S.overrides[p.id]; else S.overrides[p.id] = 'main'; replan(); });
      list.append(h('div', { class: 'cc-item' }, play,
        h('div', { class: 'cc-text' }, h('div', {}, p.words.map((w) => w[0]).join(' ')), h('div', { class: 'why' }, tag, ' ', reasonText(p))),
        back));
    }
    card.append(list);
  } else card.append(h('div', { class: 'hint cc-empty' }, t('cut_nothing')));
  card.hidden = false;
  const x = TL.cutX(c.t), r = $('#timeline').getBoundingClientRect();
  const cw = card.offsetWidth, ch = card.offsetHeight;
  card.style.left = Math.min(Math.max(8, x - cw / 2), innerWidth - cw - 8) + 'px';
  card.style.top = Math.max(8, r.top - ch - 10) + 'px';
}
document.addEventListener('mousedown', (e) => {
  if (cutOpen && !$('#cutCard').contains(e.target) && !$('#tlCanvas').contains(e.target) && !$('#menu').contains(e.target)) closeCutCard();
});

/* ---------- дорожки ---------- */
function renderTracks() {
  const box = $('#tracks');
  box.innerHTML = '';
  const an = S.analysis;
  const byTrack = {};
  for (const [i, sc] of (an.screens || []).entries()) (byTrack[sc.track || 0] = byTrack[sc.track || 0] || []).push([i, sc]);
  const row = (label, names, eye, extra) => h('div', { class: 'track-row' }, h('span', { class: 'track-v' }, label), h('span', { class: 'track-names' }, names), extra || null, eye || null);
  box.append(row('V1', an.clips.map((c) => c.name).join(', ')));
  for (const tr of Object.keys(byTrack).map(Number).sort((a, b) => a - b)) {
    const list = byTrack[tr];
    const shown = S.settings.show_track === tr;
    const eye = h('button', { class: 'icon-btn eye' + (shown ? ' on' : ''), html: shown ? ICON.eye : ICON.eyeOff, title: t('track_show') });
    eye.addEventListener('click', () => {
      S.settings.show_track = shown ? -1 : tr;
      api('save_settings', { show_track: S.settings.show_track });
      renderTracks();
    });
    const bad = list.filter(([, sc]) => !sc.sync.ok).map(([, sc]) => sc.name);
    const note = bad.length ? h('span', { class: 'track-warn', title: t('track_unsynced') }, '⚠ ' + bad.join(', ')) : null;
    box.append(row('V' + (tr + 2), list.map(([, sc]) => sc.name).join(', '), eye, note));
  }
  const add = h('button', { class: 'db-add track-add' }, h('span', {}, '＋'), t('add_track'));
  add.addEventListener('click', async () => { add.disabled = true; tracksAdded(await api('add_tracks')); add.disabled = false; });
  box.append(add);
}
function tracksAdded(res) {
  $('#dragOverlay').classList.remove('on');
  if (!res || !res.added || !res.added.length) return;
  S.analysis.screens = res.screens;
  if (res.plan) { S.plan = res.plan; renderResult(false); }
  const ok = res.added.filter((a) => a.ok), bad = res.added.filter((a) => !a.ok);
  if (ok.length) {
    const tr = ok[ok.length - 1].track;
    S.settings.show_track = tr;
    api('save_settings', { show_track: tr });
    renderTracks();
    toast(t('track_added', ok.map((a) => a.name).join(', '), tr + 2));
  }
  if (bad.length) toast(t('track_unsynced') + ': ' + bad.map((a) => a.name).join(', '), { error: true, ms: 8000 });
}

/* ---------- правая колонка: вкладки ---------- */
document.querySelectorAll('.side-tab').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('.side-tab').forEach((x) => x.classList.toggle('on', x === b));
  $('#paneText').classList.toggle('on', b.dataset.tab === 'text');
  $('#paneSettings').classList.toggle('on', b.dataset.tab === 'settings');
}));
/* текст как в Spotify: список сам едет за воспроизведением; если листаете сами — ждёт 4 секунды */
let userScrollUntil = 0;
['wheel', 'pointerdown', 'touchstart', 'keydown'].forEach((ev) => $('#phraseScroll').addEventListener(ev, () => { userScrollUntil = performance.now() + 4000; }, { passive: true }));
$('#followBtn').addEventListener('click', () => { S.follow = !S.follow; $('#followBtn').classList.toggle('on', S.follow); if (S.follow) followNow(true); });
function scrollRowIntoView(row, smooth = true) {
  const box = $('#phraseScroll');
  const top = row.offsetTop - box.clientHeight / 2 + row.offsetHeight / 2;
  box.scrollTo({ top: Math.max(0, top), behavior: smooth ? 'smooth' : 'auto' });
}
function followNow(force) {
  const id = Player.currentPhrase();
  if (id == null || (!force && (!S.follow || performance.now() < userScrollUntil))) return;
  const r = rowById.get(id);
  if (r && !r.row.hidden) scrollRowIntoView(r.row);
}

/* список фраз: строится один раз, при пересчёте обновляются только изменившиеся строки и слова */
const rowById = new Map();
let wordEls = [];       // глобальный индекс слова → <span>
let cutShown = {};      // какие слова сейчас показаны вырезанными
const normW = (w) => w.toLowerCase().replace(/ё/g, 'е').replace(/[^\p{L}\p{N}*-]+/gu, '');
function wordReason(r) { return t('wc_' + r); }

function buildPhrases() {
  const box = $('#phrases');
  box.innerHTML = '';
  rowById.clear();
  wordEls = [];
  cutShown = {};
  const frag = document.createDocumentFragment();
  const many = S.analysis.phrases.length > 150;
  S.analysis.phrases.forEach((p, n) => {
    const tag = h('span', { class: 'tag click' });
    tag.addEventListener('click', (e) => { e.stopPropagation(); statusMenu(tag, p); });
    const words = h('span', { class: 'words' });
    p.words.forEach(([wd], k) => {
      const el = h('span', { class: 'w', 'data-wi': p.w0 + k }, wd);
      wordEls[p.w0 + k] = el;
      words.append(el, ' ');
    });
    const why = h('span', { class: 'why' });
    const row = h('div', { class: 'phrase', 'data-id': p.id, style: many ? null : `animation-delay:${Math.min(n, 20) * 12}ms` },
      h('div', { class: 'ts', title: S.analysis.clips[p.clip].name }, clock(p.start)),
      h('div', {}, tag, p.takes > 1 ? h('span', { class: 'tag gray take', title: t('take_no') }, `${p.take}/${p.takes}`) : null),
      h('div', { class: 'txt' }, words, why));
    if (many) row.classList.add('noanim');
    rowById.set(p.id, { row, tag, why, st: null, why_s: null, p });
    frag.append(row);
  });
  box.append(frag);
  box.append(h('div', { class: 'hint empty-hint', id: 'phrasesEmpty' }));
  applySearch();
  updatePhrases();
}

// клик по слову — играть с этого места, по строке — играть фразу; правая кнопка по слову — меню
$('#phrases').addEventListener('click', (e) => {
  const row = e.target.closest('.phrase');
  if (!row || e.target.closest('.tag')) return;
  const r = rowById.get(+row.dataset.id);
  const w = e.target.closest('.w');
  if (w) Player.playPhrase(r.p, +w.dataset.wi);
  else Player.playPhrase(r.p);
});
$('#phrases').addEventListener('contextmenu', (e) => {
  const w = e.target.closest('.w');
  if (!w) return;
  e.preventDefault();
  const wi = +w.dataset.wi;
  const row = rowById.get(+w.closest('.phrase').dataset.id);
  const text = normW(w.textContent);
  const isCut = !!(S.plan.cut_words || {})[wi];
  const items = [];
  if (isCut) items.push({ label: t('wm_keep'), fn: () => { S.wordOverrides[wi] = 'keep'; replan(); } });
  else items.push({ label: t('wm_cut'), fn: () => { S.wordOverrides[wi] = 'cut'; replan(); } });
  if (S.wordOverrides[wi] != null) items.push({ label: t('wm_reset'), fn: () => { delete S.wordOverrides[wi]; replan(); } });
  if (text) items.push({ label: t('wm_cut_all', text), fn: () => addCutWord(text) });
  items.push({ label: t('wm_play'), fn: () => Player.playPhrase(row.p, wi) });
  openMenu(w, `«${w.textContent.replace(/[.,!?…«»]/g, '')}»`, items);
});
function addCutWord(word) {
  const list = S.settings.cut_words || [];
  if (!list.includes(word)) S.settings.cut_words = [...list, word];
  renderSettings($('#liveSettings'), SETTINGS_LIVE, onLiveSetting);
  replan();
  toast(t('word_added', word));
}

/* поиск по фразам */
let searchHits = [];   // id фраз с совпадениями
let hitWords = [];     // подсвеченные слова
let searchPos = -1;
function applySearch() {
  for (const el of hitWords) el.classList.remove('hit');
  hitWords = [];
  searchHits = [];
  searchPos = -1;
  const q = ($('#searchInput').value || '').trim();
  const qt = q.split(/\s+/).map(normW).filter(Boolean);
  if (qt.length) {
    for (const p of S.analysis.phrases) {
      const toks = p.words.map(([wd]) => normW(wd));
      let found = false;
      for (let i = 0; i + qt.length <= toks.length; i++) {
        let ok = true;
        for (let j = 0; j < qt.length && ok; j++) {
          const last = j === qt.length - 1;
          ok = last ? toks[i + j].startsWith(qt[j]) : toks[i + j] === qt[j];
        }
        if (ok) {
          found = true;
          for (let j = 0; j < qt.length; j++) { const el = wordEls[p.w0 + i + j]; if (el) { el.classList.add('hit'); hitWords.push(el); } }
        }
      }
      if (found) searchHits.push(p.id);
    }
  }
  renderSearchBar(q);
}
function renderSearchBar(q) {
  const bar = $('#searchActions');
  bar.innerHTML = '';
  $('#searchClear').hidden = !q;
  if (!q) { $('#searchCount').textContent = ''; return; }
  $('#searchCount').textContent = searchHits.length ? t('found', searchHits.length) : t('not_found');
  if (!searchHits.length) return;
  const allRemoved = searchHits.every((id) => S.overrides[id] === 'bad');
  const word = q.trim().toLowerCase();
  if (allRemoved) bar.append(h('button', { class: 'btn btn-secondary btn-sm', onclick: () => { for (const id of searchHits) delete S.overrides[id]; replan(); } }, t('restore_phrases')));
  else bar.append(h('button', { class: 'btn btn-secondary btn-sm', onclick: () => { for (const id of searchHits) S.overrides[id] = 'bad'; replan(); } }, t('remove_phrases', searchHits.length)));
  bar.append(h('button', { class: 'btn btn-secondary btn-sm', onclick: () => addCutWord(word) }, t('cut_word_all', word)));
}
function jumpToHit(dir) {
  if (!searchHits.length) return;
  const visible = searchHits.filter((id) => !rowById.get(id).row.hidden);
  if (!visible.length) return;
  searchPos = (searchPos + dir + visible.length) % visible.length;
  const r = rowById.get(visible[searchPos]);
  userScrollUntil = performance.now() + 4000;
  scrollRowIntoView(r.row);
  flash(r.row);
  $('#searchCount').textContent = t('found_pos', searchPos + 1, visible.length);
}
function flash(row) { row.classList.remove('flash'); void row.offsetWidth; row.classList.add('flash'); }
let searchTimer = null;
$('#searchInput').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { applySearch(); updatePhrases(); }, 120); });
$('#searchInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); jumpToHit(e.shiftKey ? -1 : 1); }
  else if (e.key === 'Escape') { $('#searchInput').value = ''; applySearch(); updatePhrases(); }
});
$('#searchClear').addEventListener('click', () => { $('#searchInput').value = ''; applySearch(); updatePhrases(); $('#searchInput').focus(); });

function updatePhrases() {
  const an = S.analysis;
  const counts = { all: an.phrases.length, main: 0, alt: 0, bad: 0 };
  let visible = 0;
  const hitSet = new Set(searchHits);
  const searching = !!($('#searchInput').value || '').trim();
  for (const p of an.phrases) {
    const st = phraseStatus(p);
    counts[st]++;
    const r = rowById.get(p.id);
    if (!r) continue;
    if (r.st !== st) {
      r.row.classList.remove('main', 'alt', 'bad');
      r.row.classList.add(st);
      r.tag.className = 'tag click ' + STATUS_TAG[st];
      r.tag.textContent = t('status_' + st);
      r.st = st;
    }
    const why = reasonText(p);
    if (r.why_s !== why) {
      r.why.textContent = why;
      r.why.classList.toggle('manual', S.overrides[p.id] != null);
      r.why.hidden = !why;
      r.why_s = why;
    }
    const show = (S.filter === 'all' || S.filter === st) && (!searching || hitSet.has(p.id));
    r.row.hidden = !show;
    if (show) visible++;
  }
  // вырезанные слова — только изменения
  const cw = (S.plan && S.plan.cut_words) || {};
  for (const k of Object.keys(cutShown)) {
    if (!cw[k]) { const el = wordEls[k]; if (el) { el.classList.remove('cut', 'manual'); el.title = ''; } delete cutShown[k]; }
  }
  for (const [k, why] of Object.entries(cw)) {
    if (cutShown[k] === why) continue;
    const el = wordEls[k];
    if (!el) continue;
    el.classList.add('cut');
    el.classList.toggle('manual', why === 'manual');
    el.title = wordReason(why);
    cutShown[k] = why;
  }
  const f = $('#phraseFilter');
  f.innerHTML = '';
  for (const k of ['all', 'main', 'alt', 'bad']) {
    const c = h('button', { class: 'chip' + (S.filter === k ? ' on' : '') }, t('f_' + k), h('span', { class: 'n' }, counts[k]));
    c.addEventListener('click', () => { S.filter = k; updatePhrases(); });
    f.append(c);
  }
  const empty = $('#phrasesEmpty');
  if (empty) { empty.hidden = visible > 0; empty.textContent = an.phrases.length ? t('empty') : t('no_speech'); }
  if (searching) renderSearchBar(($('#searchInput').value || '').trim());
}

function statusMenu(anchor, p) {
  const cur = phraseStatus(p);
  const items = ['main', 'alt', 'bad'].map((k) => ({
    label: t('status_' + k), tag: STATUS_TAG[k], on: cur === k,
    fn: () => { if (k === p.auto) delete S.overrides[p.id]; else S.overrides[p.id] = k; replan(); },
  }));
  if (S.overrides[p.id] != null) items.push({ label: t('status_reset', t('status_' + p.auto)), fn: () => { delete S.overrides[p.id]; replan(); } });
  openMenu(anchor, t('status_title'), items);
}

let replanTimer = null, replanSeq = 0, replanBusy = false, replanAgain = false;
function replan(delay = 0) {
  clearTimeout(replanTimer);
  replanTimer = setTimeout(run, delay);
  async function run() {
    if (replanBusy) { replanAgain = true; return; }
    replanBusy = true;
    const seq = ++replanSeq;
    try {
      const plan = await api('replan', S.settings, S.overrides, S.wordOverrides, S.trims);
      if (seq === replanSeq && plan) { S.plan = plan; renderResult(false); }
    } finally {
      replanBusy = false;
      if (replanAgain) { replanAgain = false; run(); }
    }
  }
}

$('#backBtn').addEventListener('click', () => { show('files'); renderSettings($('#settings'), SETTINGS_MAIN, onMainSetting); });
$('#exportBtn').addEventListener('click', async () => {
  const path = await api('export');
  if (path) toast(t('saved'), { action: { label: t('show_folder'), fn: () => api('reveal', path) }, ms: 7000 });
});

function renderProxyNote() {
  if (!S.analysis) return;
  const clips = S.analysis.clips;
  const light = S.settings.preview_quality === 'light';
  const n = light ? clips.filter((c) => c.lightReady).length : S.ready.filter(Boolean).length;
  $('#proxyNote').textContent = n < clips.length ? t(light ? 'light_progress' : 'proxies', n, clips.length) : '';
  const hasScreens = false;  // дорожки теперь — в списке под таймлайном
  $('#screenBtn').hidden = true;
  if (hasScreens) {
    $('#screenBtn').innerHTML = '';
    $('#screenBtn').classList.toggle('on', !!S.settings.show_screen);
    $('#screenBtn').append(h('span', { html: ICON.screen, style: 'display:inline-flex' }), h('span', {}, t(S.settings.show_screen ? 'screen_on' : 'screen_off')));
  }
  $('#qualityBtn').innerHTML = '';
  $('#qualityBtn').append(h('span', {}, t(light ? 'q_light' : 'q_orig')), h('span', { html: ICON.chev }));
}
$('#screenBtn').addEventListener('click', () => {
  S.settings.show_screen = !S.settings.show_screen;
  api('save_settings', { show_screen: S.settings.show_screen });
  renderProxyNote();
});
$('#qualityBtn').addEventListener('click', (e) => {
  e.stopPropagation();
  const cur = S.settings.preview_quality || 'original';
  openMenu($('#qualityBtn'), t('q_title'), [
    { label: t('q_orig'), sub: t('q_orig_d'), on: cur === 'original', fn: () => setQuality('original') },
    { label: t('q_light'), sub: t('q_light_d'), on: cur === 'light', fn: () => setQuality('light') },
  ]);
});
async function setQuality(q) {
  S.settings.preview_quality = q;
  await api('set_quality', q);
  renderProxyNote();
  Player.reloadCurrent();
  if (q === 'light' && S.analysis && S.analysis.clips.some((c) => c.direct && !c.lightReady)) toast(t('light_wait'), { ms: 6000 });
}

/* ---------- плеер: склейка кусков на лету ----------
   Две «деки» (видео + звук микрофона), пока одна играет, вторая готовит следующий клип.
   Видео, которое браузер умеет сам, идёт прямо из исходника без звука, а звук микрофона —
   отдельной лёгкой дорожкой, синхронизированной с видео. */
const Player = (() => {
  const decks = [{ v: $('#vidA'), a: $('#audA') }, { v: $('#vidB'), a: $('#audB') }];
  let active = 0, items = [], idx = 0, playing = false, total = 0, mode = 'plan', srcRange = null, pending = 0;
  let waitingFor = null, waitArgs = null, lastGlobal = 0, lastHl = null;
  let scrubbing = false, lastScrubSeek = 0, volume = 1, muted = false, queue = [];
  const cur = () => decks[active], other = () => decks[1 - active];
  const sep = (d) => d.v.dataset.sep === '1';
  const light = () => S.settings.preview_quality === 'light';
  const aOff = (d) => +(d.v.dataset.aoff || 0);   // время в записи микрофона = время видео + смещение
  const aTime = (d, tt) => Math.max(0, tt + aOff(d));

  function applyVolume() {
    for (const d of decks) {
      d.a.volume = muted ? 0 : volume;
      d.v.volume = muted ? 0 : volume;
      d.v.muted = sep(d) || muted;
      d.a.preservesPitch = true;
    }
  }
  function load(d, clip) {
    return new Promise((res) => {
      const c0 = S.analysis.clips[clip];
      const want = String(clip) + (light() && c0.direct && c0.lightReady ? 'L' : '');
      if (d.v.dataset.key === want && d.v.readyState >= 1) return res(true);
      const c = S.analysis.clips[clip];
      const useLight = light() && c.direct && c.lightReady;   // лёгкая копия: звук уже внутри файла
      const key = String(clip) + (useLight ? 'L' : '');
      d.v.dataset.clip = String(clip);
      d.v.dataset.key = key;
      d.v.dataset.sep = c.sepAudio && !useLight ? '1' : '0';
      d.v.dataset.aoff = String(c.aOff || 0);
      d.v.src = MOCKED ? '' : (useLight ? `/light/${clip}` : `/media/${clip}`);
      if (d.v.dataset.sep === '1' && !MOCKED) d.a.src = `/audio/${clip}`; else { d.a.pause(); d.a.removeAttribute('src'); }
      applyVolume();
      const done = (ok) => { d.v.removeEventListener('loadedmetadata', okH); d.v.removeEventListener('error', errH); res(ok); };
      const okH = () => done(true), errH = () => done(false);
      d.v.addEventListener('loadedmetadata', okH);
      d.v.addEventListener('error', errH);
      if (MOCKED) setTimeout(okH, 10);
    });
  }
  function setTime(d, tt) {
    d.v.currentTime = tt;
    if (sep(d)) d.a.currentTime = aTime(d, tt);
  }
  function playDeck(d) {
    d.v.play().catch(() => {});
    if (sep(d)) {
      // звук заранее выставлен на нужное место — не дёргаем его лишней перемоткой
      const want = aTime(d, d.v.currentTime);
      if (Math.abs(d.a.currentTime - want) > 0.04) d.a.currentTime = want;
      d.a.play().catch(() => {});
    }
  }
  function pauseDeck(d) { d.v.pause(); d.a.pause(); }
  function wait(clip, on) {
    $('#playerWait').classList.toggle('on', on);
    $('#playerWaitText').textContent = t('preview_wait');
    waitingFor = on ? clip : null;
  }
  async function goto(clip, tt, play) {
    const my = ++pending;
    prep = null;
    if (!S.ready[clip]) { pauseDeck(cur()); wait(clip, true); waitArgs = [clip, tt, play]; return; }
    wait(null, false);
    let d = cur();
    if (d.v.dataset.clip !== String(clip)) {
      d = other();
      await load(d, clip);
      if (my !== pending) return;
      setTime(d, tt);
      pauseDeck(cur());
      active = 1 - active;
      decks.forEach((x, i) => x.v.classList.toggle('active', i === active));
    } else {
      setTime(d, tt);
    }
    if (play) playDeck(d);
  }
  /* Двойная буферизация: пока играет текущий кусок, вторая дека заранее встаёт на начало следующей
     склейки (видео и звук) и ждёт. На склейке деки меняются местами мгновенно — без ожидания перемотки. */
  let prep = null;   // { k: индекс куска, ready: дека уже перемоталась }
  const contiguous = (k) => {
    const a = items[k - 1], b = items[k];
    return a && b && a.clip === b.clip && Math.abs(b.in - a.out) < 0.05;
  };
  function prepareNext() {
    let k = idx + 1;
    while (k < items.length && contiguous(k)) k++;
    if (k >= items.length) { prep = null; return; }
    if (prep && prep.k === k) return;
    const nx = items[k];
    if (!S.ready[nx.clip]) { prep = null; return; }
    const d = other();
    const my = { k, ready: false };
    prep = my;
    load(d, nx.clip).then((ok) => {
      if (prep !== my || !ok || d === cur()) return;
      pauseDeck(d);
      const done = () => { if (prep === my) my.ready = true; };
      if (Math.abs(d.v.currentTime - nx.in) < 0.02 && !d.v.seeking) { done(); return; }
      d.v.addEventListener('seeked', done, { once: true });
      setTime(d, nx.in);
    });
  }
  const preloadNext = prepareNext;
  function swapToPrepared() {
    const old = cur();
    active = 1 - active;
    const d = cur();
    decks.forEach((x, i) => x.v.classList.toggle('active', i === active));
    playDeck(d);
    pauseDeck(old);
    prep = null;
  }
  function globalTime() {
    const it = items[idx];
    if (!it) return 0;
    return it.t + Math.min(Math.max(cur().v.currentTime - it.in, 0), it.out - it.in);
  }
  function setPlaying(p) {
    playing = p;
    $('#player').classList.toggle('playing', p);
    $('#playBtn').innerHTML = p ? ICON.pause : ICON.play;
  }
  function badge(text) {
    const b = $('#playerBadge');
    if (text) b.textContent = text;
    b.classList.toggle('on', !!text);
  }
  function findItem(tt) {
    let lo = 0, hi = items.length - 1, best = 0;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (items[m].t <= tt) { best = m; lo = m + 1; } else hi = m - 1; }
    return best;
  }
  function highlight(clip, tt) {
    if (!S.analysis) return;
    const p = phraseAt(clip, tt);
    const id = p ? p.id : null;
    if (id === lastHl) return;
    if (lastHl != null) { const r = rowById.get(lastHl); if (r) r.row.classList.remove('playing'); }
    lastHl = id;
    $('#nowText').textContent = p ? p.words.map((w) => w[0]).join(' ') : '';
    $('#nowText').classList.toggle('link', !!p);
    if (p) { const r = rowById.get(id); if (r) r.row.classList.add('playing'); followNow(false); }
  }
  let nowWord = null;
  function highlightWord(clip, tt) {
    const p = lastHl != null ? S.analysis.phrases[lastHl] : null;
    let el = null;
    if (p && p.clip === clip) {
      let k = -1;
      for (let j = 0; j < p.words.length; j++) if (p.words[j][2] <= tt + 0.02) k = j; else break;
      if (k >= 0) el = wordEls[p.w0 + k];
    }
    if (el === nowWord) return;
    if (nowWord) nowWord.classList.remove('now');
    nowWord = el;
    if (el) el.classList.add('now');
  }
  // звук микрофона держим вплотную к видео: мелкое расхождение выправляем скоростью (без щелчков),
  // перематываем только при большом
  function syncAudio(d) {
    if (!sep(d) || d.v.paused) return;
    if (d.a.paused && !d.v.seeking && d.v.readyState >= 3) d.a.play().catch(() => {});
    if (d.a.seeking) return;
    const diff = d.a.currentTime - aTime(d, d.v.currentTime);
    if (Math.abs(diff) > 0.25) { d.a.currentTime = aTime(d, d.v.currentTime); d.a.playbackRate = 1; return; }
    const rate = Math.abs(diff) < 0.03 ? 1 : 1 - Math.max(-0.02, Math.min(0.02, diff * 0.5));
    if (Math.abs(d.a.playbackRate - rate) > 0.002) d.a.playbackRate = rate;
  }

  function tick() {
    requestAnimationFrame(tick);
    if (!items.length || S.view !== 'result') return;
    const d = cur();
    syncAudio(d);
    if (mode === 'source') {
      if (srcRange && d.v.currentTime >= srcRange.e) {
        if (queue.length) { const p = queue.shift(); srcRange = { clip: p.clip, e: p.end + 0.3 }; goto(p.clip, Math.max(0, p.start - 0.3), true); return; }
        pauseDeck(d); setPlaying(false); mode = 'plan'; badge(''); seek(lastGlobal, false);
      }
      highlight(srcRange && srcRange.clip, d.v.currentTime);
      return;
    }
    const it = items[idx];
    if (playing && !waitingFor && !scrubbing && !d.v.seeking && d.v.currentTime >= it.out - 0.015) {
      if (idx + 1 >= items.length) { pauseDeck(d); setPlaying(false); }
      else {
        const k = idx + 1, nx = items[k];
        idx = k;
        if (nx.clip === it.clip && Math.abs(nx.in - d.v.currentTime) < 0.05) { /* продолжение — играем дальше */ }
        else if (prep && prep.k === k && prep.ready) swapToPrepared();
        else goto(nx.clip, nx.in, true);
        badge(nx.kind === 'alt' ? t('badge_alt') : '');
        prepareNext();
      }
    } else if (playing && !prep && !waitingFor && !scrubbing) prepareNext();
    syncScreen(it, d);
    if (!waitingFor && !scrubbing) lastGlobal = globalTime();
    TL.setHead(lastGlobal, playing && !scrubbing);
    $('#timeLabel').textContent = `${clock(lastGlobal)} / ${clock(S.plan ? S.plan.main_duration : total)}`;
    highlight(items[idx].clip, d.v.currentTime);
    highlightWord(items[idx].clip, d.v.currentTime);
  }
  // запись экрана: тот же момент, что и у камеры (через время микрофона)
  const sv = $('#vidScreen');
  function syncScreen(it, d) {
    const tr = S.settings.show_track;
    const ent = tr != null && tr >= 0 && it && it.scr ? it.scr.find(([si]) => S.analysis.screens[si] && (S.analysis.screens[si].track || 0) === tr) : null;
    const on = ent && S.analysis.screens[ent[0]].direct;
    sv.classList.toggle('on', !!on);
    if (!on) { if (!sv.paused) sv.pause(); return; }
    const si = ent[0];
    if (sv.dataset.si !== String(si)) { sv.dataset.si = String(si); sv.src = MOCKED ? '' : `/screen/${si}`; }
    const want = ent[1] + (d.v.currentTime - it.in);
    if (want < 0 || sv.readyState < 1) return;
    if (d.v.paused) { if (!sv.paused) sv.pause(); if (Math.abs(sv.currentTime - want) > 0.08 && !sv.seeking) sv.currentTime = want; return; }
    if (sv.paused) { sv.currentTime = want; sv.play().catch(() => {}); return; }
    const diff = sv.currentTime - want;
    if (Math.abs(diff) > 0.3 && !sv.seeking) { sv.currentTime = want; sv.playbackRate = 1; }
    else sv.playbackRate = Math.abs(diff) < 0.04 ? 1 : 1 - Math.max(-0.05, Math.min(0.05, diff));
  }
  function seek(tt, play = playing) {
    if (!items.length) return;
    mode = 'plan'; srcRange = null;
    idx = findItem(tt);
    const it = items[idx];
    const st = Math.min(Math.max(it.in + (tt - it.t), it.in), it.out - 0.02);
    lastGlobal = it.t + (st - it.in);
    badge(it.kind === 'alt' ? t('badge_alt') : '');
    goto(it.clip, st, play);
    preloadNext();
  }
  function bySource(clip, tt) {
    let best = null;
    for (const x of items) {
      if (x.clip !== clip) continue;
      if (tt >= x.in - 0.01 && tt <= x.out) return x.t + (tt - x.in);
      if (x.in > tt && (!best || x.in < best.in)) best = x;
    }
    return best ? best.t : lastGlobal;
  }
  return {
    setPlan(plan) {
      prep = null;
      const first = !items.length;
      const keep = items.length && items[idx] ? { clip: items[idx].clip, t: cur().v.currentTime } : null;
      items = plan.timeline;
      total = Math.max(plan.duration, 0.001);
      if (!items.length) return;
      if (first) { seek(0, false); return; }
      if (mode === 'plan' && keep) {
        const g = bySource(keep.clip, keep.t);
        idx = findItem(g);
        const it = items[idx];
        if (!(it.clip === keep.clip && keep.t >= it.in - 0.01 && keep.t <= it.out)) seek(g);
      }
    },
    reset() {
      items = []; idx = 0; lastHl = null;
      decks.forEach((d) => { pauseDeck(d); d.v.removeAttribute('src'); d.a.removeAttribute('src'); d.v.dataset.clip = ''; d.v.load(); });
    },
    toggle() {
      if (!items.length) return;
      const d = cur();
      if (playing) { pauseDeck(d); setPlaying(false); }
      else {
        if (mode === 'plan' && idx === items.length - 1 && d.v.currentTime >= items[idx].out - 0.03) seek(0, true);
        else if (!waitingFor) playDeck(d);
        setPlaying(true);
      }
    },
    pause() { decks.forEach(pauseDeck); $('#vidScreen').pause(); setPlaying(false); },
    seek(tt, play) { queue = []; return seek(tt, play); },
    // перетаскивание курсора: метка двигается сразу за мышью, видео догоняет не чаще 20 раз в секунду
    scrub(tt) {
      scrubbing = true;
      lastGlobal = Math.min(Math.max(tt, 0), total);
      TL.setHead(lastGlobal, false);
      $('#timeLabel').textContent = `${clock(lastGlobal)} / ${clock(S.plan ? S.plan.main_duration : total)}`;
      const now = performance.now();
      if (now - lastScrubSeek > 50 && !cur().v.seeking) { lastScrubSeek = now; seek(lastGlobal, false); }
    },
    endScrub(tt) { scrubbing = false; seek(tt, playing); },
    proxyReady(clip) {
      if (waitingFor === clip && waitArgs) { const [c, tt, p] = waitArgs; waitArgs = null; goto(c, tt, p || playing); }
    },
    // смена качества на лету: перезагружаем текущий клип с той же позиции
    reloadCurrent() {
      const d = cur();
      if (!items.length) return;
      const tt = d.v.currentTime, clip = +d.v.dataset.clip, was = playing;
      decks.forEach((x) => { x.v.dataset.key = ''; });
      other().v.dataset.clip = '';
      pauseDeck(d);
      d.v.dataset.clip = '';
      goto(clip, tt, was);
    },
    playPhrase(p, wordIndex) {
      const st = phraseStatus(p);
      const from = wordIndex != null ? (p.words[wordIndex - p.w0] || [])[2] : null;
      const it = items.find((x) => x.phrases.includes(p.id) && (st !== 'alt' || x.kind === 'alt'));
      if (it && st !== 'bad') {
        const srcT = from != null ? from - 0.05 : Math.max(p.start - 0.1, it.in);
        const g = it.kind === 'alt' && from == null ? it.t : bySource(p.clip, Math.max(srcT, it.in));
        seek(g, true); setPlaying(true);
        TL.reveal(g);
      } else {
        mode = 'source';
        srcRange = { clip: p.clip, e: p.end + 0.3 };
        badge(t('badge_src'));
        goto(p.clip, Math.max(0, (from != null ? from : p.start) - 0.3), true);
        setPlaying(true);
      }
    },
    nudge(dt) { seek(Math.min(Math.max(lastGlobal + dt, 0), total), playing); },
    playQueue(list) {
      if (!list.length) return;
      queue = list.slice(1);
      const p = list[0];
      mode = 'source';
      srcRange = { clip: p.clip, e: p.end + 0.3 };
      badge(t('badge_queue', list.length));
      goto(p.clip, Math.max(0, p.start - 0.3), true);
      setPlaying(true);
    },
    forcePlay() { if (!playing) this.toggle(); },
    setVolume(v) { volume = v; muted = v === 0 ? muted : false; applyVolume(); },
    toggleMute() { muted = !muted; applyVolume(); return muted; },
    currentPhrase() { return lastHl; },
    currentClip() { return +cur().v.dataset.clip; },
    init() {
      decks[0].v.classList.add('active');
      $('#playBtn').innerHTML = ICON.play;
      $('#playBtn').addEventListener('click', () => this.toggle());
      $('#bigPlay').addEventListener('click', (e) => { e.stopPropagation(); this.toggle(); });
      $('#player').addEventListener('click', () => this.toggle());
      for (const d of decks) {
        // видео встало на подгрузку — звук ждёт вместе с ним
        d.v.addEventListener('waiting', () => d.a.pause());
        d.v.addEventListener('pause', () => d.a.pause());
      }
      requestAnimationFrame(tick);
    },
  };
})();

/* громкость */
function renderVolume() {
  const v = S.settings.volume ?? 1;
  const p = Math.round(v * 100);
  $('#volFill').style.width = p + '%';
  $('#volKnob').style.left = p + '%';
  $('#volBtn').innerHTML = v === 0 || volMuted ? ICON.mute : ICON.vol;
  $('#volBtn').title = t('volume') + ` · ${volMuted ? 0 : p}%`;
}
let volMuted = false, volSave = null;
(function initVolume() {
  const sl = $('#volSlider');
  let drag = false;
  const set = (e) => {
    const r = sl.getBoundingClientRect();
    const v = Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1);
    S.settings.volume = +v.toFixed(2);
    volMuted = false;
    Player.setVolume(S.settings.volume);
    renderVolume();
    clearTimeout(volSave);
    volSave = setTimeout(() => api('save_settings', { volume: S.settings.volume }), 400);
  };
  sl.addEventListener('pointerdown', (e) => { drag = true; sl.setPointerCapture(e.pointerId); set(e); });
  sl.addEventListener('pointermove', (e) => { if (drag) set(e); });
  sl.addEventListener('pointerup', () => { drag = false; });
  sl.addEventListener('wheel', (e) => {
    e.preventDefault();
    S.settings.volume = Math.min(1, Math.max(0, (S.settings.volume ?? 1) + (e.deltaY < 0 ? 0.05 : -0.05)));
    Player.setVolume(S.settings.volume); renderVolume();
  }, { passive: false });
  $('#volBtn').addEventListener('click', () => { volMuted = Player.toggleMute(); renderVolume(); });
})();

/* клик по тексту текущей фразы под плеером — прокрутить список к ней */
$('#nowText').addEventListener('click', () => {
  const id = Player.currentPhrase();
  if (id == null) return;
  const r = rowById.get(id);
  if (!r) return;
  if (r.row.hidden) { S.filter = 'all'; $('#searchInput').value = ''; applySearch(); updatePhrases(); }
  document.querySelector('.side-tab[data-tab="text"]').click();
  scrollRowIntoView(r.row);
  flash(r.row);
});

const TL = createTimeline({
  canvas: $('#tlCanvas'), mmCanvas: $('#mmCanvas'), mmWrap: $('#minimap'), mmView: $('#mmView'),
  slider: $('#zoomSlider'), tip: $('#tlTip'),
  onSeek: (tt) => Player.seek(tt),
  onScrub: (tt) => Player.scrub(tt),
  onScrubEnd: (tt) => Player.endScrub(tt),
  cuts: () => CUTS,
  onCutClick: (c) => openCutCard(c),
  onTrim: (c, side, delta) => {
    const key = side === 'left' ? c.a.ko : c.b.ki;
    // тянем край левого куска → меняется его конец; правого → начало (знак: вправо = позже)
    setTrim(key, side === 'left' ? delta : delta);
    toast(t('trimmed', trimFmt(S.trims[key] || 0)), { ms: 1500 });
  },
  onContext: (it, e) => {
    const ps = it.phrases.map((id) => S.analysis.phrases[id]).filter(Boolean);
    const items = ps.map((p) => ({ label: t('remove_phrase', p.words.map((w) => w[0]).join(' ').slice(0, 48)), fn: () => { S.overrides[p.id] = 'bad'; replan(); } }));
    if (ps.length > 1) items.push({ label: t('remove_piece'), fn: () => { for (const p of ps) S.overrides[p.id] = 'bad'; replan(); } });
    if (it.ki) items.push({ label: t('cut_reset'), fn: () => { delete S.trims[it.ki]; delete S.trims[it.ko]; replan(); } });
    const fake = { getBoundingClientRect: () => ({ left: e.clientX, right: e.clientX, top: e.clientY, bottom: e.clientY }) };
    openMenu(fake, `${S.analysis.clips[it.clip].name} · ${clock(it.in)}–${clock(it.out)}`, items);
  },
  label: (it) => {
    if (!it.phrases.length) return S.analysis.clips[it.clip].name;
    const p = S.analysis.phrases[it.phrases[0]];
    return p ? p.words.map((w) => w[0]).join(' ') : '';
  },
  fillTip: (tip, it) => {
    tip.innerHTML = '';
    tip.append(h('div', { class: 'muted' }, `${it.kind === 'alt' ? t('badge_alt') + ' · ' : ''}${S.analysis.clips[it.clip].name} · ${clock(it.in)}–${clock(it.out)}`));
    const text = it.phrases.map((id) => S.analysis.phrases[id]).filter(Boolean).map((p) => p.words.map((w) => w[0]).join(' ')).join(' ');
    if (text) tip.append(h('div', {}, text.length > 200 ? text.slice(0, 200) + '…' : text));
  },
});
window.TL = TL;
$('#zoomIn').addEventListener('click', () => TL.zoomIn());
$('#zoomOut').addEventListener('click', () => TL.zoomOut());
$('#zoomFit').addEventListener('click', () => TL.fit());
Player.init();

document.addEventListener('keydown', (e) => {
  if (S.view !== 'result' || e.target.closest('input,textarea') || e.ctrlKey || e.metaKey) return;
  if (e.code === 'Space') { e.preventDefault(); Player.toggle(); }
  else if (e.key === 'ArrowLeft') { e.preventDefault(); Player.nudge(e.shiftKey ? -15 : -3); }
  else if (e.key === 'ArrowRight') { e.preventDefault(); Player.nudge(e.shiftKey ? 15 : 3); }
  else if (e.key === '+' || e.key === '=') TL.zoomIn();
  else if (e.key === '-' || e.key === '_') TL.zoomOut();
  else if (e.key === '\\') TL.fit();
});

/* ---------- масштаб интерфейса: Ctrl + / Ctrl − / Ctrl 0 / Ctrl + колесо ---------- */
const ZOOMS = [0.7, 0.8, 0.9, 1, 1.1, 1.25, 1.4, 1.6];
function applyZoom(z, announce) {
  z = Math.min(1.6, Math.max(0.7, z));
  S.settings.ui_zoom = z;
  document.documentElement.style.zoom = z;
  if (window.TL) TL.theme();
  if (announce) { toast(t('zoom_is', Math.round(z * 100)), { ms: 1200 }); api('save_settings', { ui_zoom: z }); }
}
function stepZoom(dir) {
  const z = S.settings.ui_zoom || 1;
  let i = ZOOMS.findIndex((x) => Math.abs(x - z) < 0.01);
  if (i < 0) i = ZOOMS.findIndex((x) => x > z) - (dir > 0 ? 1 : 0);
  applyZoom(ZOOMS[Math.min(ZOOMS.length - 1, Math.max(0, i + dir))], true);
}
document.addEventListener('keydown', (e) => {
  if (!(e.ctrlKey || e.metaKey)) return;
  if (e.key === '=' || e.key === '+') { e.preventDefault(); stepZoom(1); }
  else if (e.key === '-' || e.key === '_') { e.preventDefault(); stepZoom(-1); }
  else if (e.key === '0') { e.preventDefault(); applyZoom(1, true); }
  else if (e.key === 'f' || e.key === 'F') { if (S.view === 'result') { e.preventDefault(); $('#searchInput').focus(); $('#searchInput').select(); } }
});
window.addEventListener('wheel', (e) => {
  if (!e.ctrlKey) return;
  e.preventDefault();
  stepZoom(e.deltaY < 0 ? 1 : -1);
}, { passive: false });

/* ---------- события от Python ---------- */
const App = {
  dropStart() { $('#dragOverlay').classList.remove('on'); dragDepth = 0; },
  filesAdded(res) { addResult(res); },
  progress({ stage, fraction, message }) {
    const i = STEPS.indexOf(stage);
    if (i < 0) return;
    STEPS.forEach((id, k) => {
      if (k < i && stepState[id] && stepState[id].cls !== 'done') {
        stepState[id].cls = 'done';
        const el = $('#step-' + id); if (el) el.className = 'step done';
      }
    });
    const st = stepState[stage] = { cls: fraction >= 1 ? 'done' : 'active', frac: fraction, msg: message };
    const el = $('#step-' + stage);
    if (el) {
      el.className = 'step ' + st.cls;
      el.querySelector('.bar > i').style.width = Math.round(fraction * 100) + '%';
      el.querySelector('.step-msg').textContent = message;
    }
    $('#progressMsg').textContent = message;
    const w = { sync: [0, 0.15], speech: [0.15, 0.95], takes: [0.95, 1] }[stage];
    S.busyFrac = w[0] + (w[1] - w[0]) * fraction;
    renderModelState();
  },
  modelState({ state, error }) { S.modelState = state; S.modelError = error; renderModelState(); },
  async done(payload) {
    const data = payload && payload.analysis ? payload : await (await fetch('/api/result?' + Date.now())).json();
    STEPS.forEach((id) => { stepState[id] = { cls: 'done', frac: 1, msg: '' }; const el = $('#step-' + id); if (el) el.className = 'step done'; });
    Player.reset();
    S.analysis = data.analysis;
    S.plan = data.plan;
    S.overrides = {};
    S.wordOverrides = {};
    S.trims = {};
    closeCutCard();
    S.filter = 'all';
    $('#searchInput').value = '';
    S.ready = S.analysis.clips.map((c) => !!c.ready);
    S.busy = false; renderModelState();
    indexPhrases();
    setTimeout(() => {
      show('result');
      renderSettings($('#liveSettings'), SETTINGS_LIVE, onLiveSetting);
      renderResult(true);
    }, 300);
  },
  proxyReady({ clip, error, light }) {
    if (!S.analysis) return;
    if (error) toast(t('proxy_fail') + error, { error: true, ms: 8000 });
    else if (light) {
      S.analysis.clips[clip].lightReady = true;
      if (S.settings.preview_quality === 'light' && Player.currentClip() === clip) Player.reloadCurrent();
    } else { S.ready[clip] = true; S.analysis.clips[clip].lightReady = S.analysis.clips[clip].lightReady || !S.analysis.clips[clip].direct; Player.proxyReady(clip); }
    renderProxyNote();
  },
  cancelled() { S.busy = false; renderModelState(); show('files'); toast(t('cancelled')); },
  failed({ message }) { S.busy = false; renderModelState(); show('files'); toast(message, { error: true, ms: 9000 }); },
};
window.App = App;

function onMainSetting() { api('save_settings', S.settings); }
function onLiveSetting(key, dragging) { replan(dragging ? 40 : 0); }
function renderModelCallout() {
  const c = $('#modelCallout');
  const parts = t(S.model ? 'model_vt' : 'model_dl');
  c.innerHTML = '';
  c.append(h('span', { class: 'emoji' }, '💡'), h('div', {}, parts[0], h('b', {}, parts[1]), parts[2]));
}

/* ---------- старт ---------- */
(async function init() {
  applyStaticText();
  applyTheme((() => { try { return localStorage.getItem('theme') || 'system'; } catch (e) { return 'system'; } })());
  const st = await api('init');
  S.settings = st.settings;
  S.files = st.files || [];
  S.model = st.model;
  S.version = st.version;
  S.modelState = st.modelState;
  applyTheme(S.settings.theme || 'system');   // источник правды — настройки программы, а не память браузера
  applyZoom(S.settings.ui_zoom || 1, false);
  Player.setVolume(S.settings.volume ?? 1);
  setLang(S.settings.ui_lang || LANG, false);
  renderVolume();
  S.view = null; show('files');
})();
