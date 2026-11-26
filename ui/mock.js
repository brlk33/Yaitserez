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
    reanalyze: async (s, o, wo, ids) => {
      for (let k = 1; k <= 4; k++) { await new Promise((r) => setTimeout(r, 250)); App.reanalyzeProgress({ fraction: k / 4, message: '' }); }
      for (const id of ids.slice(0, 2)) phrases[id].auto = 'bad';   // «нейросеть» передумала про пару фраз
      return { plan: plan(s, o, wo), dropped: Math.min(2, ids.length) };
    },
    check_update: async () => ({ version: '1.4.0', notes: '' }), install_update: async () => false,
    style_pick: async () => 'E:\\Projects\\Курс\\AE 01 финал.xml',
    style_start: async () => {
      setTimeout(() => App.styleDone({ settings: Object.assign(settings, { pause: 0.18, cut_breaths: true, style_ref: {
        file: 'AE 01 финал.xml', sequence: 'AE 01', cuts: 142, pause: 0.18, pause_lo: 0.12, pause_hi: 0.27, breath_share: 0.08,
        missing: [], before: { pause: 0.2, cut_breaths: true }, after: { pause: 0.18, cut_breaths: true } } }), report: { pause: 0.18 } }), 800);
      return true;
    },
    style_undo: async () => Object.assign(settings, { pause: 0.2, style_ref: null }),
    llm_status: async () => ({ choice: '9b', has_9b: true, has_4b: false, size_9b: 5.68e9, size_4b: 2.74e9, using: 'Qwen3.5-9B-Q4_K_M.gguf' }),
    learn_info: async () => ({ llm: true, busy: false, report: null, projects: [
      { path: 'E:\\Projects\\Курс\\04 AE 1\\00 PROJECTS\\AE 01.yaitserez', name: 'AE 01.yaitserez' },
      { path: 'E:\\Projects\\Курс\\03 PR 2\\PR 02.yaitserez', name: 'PR 02.yaitserez' }] }),
    learn_add: async () => [],
    learn_cancel: async () => true,
    learn_reset: async () => settings,
    learn_start: async () => {
      let f = 0;
      const iv = setInterval(() => {
        f += 0.2;
        if (f < 1) return App.learnProgress({ fraction: f, message: 'AE 01: Ищу переговорённые фразы: 400 из 1084' });
        clearInterval(iv);
        App.learnDone({ settings, report: { date: '2026-11-22', changed: true, n_examples: 6, llm: true,
          params: { takes_strictness: 'strict', pair_cov: 0.35, continuation_gap: 2.2 },
          defaults: { takes_strictness: 'medium', pair_cov: 0.35, continuation_gap: 2.2 },
          projects: [{ name: 'AE 01', source: 'premiere', source_file: 'AE 01.prproj', words: 8172,
            before: { agree: 0.8435, extra: 1040, lost: 239, minutes: 43.8, target_minutes: 38.0 },
            after: { agree: 0.8484, extra: 985, lost: 254, minutes: 43.2, target_minutes: 38.0,
              extra_examples: ['Плюс я ещё туда завёз функцию, чтобы обновлять кадры…', 'Возвращаемся теперь в автор.'],
              lost_examples: ['Это такая картинка, на которой изображена поверхность бумаги…'] } },
          { name: 'test', error: 'итоговый монтаж слишком короткий (0.2 мин) — похоже на черновик, пропускаю' }] } });
      }, 500);
      return true;
    },
  };
  return { api };
})();
