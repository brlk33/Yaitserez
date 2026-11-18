"""Построение монтажа: какие куски каких клипов идут на таймлайн.

Паузы. На каждой склейке остаётся пауза заданной длины. Откуда она берётся, решает настройка:
по умолчанию — из конца клипа ПЕРЕД склейкой (договорил и чуть помолчал), а следующий клип
начинается почти сразу перед словом — так удобно делать J-cut и не захватывается вдох.

Вдохи. Вдох — шум без низких частот голоса. В паузах такие участки не попадают в монтаж,
а короткая пауза с вдохом внутри разрезается, даже если она короче порога.

Слова. Отдельные слова можно вырезать, не трогая фразу: мат, «э-э / м-м», свой список, ручные правки.
"""
from __future__ import annotations

import re
from bisect import bisect_right

import numpy as np

from .takes import is_profane, norm

ENV_FPS = 100  # частота огибающей громкости

FILLERS = {"э", "ээ", "эээ", "э-э", "э-э-э", "эм", "эмм", "м", "мм", "ммм", "м-м", "хм", "а-а", "uh", "um", "uhm", "erm", "hmm"}


def envelope(audio16k: np.ndarray) -> np.ndarray:
    """Громкость в дБ, 100 значений в секунду."""
    hop = 16000 // ENV_FPS
    n = len(audio16k) // hop
    if n == 0:
        return np.full(1, -100.0, dtype=np.float32)
    frames = audio16k[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12)
    return (20 * np.log10(rms)).astype(np.float32)


PEAK_FPS = 200


def peaks(audio16k: np.ndarray) -> bytes:
    """Пики волны для дорожки A1, как в Premiere: 200 значений в секунду, 0–255 (мягкая кривая,
    чтобы тихая речь тоже была видна)."""
    hop = 16000 // PEAK_FPS
    n = len(audio16k) // hop
    if n == 0:
        return b"\0"
    p = np.abs(audio16k[: n * hop].reshape(n, hop)).max(axis=1)
    v = np.clip(p, 0.0, 1.0) ** 0.6 * 255.0
    return v.astype(np.uint8).tobytes()


_VAD = None


