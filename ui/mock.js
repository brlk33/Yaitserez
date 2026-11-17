/* Демо-данные для проверки интерфейса в обычном браузере (index.html?mock).
   Генерирует ~4 часа исходников и ~4000 фраз, чтобы проверить скорость таймлайна и списка. */
'use strict';

const Mock = (() => {
  const WORDS = 'сегодня мы поговорим о монтаже видео первое что нужно сделать это разложить исходники по папкам второй шаг очень важный синхронизируем звук с микрофона потом режем паузы и выкидываем дубли в конце экспортируем проект'.split(' ');
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const clips = [], phrases = [];
  let wcount = 0;
  const CLIPS = 14;
  for (let c = 0; c < CLIPS; c++) {
    const dur = 900 + rnd() * 600;
    clips.push({ name: `C${String(c + 1).padStart(4, '0')}.MP4`, duration: dur, sync: { ok: c !== 9 }, ready: c < 3, sepAudio: true, direct: true, lightReady: c < 2 });
    let tt = 2 + rnd() * 3;
    while (tt < dur - 8) {
      const n = 3 + Math.floor(rnd() * 12);
      const ws = Array.from({ length: n }, (_, k) => [WORDS[Math.floor(rnd() * WORDS.length)], rnd() < 0.03 ? 1 : 0, +(tt + k * 0.33).toFixed(2)]);
      ws[0][0] = ws[0][0][0].toUpperCase() + ws[0][0].slice(1);
      ws[n - 1][0] += '.';
      const len = n * 0.33 + rnd();
      const r = rnd();
      const auto = r < 0.12 ? 'bad' : r < 0.2 ? 'alt' : 'main';
      phrases.push({ id: phrases.length, clip: c, start: tt, end: tt + len, auto,
        reason: auto === 'bad' ? (rnd() < 0.5 ? ['cutoff'] : ['unfinished']) : auto === 'alt' ? ['alt', 1, 2] : null,
        take: 1, takes: auto === 'main' ? 1 : 2, words: ws, w0: wcount });
      wcount += n;
      tt += len + 0.2 + rnd() * 2.5;
    }
  }
  const analysis = { clips, mics: ['ZOOM0001.WAV'], phrases, screens: [{ name: 'OBS screen.mp4', duration: 15000, sync: { ok: true }, direct: true }] };

  function plan(settings, overrides, wo) {
    const st = {};
    for (const p of phrases) st[p.id] = overrides[p.id] || (settings.drop_bad_takes === false ? 'main' : p.auto);
    const maxP = settings.max_pause ?? 0.5, keep = settings.keep_pause ?? 0.25;
    const tl = [];
    let tt = 0;
    const push = (p, kind) => {
      const ins = Math.max(0, p.start - keep * 0.4), out = p.end + keep * 0.6;
      const last = tl[tl.length - 1];
      if (kind === 'main' && last && last.kind === 'main' && last.clip === p.clip && ins - last.out < maxP - keep) {
        tt += out - last.out; last.out = out; last.phrases.push(p.id); return;
      }
      tl.push({ clip: p.clip, in: +ins.toFixed(3), out: +out.toFixed(3), t: +tt.toFixed(3), kind, phrases: [p.id], scr: [0, +ins.toFixed(3)] });
      tt += out - ins;
    };
    for (const p of phrases) if (st[p.id] === 'main') push(p, 'main');
    const mainDur = tt;
    let altStart = null;
    if (settings.keep_alternates !== false) {
      tt += 3; altStart = tt;
      for (const p of phrases) if (st[p.id] === 'alt') push(p, 'alt');
    }
    const cnt = (k) => Object.values(st).filter((v) => v === k).length;
    const cw = {};
    for (const p of phrases) p.words.forEach((w, k) => { if (w[1]) cw[p.w0 + k] = 'repeat'; });
    for (const [k, v] of Object.entries(wo || {})) { if (v === 'cut') cw[k] = 'manual'; else delete cw[k]; }
    return { timeline: tl, duration: tt, main_duration: mainDur, alt_start: altStart, statuses: st, cut_words: cw,
      stats: { original: clips.reduce((a, c) => a + c.duration, 0), result: mainDur, main: cnt('main'), alt: cnt('alt'), bad: cnt('bad') } };
  }

  const settings = { remove_silence: true, max_pause: 0.5, keep_pause: 0.3, pause_place: 'tail', pre_roll: 0.05, cut_breaths: true, breath_sens: 0.6, pause: 0.2, equalize: true, pause_place: 'auto', show_screen: true, preview_quality: 'original', cut_profanity: true, cut_fillers: true, cut_words: ['блин*'], smart_takes: true, volume: 0.8, ui_zoom: 1, drop_bad_takes: true, keep_alternates: true,
    prefer_take: 'last', camera_audio: 'muted', keep_silent_clips: true, language: 'ru', theme: 'system', ui_lang: 'ru' };
  const api = {
    init: async () => ({ settings, version: '1.0.0', model: 'VoiceType', modelState: 'ready', files: clips.map((c, i) => ({ id: String(i), name: c.name, kind: 'video', duration: c.duration, info: '3840×2160 · 25 к/с', path: 'E:\\' + c.name })).concat([{ id: 'm', name: 'ZOOM0001.WAV', kind: 'audio', duration: 15000, info: '48 кГц · стерео', path: 'E:\\ZOOM0001.WAV' }]) }),
    save_settings: async () => true, set_lang: async () => true, remove_file: async () => true, set_kind: async () => true,
    pick_files: async () => ({ added: [], errors: [] }), cancel: async () => true, export: async () => null, reveal: async () => true,
    win_drag: async () => null, win_resize: async () => null, win_toggle_max: async () => false, win_min: async () => null,
    win_close: async () => null, take_dropped: async () => ({ added: [], errors: [] }), open_folder: async () => true,
    cache_info: async () => ({ path: 'D:\\Program Files\\Yaitserez\\cache', size: 734003200 }),
    clear_cache: async () => ({ path: 'D:\\Program Files\\Yaitserez\\cache', size: 0 }),
    start: async (s) => {
      const steps = [['sync', 'Синхронизировано 14 из 14'], ['speech', 'Распознаю речь: C0003.MP4 (3 из 14)'], ['takes', 'Ищу дубли']];
      let k = 0;
      const iv = setInterval(() => {
        if (k < steps.length * 5) { const [st, m] = steps[Math.floor(k / 5)]; App.progress({ stage: st, fraction: (k % 5 + 1) / 5, message: m }); k++; }
        else {
          clearInterval(iv);
          App.done({ analysis, plan: plan(s, {}) });
          let c = 3;
          const pv = setInterval(() => { if (c >= CLIPS) return clearInterval(pv); App.proxyReady({ clip: c++, done: c, total: CLIPS }); }, 700);
        }
      }, 60);
      return true;
    },
    replan: async (s, o, wo) => plan(s, o, wo), set_quality: async () => true,
  };
  return { api };
})();
