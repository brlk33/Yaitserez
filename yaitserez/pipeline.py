"""Полный цикл анализа: синхронизация → распознавание → разбор дублей. Превью делаются в фоне."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np

from . import cutter, takes
from .i18n import L
from .media import MediaInfo, browser_playable, ffmpeg, load_audio, run
from .paths import cache_dir
from .sync import sync_videos


class Cancelled(Exception):
    pass


def _natural(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def order_videos(videos: list[MediaInfo]) -> list[MediaInfo]:
    if videos and all(v.creation_time for v in videos) and len({v.creation_time for v in videos}) == len(videos):
        return sorted(videos, key=lambda v: (v.creation_time, _natural(v.name)))
    return sorted(videos, key=lambda v: _natural(v.name))


def _key(*parts) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()[:16]


def _file_sig(path: str) -> str:
    st = os.stat(path)
    return f"{os.path.abspath(path)}:{st.st_size}:{int(st.st_mtime)}"


def _clip_dict(v: MediaInfo) -> dict:
    return {
        "path": v.path, "name": v.name, "duration": v.duration, "has_video": v.has_video, "has_audio": v.has_audio,
        "width": v.width, "height": v.height, "fps_num": v.fps_num, "fps_den": v.fps_den,
        "sample_rate": v.sample_rate, "channels": v.channels, "audio_channels": v.audio_channels, "direct": browser_playable(v),
    }


# ---------------- превью ----------------
_GPU_DECODE_OK: bool | None = None


def make_proxy(clip: dict, mic: dict | None, offset: float, out: str, cancelled=lambda: False, height: int = 540) -> None:
    """Лёгкая копия 540p со звуком микрофона. Сначала полностью на видеокарте (декодирование + масштаб +
    кодирование), если не вышло — декодирование на процессоре, затем чистый libx264."""
    global _GPU_DECODE_OK
    audio_in, afilter, amap = [], [], None
    if mic is not None:
        if offset >= 0:
            audio_in = ["-ss", f"{offset:.4f}", "-i", mic["path"]]
        else:
            audio_in = ["-i", mic["path"]]
            afilter = ["-af", f"adelay={int(round(-offset * 1000))}:all=1"]
        amap = "1:a:0"
    elif clip["has_audio"]:
        amap = "0:a:0"
    tail = (["-map", "0:v:0"] + (["-map", amap] if amap else []) + afilter +
            ["-t", f"{clip['duration']:.3f}", "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart"])
    nvenc = ["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ll", "-rc", "vbr", "-cq", "30", "-g", "12", "-bf", "0"]
    variants = []
    if _GPU_DECODE_OK is not False:
        variants.append(("gpu", ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-i", clip["path"]],
                         ["-vf", f"scale_cuda=-2:{height}:format=nv12"] + nvenc))
    variants.append(("cpu+nvenc", ["-threads", "0", "-i", clip["path"]],
                     ["-vf", f"scale=-2:{height}:flags=fast_bilinear,format=yuv420p"] + nvenc))
    variants.append(("cpu", ["-threads", "0", "-i", clip["path"]],
                     ["-vf", f"scale=-2:{height}:flags=fast_bilinear,format=yuv420p", "-c:v", "libx264", "-preset",
                      "ultrafast", "-crf", "28", "-g", "12", "-bf", "0"]))
    err = ""
    for name, vin, venc in variants:
        if cancelled():
            return
        p = run([ffmpeg(), "-y", "-v", "error", "-nostdin"] + vin + audio_in + tail + venc + [out])
        if p.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 0:
            if name == "gpu":
                _GPU_DECODE_OK = True
            return
        if name == "gpu" and _GPU_DECODE_OK is None:
            _GPU_DECODE_OK = False
        err = p.stderr.decode("utf-8", "replace")[-300:]
    raise RuntimeError(L(f"Не удалось сделать превью для {clip['name']}: ", f"Preview failed for {clip['name']}: ") + err)


def make_audio_proxy(clip: dict, mic: dict, offset: float, out: str) -> None:
    """Звук микрофона, выровненный по клипу (AAC). Делается за секунды — видео при этом
    проигрывается прямо из исходника, если браузер его умеет."""
    args = [ffmpeg(), "-y", "-v", "error", "-nostdin"]
    af = []
    if offset >= 0:
        args += ["-ss", f"{offset:.4f}", "-i", mic["path"]]
    else:
        args += ["-i", mic["path"]]
        af = ["-af", f"adelay={int(round(-offset * 1000))}:all=1"]
    args += af + ["-t", f"{clip['duration']:.3f}", "-vn", "-c:a", "aac", "-b:a", "160k", "-ac", "2",
                  "-movflags", "+faststart", out]
    p = run(args)
    if p.returncode != 0 or not os.path.isfile(out):
        raise RuntimeError(L(f"Не удалось подготовить звук для {clip['name']}", f"Audio prep failed for {clip['name']}"))


BROWSER_AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


class ProxyQueue:
    """Подготовка предпросмотра в фоне.

    * видео, которое браузер играет сам (H.264 8 бит 4:2:0 — большинство камер), не перекодируется:
      плеер берёт исходник, а звук микрофона идёт отдельной лёгкой дорожкой — готово за секунды;
    * остальное (ProRes, HEVC 10 бит, 4:2:2…) перекодируется в лёгкую копию 540p на видеокарте.
    Сначала делается всё быстрое, потом тяжёлое.
    """

    def __init__(self, clips, mics, on_ready, cancelled, light=False):
        self.clips, self.mics, self.on_ready, self.cancelled = clips, mics, on_ready, cancelled
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.light_requested = False
        self.done = 0
        self.lock = threading.Lock()
        self.futures: list[Future] = []
        for c in clips:
            s = c["sync"]
            mic = mics[s["mic"]] if s["ok"] else None
            sig = (_file_sig(c["path"]), mic and _file_sig(mic["path"]), round(s["offset"], 3) if mic else 0)
            c["audio_src"] = None
            c["audio_offset"] = 0.0
            # лёгкая копия 540p со звуком микрофона внутри — для режима «Лёгкое качество»
            c["light"] = os.path.join(cache_dir(), "proxy_" + _key(*sig, 3) + ".mp4")
            c["light_ready"] = os.path.isfile(c["light"])
            hgt = int(c.get("height") or 1080)
            c["half_h"] = max(270, (hgt // 2) // 2 * 2)
            c["half"] = os.path.join(cache_dir(), "proxy_" + _key(*sig, 3, c["half_h"]) + ".mp4")
            c["half_ready"] = os.path.isfile(c["half"])
            if c.get("audio_only"):
                if c.get("direct"):
                    c["video_src"], c["proxy_ready"] = c["path"], True
                else:
                    c["video_src"] = os.path.join(cache_dir(), "audio_" + _key(*sig, 1) + ".m4a")
                    c["proxy_ready"] = os.path.isfile(c["video_src"])
                continue
            if c.get("direct"):
                c["video_src"] = c["path"]
                if mic is not None and os.path.splitext(mic["path"])[1].lower() in BROWSER_AUDIO:
                    # запись микрофона браузер играет сам: смещение синхронизации учитывает плеер
                    c["audio_src"] = mic["path"]
                    c["audio_offset"] = s["offset"]
                    c["proxy_ready"] = True
                    continue
                if mic is not None:
                    c["audio_src"] = os.path.join(cache_dir(), "audio_" + _key(*sig, 1) + ".m4a")
                c["proxy_ready"] = c["audio_src"] is None or os.path.isfile(c["audio_src"])
            else:
                c["video_src"] = c["light"]
                c["proxy_ready"] = c["light_ready"]
        order = [k for k in sorted(range(len(clips)), key=lambda k: (not clips[k].get("direct"), k))
                 if not clips[k]["proxy_ready"]]
        for k in order:
            self.futures.append(self.pool.submit(self._job, k))
        if light:
            self.request_light()

    def request_half(self):
        """Копии в половину разрешения — по запросу (качество превью «1/2»)."""
        if getattr(self, "half_requested", False):
            return
        self.half_requested = True
        for k, c in enumerate(self.clips):
            if not c.get("audio_only") and not c.get("half_ready"):
                self.futures.append(self.pool.submit(self._half_job, k))

    def _half_job(self, i):
        c = self.clips[i]
        err = None
        try:
            if not c["half_ready"] and not self.cancelled():
                s = c["sync"]
                mic = self.mics[s["mic"]] if s["ok"] else None
                tmp = c["half"] + ".tmp.mp4"
                make_proxy(c, mic, s["offset"], tmp, self.cancelled, height=c["half_h"])
                if os.path.isfile(tmp):
                    os.replace(tmp, c["half"])
                    c["half_ready"] = True
        except Exception as e:  # noqa: BLE001
            err = str(e)
        done = sum(1 for x in self.clips if x.get("half_ready"))
        self.on_ready(i, done, len(self.clips), err, light="half")

    def request_light(self):
        """Поставить в очередь лёгкие копии для клипов, которые сейчас играют из исходника."""
        if self.light_requested:
            return
        self.light_requested = True
        for k, c in enumerate(self.clips):
            if c.get("direct") and not c["light_ready"] and not c.get("audio_only"):
                self.futures.append(self.pool.submit(self._light_job, k))

    def _light_job(self, i):
        c = self.clips[i]
        err = None
        try:
            if not c["light_ready"] and not self.cancelled():
                s = c["sync"]
                mic = self.mics[s["mic"]] if s["ok"] else None
                tmp = c["light"] + ".tmp.mp4"
                make_proxy(c, mic, s["offset"], tmp, self.cancelled)
                if os.path.isfile(tmp):
                    os.replace(tmp, c["light"])
                    c["light_ready"] = True
        except Exception as e:  # noqa: BLE001
            err = str(e)
        done = sum(1 for x in self.clips if x["light_ready"])
        self.on_ready(i, done, len(self.clips), err, light=True)

    def _job(self, i):
        c = self.clips[i]
        err = None
        try:
            if not c["proxy_ready"] and not self.cancelled():
                s = c["sync"]
                mic = self.mics[s["mic"]] if s["ok"] else None
                target = c["audio_src"] if c.get("direct") else c["video_src"]
                tmp = target + (".tmp.m4a" if c.get("direct") else ".tmp.mp4")
                if c.get("audio_only"):
                    target, tmp = c["video_src"], c["video_src"] + ".tmp.m4a"
                    make_audio_proxy(c, c, 0.0, tmp)
                elif c.get("direct"):
                    make_audio_proxy(c, mic, s["offset"], tmp)
                else:
                    make_proxy(c, mic, s["offset"], tmp, self.cancelled)
                if os.path.isfile(tmp):
                    os.replace(tmp, target)
                    c["proxy_ready"] = True
                    if not c.get("direct") and not c.get("audio_only"):
                        c["light_ready"] = True
        except Exception as e:  # noqa: BLE001
            err = str(e)
        with self.lock:
            self.done += 1
            n = self.done
        self.on_ready(i, n, len(self.clips), err)


# ---------------- анализ ----------------
def analyze(videos: list[MediaInfo], mics: list[MediaInfo], settings: dict, progress, cancelled,
            on_proxy=None, screens: list[MediaInfo] | None = None) -> dict:
    """progress(stage, fraction, message). Возвращает analysis (env-массивы внутри — для build_plan)."""
    from . import transcribe as tr

    def check():
        if cancelled():
            raise Cancelled()

    videos = order_videos([v for v in videos if v.has_video])
    audio_only = not videos
    if audio_only:
        # только звук: каждая запись сама себе «клип» и сама себе микрофон
        mics = order_videos([m for m in mics if m.has_audio])
        if not mics:
            raise RuntimeError(L("Нет ни одного видео- или аудиофайла.", "There are no video or audio files."))
    clips = [_clip_dict(v) for v in (videos or mics)]
    mic_list = [_clip_dict(m) for m in mics]
    if audio_only:
        for i, c in enumerate(clips):
            c["audio_only"] = True
            c["direct"] = os.path.splitext(c["path"])[1].lower() in BROWSER_AUDIO

    # 1. синхронизация
    progress("sync", 0.0, L("Ищу совпадения звука", "Matching audio"))
    screens = order_videos([v for v in (screens or []) if v.has_video])
    screen_list = [_clip_dict(v) for v in screens]
    # экран синхронизируется по звуку микрофона так же, как камера
    to_sync = videos + screens
    sync_cache = os.path.join(cache_dir(), "sync_" + _key(2, *[_file_sig(v.path) for v in to_sync],
                                                           *[_file_sig(m.path) for m in mics]) + ".json")
    if audio_only:
        syncs = [{"mic": i, "offset": 0.0, "confidence": 1.0, "ok": True} for i in range(len(clips))]
        if screens:
            res = sync_videos(screens, mics, progress=lambda fr, msg: progress("sync", fr, msg))
            syncs += [{"mic": r.mic_index, "offset": r.offset, "confidence": r.confidence, "ok": r.ok} for r in res]
    elif os.path.isfile(sync_cache):
        with open(sync_cache, encoding="utf-8") as f:
            syncs = json.load(f)
    else:
        res = sync_videos(to_sync, mics, progress=lambda fr, msg: progress("sync", fr, msg))
        check()
        syncs = [{"mic": r.mic_index, "offset": r.offset, "confidence": r.confidence, "ok": r.ok} for r in res]
        with open(sync_cache, "w", encoding="utf-8") as f:
            json.dump(syncs, f)
    for c, s in zip(clips + screen_list, syncs):
        c["sync"] = s
    for c in screen_list:
        c["kind"] = "screen"
    # мультикамера: видео, снятые одновременно с другими, — это не следующие дубли, а другие ракурсы.
    # Основная дорожка — непересекающиеся по времени клипы, остальные уезжают на дополнительные дорожки.
    clips, extra = (clips, []) if audio_only else split_angles(clips)
    for c in extra:
        c["kind"] = "camera"
    screen_list = extra + screen_list
    assign_tracks(screen_list)
    progress("sync", 1.0, L("Звук синхронизирован", "Audio synced"))
    check()

    # 2. превью — в фоне на видеокарте, окно результата их не ждёт
    proxies = ProxyQueue(clips, mic_list, on_proxy or (lambda *a, **k: None), cancelled,
                         light=settings.get("preview_quality") == "light")

    # 3. распознавание речи (по звуку микрофона, если он есть). Звук следующего клипа
    #    читается заранее, пока видеокарта распознаёт текущий.
    model = settings.get("model", "large-v3-turbo")
    lang = settings.get("language", "ru")
    need_speech = settings.get("remove_silence", True) or settings.get("drop_bad_takes", True)
    # русская речь — GigaAM-v3 (точнее Whisper, с пунктуацией и временем слов), если он есть; иначе Whisper
    use_giga = lang == "ru" and settings.get("asr_engine", "auto") != "whisper" and tr.gigaam_available()
    engine = "gigaam-v3" if use_giga else model

    def source(c):
        s = c["sync"]
        if s["ok"]:
            mic = mic_list[s["mic"]]
            return lambda: load_audio(mic["path"], 16000, s["offset"], c["duration"]), \
                _file_sig(mic["path"]) + f"@{s['offset']:.3f}"
        if c["has_audio"]:
            return lambda: load_audio(c["path"], 16000), "cam"
        return lambda: np.zeros(int(c["duration"] * 16000), dtype=np.float32), "none"

    total_dur = sum(c["duration"] for c in clips) or 1.0
    done_dur = 0.0
    loader = ThreadPoolExecutor(max_workers=1)
    pending = loader.submit(source(clips[0])[0])
    words_by_clip, envs, thrs, lows, peaks, pers, vads = [], [], [], [], [], [], []
    try:
        for i, c in enumerate(clips):
            check()
            audio = pending.result()
            if i + 1 < len(clips):
                pending = loader.submit(source(clips[i + 1])[0])
            src_sig = source(c)[1]
            envs.append(cutter.envelope(audio))
            lows.append(cutter.lowband(audio))
            peaks.append(cutter.peaks(audio))
            vads.append(cutter.voice_prob(audio))
            pers.append(cutter.periodicity(audio) if vads[-1] is None else None)
            thrs.append(cutter.speech_threshold(envs[-1]))
            base, span = done_dur / total_dur, c["duration"] / total_dur
            done_dur += c["duration"]
            if not need_speech or src_sig == "none":
                words_by_clip.append([])
                continue
            wc = os.path.join(cache_dir(), "words_" + _key(_file_sig(c["path"]), src_sig, engine, lang, 4) + ".json")
            if os.path.isfile(wc):
                with open(wc, encoding="utf-8") as f:
                    words_by_clip.append(json.load(f))
                progress("speech", base + span, L(f"Речь распознана: {c['name']}", f"Transcribed: {c['name']}"))
                continue
            msg = L(f"Распознаю речь: {c['name']} ({i + 1} из {len(clips)})",
                    f"Transcribing: {c['name']} ({i + 1} of {len(clips)})")
            progress("speech", base, msg)
            ws = None
            if use_giga:
                try:
                    tr.release()   # видеопамять — GigaAM
                    ws = tr.transcribe_gigaam(
                        audio, cache_dir(),
                        status=lambda m, base=base: progress("speech", base, msg + " · GigaAM-v3"),
                        on_progress=lambda fr, base=base, span=span, msg=msg: (check(), progress("speech", base + fr * span, msg + " · GigaAM-v3")),
                    )
                except Cancelled:
                    raise
                except Exception as e:  # noqa: BLE001 — не вышло — распознаём Whisper
                    progress("speech", base, L(f"GigaAM недоступен ({e}), распознаю Whisper", f"GigaAM unavailable ({e}), using Whisper"))
                    use_giga, engine = False, model
                    wc = os.path.join(cache_dir(), "words_" + _key(_file_sig(c["path"]), src_sig, engine, lang, 4) + ".json")
            if ws is None:
                ws = tr.transcribe(
                    audio, model, lang,
                    status=lambda m, base=base: progress("speech", base, m),
                    on_progress=lambda fr, base=base, span=span, msg=msg: (check(), progress("speech", base + fr * span, msg)),
                )
            with open(wc, "w", encoding="utf-8") as f:
                json.dump(ws, f, ensure_ascii=False)
            words_by_clip.append(ws)
    finally:
        loader.shutdown(wait=False, cancel_futures=True)
        tr.gigaam_stop()   # освобождаем видеопамять для языковой модели
    progress("speech", 1.0, L("Речь распознана", "Speech transcribed"))
    check()

    # 4. фразы и дубли
    progress("takes", 0.0, L("Ищу дубли", "Looking for takes"))
    words_by_clip = [cutter.tighten_words(ws, envs[i], lows[i], pers[i], vads[i]) if i < len(envs) else ws
                     for i, ws in enumerate(words_by_clip)]
    words, phrases = takes.build_phrases(words_by_clip)
    hints = {}
    if settings.get("drop_bad_takes", True) and settings.get("smart_takes", True) and phrases:
        from . import llm

        llm.CHOICE["model"] = settings.get("llm_model", "9b")
        if llm.available():
            tr.release()  # освобождаем видеопамять под языковую модель
            try:
                hints = llm.analyze(phrases, "en" if lang == "en" else "ru",
                                    progress=lambda fr, msg: (check(), progress("takes", fr, msg)),
                                    cancelled=cancelled,
                                    examples=(settings.get("learned") or {}).get("examples") or None)
            except Cancelled:
                raise
            except Exception as e:  # noqa: BLE001 — без модели работаем на правилах
                progress("takes", 1.0, L(f"Смысловой разбор недоступен: {e}", f"Meaning analysis unavailable: {e}"))
            finally:
                llm.SERVER.stop()
                tr.preload(model)
    progress("takes", 1.0, L(f"Найдено фраз: {len(phrases)}", f"Phrases found: {len(phrases)}"))

    return {"clips": clips, "mics": mic_list, "words": words, "phrases": phrases, "env": envs, "thr": thrs,
            "proxies": proxies, "llm": hints, "low": lows, "screens": screen_list,
            "peaks": peaks, "per": pers, "vad": vads}


def mic_span(c: dict) -> tuple[int, float, float] | None:
    """(файл микрофона, начало, конец) клипа во времени микрофона."""
    s = c.get("sync") or {}
    if not s.get("ok"):
        return None
    return s["mic"], s["offset"], s["offset"] + c["duration"]


def split_angles(clips: list[dict]) -> tuple[list[dict], list[dict]]:
    """Делит видео на основную дорожку и одновременные ракурсы (пересечение по времени больше 2 с)."""
    main, extra = [], []
    spans = []
    for c in sorted(clips, key=lambda c: (mic_span(c) or (0, 0, 0))[1]):
        sp = mic_span(c)
        if sp is None:
            main.append(c)
            continue
        overlap = max([min(sp[2], e) - max(sp[1], s) for m, s, e in spans if m == sp[0]] + [0])
        if overlap > 2.0:
            extra.append(c)
        else:
            main.append(c)
            spans.append(sp)
    order = {id(c): k for k, c in enumerate(clips)}
    main.sort(key=lambda c: order[id(c)])
    return main, extra


def assign_tracks(extra: list[dict]) -> None:
    """Раскладывает дополнительные видео по дорожкам: куски одной записи — на одну, одновременные — на разные."""
    ends: list[tuple[int, float]] = []  # (микрофон, конец последнего клипа) на каждой дорожке
    for c in sorted(extra, key=lambda c: (mic_span(c) or (0, 0, 0))[1]):
        sp = mic_span(c)
        if sp is None:
            c["track"] = len(ends)
            ends.append((-1, 0.0))
            continue
        for t, (m, end) in enumerate(ends):
            if (m == sp[0] or m == -1) and end <= sp[1] + 0.5:
                c["track"] = t
                ends[t] = (sp[0], sp[2])
                break
        else:
            c["track"] = len(ends)
            ends.append((sp[0], sp[2]))


def append_sources(old: dict, videos: list[MediaInfo], mics: list[MediaInfo], screens: list[MediaInfo],
                   settings: dict, progress, cancelled, on_proxy=None) -> int:
    """Дозаписанные исходники — в конец уже готового разбора: синхронизация, распознавание и разбор
    дублей только для новых файлов, потом всё склеивается в один разбор (новые клипы — после старых).
    Возвращает, сколько клипов добавлено."""
    from .media import probe

    nc, nw, n_ph = len(old["clips"]), len(old["words"]), len(old["phrases"])
    audio_only = bool(old["clips"]) and all(c.get("audio_only") for c in old["clips"])
    known = {m["path"] for m in old["mics"]}
    fresh_mics = [m for m in mics if m.path not in known]
    if audio_only:
        # проект только со звуком: новые записи — новые клипы
        new = analyze([], fresh_mics, settings, progress, cancelled,
                      on_proxy=(lambda i, *a, **k: on_proxy(i + nc, *a, **k)) if on_proxy else None)
        mic_offset = len(old["mics"])
    else:
        # камеры синхронизируем со всеми записями микрофона: и старыми, и новыми
        all_mics = [probe(m["path"]) for m in old["mics"]] + fresh_mics
        new = analyze(videos, all_mics, settings, progress, cancelled,
                      on_proxy=(lambda i, *a, **k: on_proxy(i + nc, *a, **k)) if on_proxy else None,
                      screens=screens)
        mic_offset = 0
    # склейка разборов
    for c in new["clips"]:
        if mic_offset and c["sync"].get("mic") is not None:
            c["sync"] = {**c["sync"], "mic": c["sync"]["mic"] + mic_offset}
        old["clips"].append(c)
    if mic_offset:
        old["mics"] += new["mics"]
    else:
        old["mics"] = new["mics"]       # тот же список, только длиннее
    for s in new.get("screens") or []:
        if mic_offset and s["sync"].get("mic") is not None:
            s["sync"] = {**s["sync"], "mic": s["sync"]["mic"] + mic_offset}
        old.setdefault("screens", []).append(s)
    for w in new["words"]:
        w["clip"] += nc
        w["phrase"] += n_ph
        old["words"].append(w)
    for p in new["phrases"]:
        p["id"] += n_ph
        p["clip"] += nc
        p["words"] = [i + nw for i in p["words"]]
        if "group" in p:
            p["group"] += n_ph
        old["phrases"].append(p)
    for key in ("env", "thr", "low", "peaks", "per", "vad"):
        old.setdefault(key, [None] * nc)
        old[key] = list(old[key]) + list(new.get(key) or [None] * len(new["clips"]))
    hints = dict(old.get("llm") or {})
    for k, v in (new.get("llm") or {}).items():
        hints[int(k) + n_ph] = {**v, "by": (v["by"] + n_ph) if isinstance(v.get("by"), int) else v.get("by")}
    old["llm"] = hints
    old.setdefault("more_proxies", []).append(new.get("proxies"))
    for k in ("_breaths", "_onsets", "_offsets"):
        old.pop(k, None)
    classify(old, settings)          # дубли — по всему материалу: новый дубль может заменить старый
    return len(new["clips"])


def add_extra(analysis: dict, files: list[MediaInfo], progress=None) -> list[dict]:
    """Добавить видео на дополнительные дорожки уже после обработки: синхронизация по микрофону,
    без повторного распознавания речи."""
    from .media import probe

    mics = [probe(m["path"]) for m in analysis["mics"]]
    files = [f for f in files if f.has_video]
    if not files:
        return []
    res = sync_videos(files, mics, progress=progress)
    added = []
    for f, r in zip(files, res):
        c = _clip_dict(f)
        c["sync"] = {"mic": r.mic_index, "offset": r.offset, "confidence": r.confidence, "ok": r.ok}
        c["kind"] = "added"
        added.append(c)
    analysis.setdefault("screens", []).extend(added)
    assign_tracks(analysis["screens"])
    return added


def public_screens(analysis: dict) -> list[dict]:
    return [{"name": s["name"], "duration": s["duration"], "sync": s["sync"], "direct": s["direct"],
             "track": s.get("track", 0), "kind": s.get("kind", "screen")} for s in analysis.get("screens") or []]


def classify(analysis: dict, settings: dict) -> None:
    # пороги, выученные на ручном монтаже («Учиться на моих правках»), если есть
    learned = (settings.get("learned") or {}).get("params") or {}
    extra = {k: learned[k] for k in ("pair_cov", "continuation_gap") if k in learned}
    takes.classify(analysis["words"], analysis["phrases"], enabled=settings.get("drop_bad_takes", True),
                   prefer=settings.get("prefer_take", "last"), llm=analysis.get("llm"),
                   strictness=settings.get("takes_strictness", "medium"), **extra)


def public_analysis(analysis: dict) -> dict:
    """То, что уходит в интерфейс."""
    W = analysis["words"]
    return {
        "clips": [{"name": c["name"], "duration": c["duration"], "sync": c["sync"], "ready": c.get("proxy_ready", False),
                   "sepAudio": bool(c.get("audio_src")), "aOff": round(c.get("audio_offset", 0.0), 4),
                   "direct": bool(c.get("direct")), "lightReady": bool(c.get("light_ready")), "halfReady": bool(c.get("half_ready")),
                   "fps": round(c["fps_num"] / c["fps_den"], 3) if c.get("fps_num") and c.get("fps_den") else 25,
                   "w": c.get("width") or 0, "h": c.get("height") or 0, "audioOnly": bool(c.get("audio_only"))}
                  for c in analysis["clips"]],
        "mics": [m["name"] for m in analysis["mics"]],
        "screens": public_screens(analysis),
        "phrases": [
            {"id": p["id"], "clip": p["clip"], "start": round(p["start"], 3), "end": round(p["end"], 3),
             "auto": p["auto"], "reason": p["reason"], "take": p["take"], "takes": p["takes"], "group": p.get("group", p["id"]), "w0": p["words"][0],
             "words": [[W[i]["w"], 1 if W[i]["cut"] else 0, round(W[i]["s"], 2)] for i in p["words"]]}
            for p in analysis["phrases"]
        ],
    }