def voice_prob(audio16k: np.ndarray) -> np.ndarray | None:
    """Вероятность голоса от нейросети Silero VAD (она уже есть внутри faster-whisper), 0…255,
    100 значений в секунду. Голос — 0,9…1, вдох и дыхание в микрофон — 0,2…0,6, тишина — около нуля.
    Четыре часа записи — секунд двадцать на процессоре."""
    global _VAD
    try:
        if _VAD is None:
            from faster_whisper.vad import get_vad_model
            _VAD = get_vad_model()
        n = len(audio16k) // 512 * 512
        if n == 0:
            return None
        p = _VAD(np.ascontiguousarray(audio16k[:n], dtype=np.float32)).reshape(-1)   # по 32 мс
    except Exception:  # noqa: BLE001 — без нейросети работаем по громкости и спектру
        return None
    frames = int(len(audio16k) * ENV_FPS // 16000)
    idx = np.minimum((np.arange(frames) * (16000 / ENV_FPS) / 512).astype(np.int64), len(p) - 1)
    return np.clip(p[idx] * 255.0, 0, 255).astype(np.uint8)


def periodicity(audio16k: np.ndarray) -> np.ndarray:
    """Насколько звук периодичен (есть высота тона), 0…1, 100 значений в секунду.
    У голоса 0,5–0,8; у вдоха, дыхания в микрофон, щелчков и мычания сквозь нос — ниже.
    Считается автокорреляцией на 50 кадрах в секунду и растягивается вдвое — быстро и для часов записи."""
    hop, win = 320, 512
    n = max(0, (len(audio16k) - win) // hop + 1)
    out = np.zeros(max(n, 1), dtype=np.float16)
    if n == 0:
        return np.repeat(out, 2)
    d = np.diff(audio16k.astype(np.float32), prepend=np.float32(0.0))   # без гула и ветра в микрофоне
    w = np.hanning(win).astype(np.float32)
    for s in range(0, n, 20000):
        m = min(20000, n - s)
        idx = (np.arange(m)[:, None] + s) * hop + np.arange(win)[None, :]
        f = np.fft.rfft(d[idx] * w, 1024, axis=1)
        r = np.fft.irfft(np.abs(f) ** 2, axis=1)[:, :240]
        out[s:s + m] = (r[:, 40:230].max(axis=1) / (r[:, 0] + 1e-9)).astype(np.float16)
    return np.repeat(out, 2)


def lowband(audio16k: np.ndarray) -> np.ndarray:
    """Доля энергии 80–900 Гц (основа голоса) в полосе 80–8000 Гц, 100 значений в секунду.
    У голоса она высокая, у вдоха (шум) — низкая."""
    hop, win = 160, 512
    n = max(0, (len(audio16k) - win) // hop + 1)
    out = np.zeros(max(n, 1), dtype=np.float16)
    if n == 0:
        return out
    window = np.hanning(win).astype(np.float32)
    lo = slice(int(80 / 31.25), int(900 / 31.25) + 1)
    al = slice(int(80 / 31.25), win // 2 + 1)
    step = 20000
    x = np.ascontiguousarray(audio16k.astype(np.float32))
    for s in range(0, n, step):
        m = min(step, n - s)
        idx = (np.arange(m)[:, None] + s) * hop + np.arange(win)[None, :]
        spec = np.abs(np.fft.rfft(x[idx] * window, axis=1)) ** 2
        out[s:s + m] = (spec[:, lo].sum(1) / (spec[:, al].sum(1) + 1e-12)).astype(np.float16)
    return out


def speech_threshold(env: np.ndarray) -> float:
    floor = float(np.percentile(env, 15))
    peak = float(np.percentile(env, 95))
    return floor + max(6.0, 0.3 * (peak - floor))


UNVOICED = set("сшфхчцщктпsfhkptc")
PLOSIVE = set("кптчцkptc")       # смычка + щелчок: до 0,12 с перед гласной
FRICATIVE = set("сшщфхsfh")      # шипящие: до 0,18 с


VOWELS = set("аеёиоуыэюяaeiouy")
VAD_VOICE = 190     # 0,75: нейросеть уверена — голос
VAD_BREATH = 165    # меньше 0,65: звук не голос (вдох, дыхание, щелчок)
VOICED_C = set("взжбдглмнрйvzbdglmnrwj")


def consonant_room(letter: str) -> float:
    """Сколько звука до/после гласной может занимать глухая согласная на краю слова."""
    return 0.12 if letter in PLOSIVE else 0.18 if letter in FRICATIVE else 0.0


def _cluster_room(cluster: str, tail: bool) -> float:
    room = 0.0
    for ch in cluster:
        if ch in "чц":
            room += 0.16   # «ч» в «что», «чтобы» звучит как «ш» — длинный шум
        elif ch in PLOSIVE:
            room += 0.10
        elif ch in FRICATIVE:
            room += 0.15
        elif ch in VOICED_C:
            room += 0.08   # «в» перед «т» звучит как «ф», «з» как «с» — тоже шум, тоже часть слова
    if tail and cluster.endswith(("ь", "ъ")):
        room += 0.05       # мягкий конец («ть», «сь») тянется дольше
    return min(room, 0.32)


def head_room(word: str) -> tuple[float, bool]:
    """(запас на согласные перед первой гласной, есть ли среди них смычка)."""
    w = "".join(ch for ch in word.lower() if ch.isalpha())
    i = next((k for k, ch in enumerate(w) if ch in VOWELS), len(w))
    cl = w[:i]
    return _cluster_room(cl, False), any(ch in PLOSIVE for ch in cl)


def tail_room(word: str) -> tuple[float, bool]:
    w = "".join(ch for ch in word.lower() if ch.isalpha())
    i = max((k for k, ch in enumerate(w) if ch in VOWELS), default=-1)
    cl = w[i + 1:]
    return _cluster_room(cl, True), any(ch in PLOSIVE for ch in cl)


def strong_level(env: np.ndarray) -> float:
    """Громкость, с которой начинается настоящий голос (выше вдохов, мычания и шума комнаты)."""
    floor = float(np.percentile(env, 15))
    peak = float(np.percentile(env, 95))
    return floor + max(15.0, 0.42 * (peak - floor))


def tighten_words(ws: list[dict], env: np.ndarray, low: np.ndarray, per: np.ndarray | None = None,
                  vad: np.ndarray | None = None) -> list[dict]:
    """Whisper иногда растягивает слово на секунды: прячет в него вдох и «ам» перед фразой или
    долгую паузу после брошенного дубля. По звуку возвращаем слову настоящие границы."""
    if not len(env):
        return ws
    lowf = low.astype(np.float32)
    strong = strong_level(env)
    n = min(len(env), len(lowf))
    voiced = (env[:n] > strong) & (lowf[:n] >= 0.55)
    if vad is not None:   # «ам» нейросеть считает голосом — это нам и нужно: ищем разрывы между звуками речи
        n = min(n, len(vad))
        voiced = voiced[:n] & (vad[:n] >= VAD_VOICE)
    out = [dict(w) for w in ws]
    for k, w in enumerate(out):
        letters = sum(ch.isalpha() for ch in w["w"])
        lim = min(0.3 + 0.1 * letters, 1.6)
        if w["e"] - w["s"] <= lim + 0.25:
            continue
        a, b = max(0, int(w["s"] * ENV_FPS)), min(n, int(w["e"] * ENV_FPS) + 1)
        segs, start = [], None
        for i in range(a, b):
            if voiced[i] and start is None:
                start = i
            elif not voiced[i] and start is not None:
                segs.append([start, i]); start = None
        if start is not None:
            segs.append([start, b])
        clusters = []
        for s0, e0 in segs:
            if clusters and s0 - clusters[-1][1] < 30:   # разрыв меньше 0,3 с — то же слово
                clusters[-1][1] = e0
            else:
                clusters.append([s0, e0])
        if not clusters:
            continue
        prev = out[k - 1] if k > 0 else None
        glued_prev = prev is not None and w["s"] - prev["e"] < 0.06
        if len(clusters) == 1:   # одно слово и долгая тишина вокруг: обрезаем растянутый край
            if glued_prev:
                w["e"] = round(min(w["e"], clusters[0][1] / ENV_FPS + 0.15), 3)
            else:
                w["s"] = round(max(w["s"], clusters[0][0] / ENV_FPS - 0.15), 3)
            continue
        if glued_prev:   # слово продолжает речь — оно в начале, дальше пауза (брошенный дубль)
            w["e"] = round(min(w["e"], clusters[0][1] / ENV_FPS + 0.08), 3)
        else:            # перед словом — вдох или «ам», само слово в конце
            w["s"] = round(max(w["s"], clusters[-1][0] / ENV_FPS - 0.12), 3)
    return out


def breath_params(sens: float) -> tuple[float, float, int]:
    """Чувствительность 0…1 → (на сколько дБ громче тишины, макс. доля низких частот, мин. длина в кадрах по 10 мс)."""
    sens = min(max(sens, 0.0), 1.0)
    return 8.0 - 6.0 * sens, 0.35 + 0.32 * sens, int(round(13 - 9 * sens))


def detect_breaths(env: np.ndarray, low: np.ndarray, spans: list[tuple[float, float]],
                   sens: float = 0.6, per: np.ndarray | None = None, vad: np.ndarray | None = None) -> list[tuple[float, float]]:
    """Участки-вдохи между словами: громче тишины, но без голоса (нет низких частот или нет высоты тона)."""
    n = min(len(env), len(low))
    if per is not None:
        n = min(n, len(per))
    if n == 0:
        return []
    db, low_max, min_len = breath_params(sens)
    floor = float(np.percentile(env[:n], 15))
    cand = (env[:n] > floor + db) & (low[:n].astype(np.float32) < low_max)
    if vad is not None:
        n = min(n, len(vad))
        cand = (env[:n] > floor + db) & (vad[:n] < VAD_BREATH)
    elif per is not None:
        strong = strong_level(env[:n])
        cand |= (env[:n] > floor + db + 2) & (per[:n].astype(np.float32) < 0.3) & (env[:n] < strong + 4)
    inside = np.zeros(n, dtype=bool)
    for s, e in spans:  # внутри слов — не вдох (это шипящие и т. п.)
        a, b = max(0, int((s - 0.03) * ENV_FPS)), min(n, int((e + 0.03) * ENV_FPS) + 1)
        inside[a:b] = True
    cand &= ~inside
    out, start, hole = [], None, 0
    for i in range(n):
        if cand[i]:
            if start is None:
                start = i
            hole = 0
        elif start is not None:
            hole += 1
            if hole > 3:
                end = i - hole + 1
                if end - start >= min_len:
                    out.append((start / ENV_FPS, end / ENV_FPS))
                start, hole = None, 0
    if start is not None and n - start >= min_len:
        out.append((start / ENV_FPS, n / ENV_FPS))
    return out


class Edges:
    """Настоящие края голоса у слова и вдохи рядом с ними.

    Whisper ставит начало первого слова в среднем на 0,18 с раньше голоса — туда часто попадает вдох.
    Здесь начало ищется по самому звуку: первый кадр, где громко и много низких частот (голос).
    """

    def __init__(self, env, low, thr, sens, per=None, vad=None):
        self.env = env
        self.low = low.astype(np.float32)
        self.per = per.astype(np.float32) if per is not None else None
        self.vad = vad
        self.n = min(len(env), len(low), len(per) if per is not None else 1 << 30, len(vad) if vad is not None else 1 << 30)
        self.thr = thr
        self.floor = float(np.percentile(env[:self.n], 15)) if self.n else -100.0
        self.db, self.low_max, self.min_len = breath_params(sens)

        self.strong = strong_level(env[:self.n]) if self.n else 0.0

    def voiced(self, k):
        # голос — громко и с низкими частотами; тихое мычание, вдох и щелчок языком сюда не попадают
        return 0 <= k < self.n and self.low[k] >= 0.55 and self.env[k] > self.strong

    def tonal(self, k):
        """Опорный кадр голоса: нейросеть уверена, что это голос (без неё — высота тона или громкость)."""
        if self.vad is not None:
            return 0 <= k < self.n and self.vad[k] >= VAD_VOICE and self.env[k] > self.floor + 6
        if self.per is None:
            return self.voiced(k)
        return 0 <= k < self.n and self.per[k] >= 0.5 and self.env[k] > self.strong - 4

    def anchor(self, k):
        return sum(self.tonal(k + j) for j in range(4)) >= 3

    def loud(self, k):
        return 0 <= k < self.n and self.env[k] > self.strong

    def breathy(self, k):
        if not (0 <= k < self.n and self.env[k] > self.floor + self.db):
            return False
        if self.vad is not None:   # звучит, но не голос — вдох, дыхание, щелчок
            return self.vad[k] < VAD_BREATH
        if self.low[k] < self.low_max:
            return True
        # дыхание в микрофон низкочастотное, но без высоты тона и тише голоса
        return self.per is not None and self.per[k] < 0.3 and self.env[k] < self.strong + 4 and self.env[k] > self.floor + self.db + 2

    def onset(self, t_from: float, t_word: float) -> float | None:
        """Начало голоса: первая опора с высотой тона от t_from до t_word + 0,8 с, и от неё назад —
        пока звук громкий, как голос (так в начало попадают «е» и «щ» перед опорной «ё»,
        а вдох, дыхание в микрофон и мычание — нет)."""
        a, b = int(t_from * ENV_FPS), min(self.n - 4, int((t_word + 0.8) * ENV_FPS))
        for k in range(max(0, a), b):
            if self.anchor(k):
                j, gap, start = k - 1, 0, k
                while j >= max(a, 0):
                    if self.loud(j):
                        start, gap = j, 0
                    else:
                        gap += 1
                        if gap > 2:
                            break
                    j -= 1
                return start / ENV_FPS
        return None

    def offset(self, t_word_end: float, t_to: float) -> float | None:
        """Конец голоса: последняя опора с высотой тона перед t_to (назад до t_word_end − 0,6 с),
        и от неё вперёд, пока звук громкий, как голос."""
        a, b = int((t_word_end - 0.6) * ENV_FPS), int(t_to * ENV_FPS)
        for k in range(min(b, self.n - 4), max(a, 2), -1):
            if self.anchor(k):
                j, gap, end = k + 4, 0, k + 4
                while j < min(b, self.n):
                    if self.loud(j) or (self.vad is not None and self.vad[j] >= VAD_VOICE and self.env[j] > self.floor + 6):
                        end, gap = j + 1, 0
                    else:
                        gap += 1
                        if gap > 2:
                            break
                    j += 1
                return end / ENV_FPS
        return None

    def sounding(self, k):
        return 0 <= k < self.n and self.env[k] > self.floor + self.db

    def sound_before(self, t_on: float, max_back: float, t_limit: float, max_gap: int = 6) -> float:
        """Начало звучания слова: от начала голоса назад, пока есть звук (смычка до 60 мс не прерывает).
        Так в слово попадают глухие начала — «к», «т», «п», «с» — а не только гласная."""
        k = int(t_on * ENV_FPS) - 1
        lo = max(int((t_on - max_back) * ENV_FPS), int(t_limit * ENV_FPS), 0)
        start, gap, breath_run = int(t_on * ENV_FPS), 0, 0
        while k >= lo:
            # тихий звук «не голос» с низкими частотами — это вдох, а не согласная: дальше не идём
            # (у «с», «ш», «ф», «т» шум громче и почти без низких частот)
            if self.vad is not None and self.sounding(k) and self.vad[k] < VAD_BREATH                     and self.env[k] < self.floor + 10 and self.low[k] > 0.12:
                breath_run += 1          # похоже на вдох; одиночные кадры — хвост согласной, 40 мс подряд — уже вдох
                if breath_run >= 4:
                    break
                k -= 1
                continue
            breath_run = 0
            if self.sounding(k):
                start, gap = k, 0
            else:
                gap += 1
                if gap > max_gap:
                    break
            k -= 1
        return start / ENV_FPS

    def sound_after(self, t_off: float, max_fwd: float, t_limit: float) -> float:
        """Конец звучания слова: после конца голоса вперёд — смычка и щелчок «к»/«т» тоже часть слова."""
        k = int(t_off * ENV_FPS)
        hi = min(int((t_off + max_fwd) * ENV_FPS), int(t_limit * ENV_FPS), self.n)
        end, gap = int(t_off * ENV_FPS), 0
        while k < hi:
            if self.sounding(k):
                end, gap = k + 1, 0
            else:
                gap += 1
                if gap > 6:
                    break
            k += 1
        return end / ENV_FPS

    def breath_before(self, t: float, t_limit: float) -> tuple[float, float] | None:
        """Вдох, кончающийся перед моментом t (ищем назад до t_limit). Тишина > 0,15 с прерывает поиск."""
        k, lo = int(t * ENV_FPS) - 1, max(0, int(t_limit * ENV_FPS))
        end = start = None
        quiet = 0
        count = 0
        while k >= lo:
            if self.breathy(k):
                if end is None:
                    end = k + 1
                start = k
                count += 1
                quiet = 0
            else:
                quiet += 1
                if quiet > (15 if end is None else 4):
                    break
            k -= 1
        if end is not None and count >= self.min_len:
            return start / ENV_FPS, end / ENV_FPS
        return None

    def breath_after(self, t: float, t_limit: float) -> tuple[float, float] | None:
        """Вдох/выдох, начинающийся после момента t (ищем вперёд до t_limit)."""
        k, hi = int(t * ENV_FPS), min(self.n, int(t_limit * ENV_FPS))
        start = end = None
        quiet = 0
        count = 0
        while k < hi:
            if self.breathy(k):
                if start is None:
                    start = k
                end = k + 1
                count += 1
                quiet = 0
            else:
                quiet += 1
                if start is not None and quiet > 4:
                    break
            k += 1
        if start is not None and count >= self.min_len:
            return start / ENV_FPS, end / ENV_FPS
        return None


def _refine(env: np.ndarray, thr: float, t: float, direction: int, limit: float, stop: float | None = None) -> float:
    """Подтянуть границу слова по громкости (Whisper ставит их неточно), не заходя за stop."""
    f = int(round(t * ENV_FPS))
    steps = int(limit * ENV_FPS)
    best = f
    for k in range(1, steps + 1):
        g = f + direction * k
        if g < 0 or g >= len(env):
            break
        if stop is not None and (g / ENV_FPS <= stop if direction < 0 else g / ENV_FPS >= stop):
            break
        if env[g] > thr:
            best = g
        elif abs(g - best) > 3:  # 30 мс тишины — дальше не ищем
            break
    t2 = best / ENV_FPS
    return min(t, t2) if direction < 0 else max(t, t2)


def effective_status(p: dict, overrides: dict) -> str:
    return overrides.get(str(p["id"]), p["auto"])


def word_cut_reasons(analysis: dict, settings: dict, word_overrides: dict | None = None) -> dict[int, str]:
    """{индекс слова: причина} для слов, которые вырезаются сами по себе."""
    words = analysis["words"]
    out: dict[int, str] = {}
    use_takes = settings.get("drop_bad_takes", True)
    for i, w in enumerate(words):
        if w["cut"] and use_takes:
            out[i] = "repeat"
        elif settings.get("cut_profanity", True) and is_profane(w["n"]):
            out[i] = "profanity"
        elif settings.get("cut_fillers", True) and (w["n"] in FILLERS or re.fullmatch(r"(э+|м+|хм+|а+м+|э+м+|аа+|ы+м*)(-[аэм]+)*", w["n"])):
            out[i] = "filler"
    # свой список слов и фраз
    patterns = [[norm(x) for x in str(p).split() if norm(x)] for p in settings.get("cut_words", []) or []]
    patterns = [p for p in patterns if p]
    if patterns:
        n = len(words)
        for i in range(n):
            for pat in patterns:
                k = len(pat)
                if i + k <= n and all(_match(words[i + j]["n"], pat[j]) for j in range(k)) \
                        and len({words[i + j]["phrase"] for j in range(k)}) == 1:
                    for j in range(k):
                        out[i + j] = "custom"
    for k, v in (word_overrides or {}).items():
        k = int(k)
        if v == "cut":
            out[k] = "manual"
        elif v == "keep":
            out.pop(k, None)
    return out


def _match(word: str, pat: str) -> bool:
    """«блин*» — по началу слова, иначе точное совпадение (без учёта регистра и ё)."""
    return word.startswith(pat[:-1]) if pat.endswith("*") else word == pat


def build_plan(analysis: dict, settings: dict, overrides: dict, word_overrides: dict | None = None,
               trims: dict | None = None) -> dict:
    """Склейки по звуковой волне.

    У каждого куска речи есть «ядро» — от начала голоса до конца голоса (по волне, не по тексту),
    и «чистая тишина» вокруг: до соседних слов и до вдохов. На каждой склейке остаётся одна и та же
    пауза `pause`: её набираем из чистой тишины в конце предыдущего куска и/или перед следующим
    (настройка pause_place; «auto» — так, чтобы не захватить вдох). pause < 0 — наезд: склейка
    случается раньше, чем договорено.
    """
    clips = analysis["clips"]
    words = analysis["words"]
    phrases = analysis["phrases"]
    remove_silence = settings.get("remove_silence", True)
    keep_alts = settings.get("keep_alternates", True)
    cut_breaths = settings.get("cut_breaths", True)
    sens = float(settings.get("breath_sens", 0.6))
    breath_split = settings.get("breath_mode", "all") != "edges"   # «edges»: вдохи режем только между дублями
    pause = float(settings.get("pause", settings.get("keep_pause", 0.25)))
    place = settings.get("pause_place", "auto")
    equalize = settings.get("equalize", True)
    pos_pause = max(pause, 0.0)
    if equalize:
        max_pause = pos_pause + 0.08          # каждая пауза длиннее заданной сжимается — паузы звучат одинаково
    else:
        max_pause = max(float(settings.get("max_pause", 0.5)), pos_pause + 0.02)

    status = {p["id"]: effective_status(p, overrides) for p in phrases}
    cut_words = word_cut_reasons(analysis, settings, word_overrides)

    lows = analysis.get("low") or []
    edges: dict[int, Edges] = {}
    breaths: dict[int, list] = {}
    cache = analysis.setdefault("_breaths", {})
    for ci in range(len(clips)):
        if ci < len(lows):
            pers = analysis.get("per") or []
            per = pers[ci] if ci < len(pers) else None
            vads = analysis.get("vad") or []
            vad = vads[ci] if ci < len(vads) else None
            edges[ci] = Edges(analysis["env"][ci], lows[ci], analysis["thr"][ci], sens, per, vad)
            if cut_breaths:
                key = (ci, round(sens, 2))
                if key not in cache:
                    spans = [(w["s"], w["e"]) for w in words if w["clip"] == ci]
                    cache[key] = detect_breaths(analysis["env"][ci], lows[ci], spans, sens, per, vad)
                breaths[ci] = cache[key]
    starts = {ci: [b[0] for b in v] for ci, v in breaths.items()}

    def breath_in(ci: int, a: float, b: float):
        if ci not in breaths:
            return None
        lst = breaths[ci]
        k = max(0, bisect_right(starts[ci], a) - 1)
        while k < len(lst) and lst[k][0] < b:
            if lst[k][1] > a:
                return lst[k]
            k += 1
        return None

    onset_cache = analysis.setdefault("_onsets", {})

    def word_onset(i: int):
        """(начало голоса у слова i, вдох прямо перед ним или None)."""
        key = (i, round(sens, 2), cut_breaths, 3)
        if key not in onset_cache:
            w = words[i]
            ed = edges.get(w["clip"])
            prev_e = words[i - 1]["e"] if i > 0 and words[i - 1]["clip"] == w["clip"] else 0.0
            if ed is None:
                onset_cache[key] = (w["s"], None)
            else:
                lim = prev_e + 0.02
                if not re.search(r"[аеёиоуыэюяaeiouy]", w["n"]):
                    on = max(w["s"], lim)  # слово без гласной («к», «с», «в») — берём как есть
                else:
                    # окно до конца слова: Whisper бывает растягивает слово, и голос в нём ближе к концу
                    on = ed.onset(max(w["s"] - 0.15, lim), max(w["s"], w["e"] - 0.7))
                    if on is None or on > w["e"]:
                        on = w["s"]
                room, plos = head_room(w["n"])
                # назад тянемся только на длину согласных, с которых слово начинается («вт», «чт», «ш»…);
                # дальше — кандидат во вдох. Без смычки разрыв больше 30 мс — это уже щелчок, не слово
                snd = ed.sound_before(on, room, lim, 6 if plos else 3) if room else on - 0.02
                snd = min(snd, on - 0.02)
                br = ed.breath_before(snd - 0.01, max(lim, snd - 1.5)) if cut_breaths else None
                onset_cache[key] = (snd, br)
        return onset_cache[key]

    offset_cache = analysis.setdefault("_offsets", {})

    def word_offset(i: int, hi: float):
        """(конец голоса у слова i, начало вдоха/выдоха сразу после него или None)."""
        key = (i, round(sens, 2), cut_breaths, round(hi, 2), 3)
        if key not in offset_cache:
            w = words[i]
            ed = edges.get(w["clip"])
            if ed is None:
                offset_cache[key] = (w["e"], None)
            else:
                off = ed.offset(w["e"], min(w["e"] + 0.25, hi))
                if off is None or off < w["s"]:
                    off = w["e"]
                room, _ = tail_room(w["n"])
                snd = ed.sound_after(off, room + 0.03, hi) if room else off + 0.03
                snd = max(snd, off + 0.03)
                stop = None
                if cut_breaths:
                    ba = ed.breath_after(snd + 0.01, min(snd + 1.5, hi + 0.03))
                    b2 = breath_in(w["clip"], snd, snd + 1.5)
                    cands = [x[0] for x in (ba, b2) if x is not None]
                    stop = min(cands) if cands else None
                offset_cache[key] = (snd, stop)
        return offset_cache[key]

    def runs_for(selected) -> list[list[int]]:
        """Непрерывные куски речи. Кусок рвётся на вырезанном слове, на паузе длиннее порога и на вдохе."""
        runs, cur = [], []
        for i in selected:
            if i in cut_words:
                continue
            w = words[i]
            prev = words[cur[-1]] if cur else None
            if prev is not None and i == cur[-1] + 1 and w["clip"] == prev["clip"] and (
                not remove_silence or (w["s"] - prev["e"] <= max_pause and not (
                    cut_breaths and breath_split and w["s"] - prev["e"] > 0.12
                    and (breath_in(w["clip"], prev["e"], w["s"]) or word_onset(i)[1])))
            ):
                cur.append(i)
            else:
                if cur:
                    runs.append(cur)
                cur = [i]
        if cur:
            runs.append(cur)
        return runs

    def core(run: list[int]) -> dict:
        """Ядро куска (голос по волне) и границы чистой тишины вокруг него."""
        first, last = words[run[0]], words[run[-1]]
        ci = first["clip"]
        dur = clips[ci]["duration"]
        prev_w = words[run[0] - 1] if run[0] > 0 and words[run[0] - 1]["clip"] == ci else None
        next_w = words[run[-1] + 1] if run[-1] + 1 < len(words) and words[run[-1] + 1]["clip"] == ci else None
        lo = prev_w["e"] + 0.03 if prev_w is not None else 0.0
        hi = next_w["s"] - 0.03 if next_w is not None else dur
        snd_on, br = word_onset(run[0])
        s0 = max(snd_on - 0.01, lo, 0.0)
        head_lim = max(lo, br[1] + 0.03) if br is not None else lo
        snd_off, stop = word_offset(run[-1], hi)
        e0 = min(snd_off + 0.01, max(hi, snd_off), dur)
        tail_lim = min(hi, stop - 0.04) if stop is not None else hi
        if not remove_silence:
            # без удаления тишины: начало и конец клипа сохраняем, паузы внутри не трогаем
            if prev_w is None:
                head_lim = 0.0
            if next_w is None:
                tail_lim = dur
        # где реально начинается и кончается звучание: у глухих согласных («с», «т»…) — с самим согласным
        vstart = s0
        vend = e0
        return {"clip": ci, "s0": round(s0, 3), "e0": round(max(e0, s0 + 0.05), 3),
                "vs": round(vstart, 3), "ve": round(max(vend, vstart + 0.05), 3),
                "hl": round(min(head_lim, s0), 3), "tl": round(max(tail_lim, e0), 3), "words": run,
                "lo": run[0], "hi": run[-1]}

    def distribute(a: dict, b: dict):
        """Пауза на склейке a→b — точно `pause` секунд от конца звучания a до начала звучания b:
        сколько тишины взять из хвоста a и сколько из головы b."""
        if pause < 0:  # наезд: обрываем конец фразы a, b начинается ровно с голоса
            a["out"] = max(a["vs"] + 0.08, a["ve"] + pause)
            b["in"] = b["vs"]
            return
        tail_room = max(0.0, a["tl"] - a["ve"])
        head_room = max(0.0, b["vs"] - b["hl"])
        if place == "head":
            head = min(pause, head_room)
            tail = min(pause - head, tail_room)
        elif place == "split":
            head = min(pause / 2, head_room)
            tail = min(pause - head, tail_room)
            head = min(pause - tail, head_room)
        elif place == "tail":
            tail = min(pause, tail_room)
            head = min(pause - tail, head_room)
        else:  # auto: чуть-чуть перед словом для естественной атаки, остальное — из чистого хвоста
            head = min(0.03, head_room, pause)
            tail = min(pause - head, tail_room)
            head = min(pause - tail, head_room)
        a["out"] = a["ve"] + tail
        b["in"] = b["vs"] - head

    def place_ranges(ranges: list[dict], sequence: bool):
        for r in ranges:
            r["in"], r["out"] = r["s0"], r["e0"]
        for k, r in enumerate(ranges):
            if not sequence or k == 0:
                r["in"] = r["s0"] - min(min(pos_pause, 0.1) if remove_silence else 0.15, r["s0"] - r["hl"])
                if not remove_silence and r["hl"] == 0.0:
                    r["in"] = 0.0
            if not sequence or k == len(ranges) - 1:
                r["out"] = r["e0"] + min(pos_pause if remove_silence else 0.18, r["tl"] - r["e0"])
                if not remove_silence and r["tl"] >= clips[r["clip"]]["duration"]:
                    r["out"] = clips[r["clip"]]["duration"]
        if sequence:
            for a, b in zip(ranges, ranges[1:]):
                contiguous = a["clip"] == b["clip"] and b["lo"] == a["hi"] + 1 and not any(
                    i in cut_words for i in range(a["hi"] + 1, b["lo"]))
                if not remove_silence and contiguous:
                    a["out"] = b["in"] = b["s0"]  # без удаления тишины соседние куски склеиваются как были
                elif contiguous and b["vs"] - a["ve"] <= pos_pause + 0.02 and pause >= 0 \
                        and not (breath_split and breath_in(a["clip"], a["ve"], b["vs"])):
                    a["out"] = b["in"] = b["vs"]  # пауза и так не длиннее заданной — не режем
                else:
                    distribute(a, b)
        # ручная подрезка краёв: поправка к автоматике, переживает смену настроек
        for r in ranges:
            if trims and "lo" in r:
                r["in"] += float(trims.get(f"i:{r['clip']}:{r['lo']}", 0.0))
                r["out"] += float(trims.get(f"o:{r['clip']}:{r['hi']}", 0.0))
        for r in ranges:
            r["in"] = round(max(0.0, r["in"]), 3)
            r["out"] = round(min(clips[r["clip"]]["duration"], max(r["out"], r["in"] + 0.05)), 3)

    has_words = {w["clip"] for w in words}
    main_sel = [i for i, w in enumerate(words) if status[w["phrase"]] == "main"]
    main_ranges = [core(r) for r in runs_for(main_sel)]
    main_ranges.sort(key=lambda r: (r["clip"], r["s0"]))
    place_ranges(main_ranges, True)
    if settings.get("keep_silent_clips", True):
        for ci, c in enumerate(clips):
            if ci not in has_words:
                main_ranges.append({"clip": ci, "in": 0.0, "out": c["duration"], "words": []})
        main_ranges.sort(key=lambda r: (r["clip"], r["in"]))
    main_ranges = _merge(main_ranges)

    alt_ranges = []
    if keep_alts:
        for p in phrases:
            if status[p["id"]] != "alt":
                continue
            rs = [core(r) for r in runs_for(p["words"])]
            place_ranges(rs, True)
            for rr in rs:
                rr["phrase"] = p["id"]
                alt_ranges.append(rr)

    phrase_ranges = {}
    if settings.get("_with_ranges", True):
        for p in phrases:
            rs = [core(r) for r in runs_for(p["words"])]
            if not rs:
                continue
            place_ranges(rs, True)
            phrase_ranges[str(p["id"])] = [[r["clip"], r["in"], r["out"]] for r in rs]

    t = 0.0
    timeline = []
    for r in main_ranges:
        d = r["out"] - r["in"]
        if d <= 0.04:
            continue
        timeline.append({**_public(r, words), "t": round(t, 3), "kind": "main"})
        t += d
    main_dur = t
    alt_start = None
    if alt_ranges:
        t += float(settings.get("alt_gap", 3.0))
        alt_start = t
        for r in alt_ranges:
            d = r["out"] - r["in"]
            if d <= 0.04:
                continue
            timeline.append({**_public(r, words), "t": round(t, 3), "kind": "alt", "phrase": r["phrase"]})
            t += d

    _attach_screens(analysis, timeline)
    orig = sum(c["duration"] for c in clips)
    n_breaths = sum(len(v) for v in breaths.values()) + sum(
        1 for k, v in onset_cache.items() if v[1] and k[1] == round(sens, 2) and k[2])
    return {
        "timeline": timeline,
        "duration": round(t, 3),
        "main_duration": round(main_dur, 3),
        "alt_start": alt_start,
        "statuses": {str(k): v for k, v in status.items()},
        "cut_words": {str(k): v for k, v in cut_words.items()},
        "pr": phrase_ranges,
        "stats": {
            "original": round(orig, 1),
            "result": round(main_dur, 1),
            "bad": sum(1 for v in status.values() if v == "bad"),
            "alt": sum(1 for v in status.values() if v == "alt"),
            "main": sum(1 for v in status.values() if v == "main"),
            "words_cut": len(cut_words),
            "breaths": n_breaths if cut_breaths else 0,
        },
    }


def _attach_screens(analysis: dict, timeline: list[dict]) -> None:
    """Для каждого куска находим тот же момент на каждой дополнительной дорожке (через время микрофона).
    it["scr"] = [[номер файла, время в нём], …] — по одному на дорожку."""
    screens = analysis.get("screens") or []
    if not screens:
        return
    clips = analysis["clips"]
    for it in timeline:
        c = clips[it["clip"]]
        sy = c["sync"]
        if not sy.get("ok"):
            continue
        mic_t = it["in"] + sy["offset"]
        dur = it["out"] - it["in"]
        best: dict[int, tuple] = {}
        for si, sc in enumerate(screens):
            ss = sc["sync"]
            if not ss.get("ok") or ss["mic"] != sy["mic"]:
                continue
            s_in = mic_t - ss["offset"]
            cover = min(s_in + dur, sc["duration"]) - max(s_in, 0.0)
            tr = sc.get("track", 0)
            if cover > 0.04 and (tr not in best or cover > best[tr][2]):
                best[tr] = (si, s_in, cover)
        if best:
            it["scr"] = [[v[0], round(v[1], 3)] for _t, v in sorted(best.items())]


def _merge(ranges: list[dict]) -> list[dict]:
    out: list[dict] = []
    for r in ranges:
        if out and out[-1]["clip"] == r["clip"] and r["in"] <= out[-1]["out"] + 0.02:
            out[-1]["out"] = max(out[-1]["out"], r["out"])
            out[-1]["words"] = out[-1]["words"] + r["words"]
            if "hi" in r:
                out[-1]["hi"] = r["hi"]
        else:
            out.append(dict(r))
    return out


def _public(r: dict, words: list[dict]) -> dict:
    phrases = sorted({words[i]["phrase"] for i in r["words"]})
    d = {"clip": r["clip"], "in": r["in"], "out": r["out"], "phrases": phrases}
    if "lo" in r:  # ключи краёв — для ручной подрезки
        d["ki"], d["ko"] = f"i:{r['clip']}:{r['lo']}", f"o:{r['clip']}:{r['hi']}"
    return d
