"""Стиль нарезки по образцу: готовый монтаж (XML Final Cut Pro 7 из Premiere / DaVinci или .prproj)
→ какую паузу монтажёр оставляет на склейке и оставляет ли вдохи → настройки Яйцереза.

На каждой склейке (следующий кусок — не продолжение предыдущего) слушаем исходник: сколько тишины
после голоса в конце куска и до голоса в начале следующего. Их сумма — пауза на склейке.
Вдох — звук без голоса (нейросеть VAD) в этой тишине.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote

import numpy as np

from . import cutter, premiere
from .i18n import L
from .media import load_audio

WIN = 1.5          # сколько секунд исходника слушаем с каждой стороны склейки
MAX_CUTS = 160     # больше не нужно для медианы, а читать звук долго
BREATH_SHARE = 0.35


class Cancelled(Exception):
    pass


def _url_path(url: str) -> str:
    p = unquote(url or "")
    if p.startswith("file://"):
        p = p[7:]
    if p.startswith("localhost"):
        p = p[9:]
    if len(p) > 2 and p[0] == "/" and p[2] == ":":
        p = p[1:]                      # /E:/… → E:/…
    return os.path.normpath(p)


def _fps(el, default: float) -> float:
    r = el.find("rate") if el is not None else None
    if r is None or not (r.findtext("timebase") or "").strip():
        return default
    tb = float(r.findtext("timebase"))
    return tb * 1000 / 1001 if (r.findtext("ntsc") or "").strip().upper() == "TRUE" else tb


def read_xml(path: str) -> tuple[str, list[dict]]:
    """(имя последовательности, куски основной дорожки) из XML Final Cut Pro 7 (xmeml)."""
    root = ET.parse(path).getroot()
    files = {}
    for f in root.iter("file"):
        if f.get("id") and f.findtext("pathurl"):
            files[f.get("id")] = _url_path(f.findtext("pathurl"))
    best = ("", [])
    for seq in root.iter("sequence"):
        fps = _fps(seq, 25.0)
        media = seq.find("media")
        if media is None:
            continue
        # основная дорожка — первая видеодорожка с кусками, без видео — первая звуковая
        tracks = [t for kind in ("video", "audio") for t in media.findall(f"{kind}/track") if t.find("clipitem") is not None]
        for tr in tracks[:1]:
            items, prev_end = [], 0.0
            for ci in tr.findall("clipitem"):
                f = ci.find("file")
                src = files.get(f.get("id")) if f is not None else None
                if not src:
                    continue
                r = _fps(ci, fps)
                start, end = int(ci.findtext("start") or -1), int(ci.findtext("end") or -1)
                a, b = int(ci.findtext("in") or 0), int(ci.findtext("out") or 0)
                t0 = start / r if start >= 0 else prev_end      # -1 — рядом переход
                t1 = end / r if end >= 0 else t0 + (b - a) / r
                items.append({"path": src, "start": t0, "end": t1, "in": a / r, "out": b / r})
                prev_end = t1
            if len(items) > len(best[1]):
                best = (seq.findtext("name") or "", items)
    return best


def read_prproj(path: str) -> tuple[str, list[dict]]:
    """То же из проекта Premiere: последовательность с наибольшим числом кусков на нижней видеодорожке."""
    best = ("", [])
    for name, items in premiere.sequences(path).items():
        vids = [x for x in items if x["kind"] == "video"]
        pool = vids or [x for x in items if x["kind"] == "audio"]
        if not pool:
            continue
        low = min(x["track"] for x in pool)
        main = [x for x in pool if x["track"] == low]
        if len(main) > len(best[1]):
            best = (name, main)
    return best


def read_edit(path: str) -> tuple[str, list[dict]]:
    if path.lower().endswith(".prproj"):
        return read_prproj(path)
    return read_xml(path)


def cut_pairs(items: list[dict]) -> list[tuple[dict, dict]]:
    """Соседние на таймлайне куски, между которыми настоящая склейка (вырезано что-то из исходника)."""
    items = sorted(items, key=lambda x: x["start"])
    out = []
    for a, b in zip(items, items[1:]):
        if b["start"] - a["end"] > 0.1:
            continue                    # дыра на таймлайне — не склейка
        if a["path"] == b["path"] and abs(b["in"] - a["out"]) < 0.08:
            continue                    # просто разрезанный кусок
        if a["out"] - a["in"] < 0.3 or b["out"] - b["in"] < 0.3:
            continue
        out.append((a, b))
    if len(out) > MAX_CUTS:
        step = len(out) / MAX_CUTS
        out = [out[int(i * step)] for i in range(MAX_CUTS)]
    return out


def _edge(audio: np.ndarray) -> tuple[np.ndarray, np.ndarray | None]:
    return cutter.envelope(audio), cutter.voice_prob(audio)


def _breath(env, vad, a: int, b: int, floor: float) -> bool:
    """Есть ли в отрезке [a, b) кадров вдох: звук громче тишины, но не голос, от 0,1 с."""
    if b - a < 10:
        return False
    seg = env[a:b] > floor + 6.0
    if vad is not None:
        seg &= vad[a:b] < cutter.VAD_BREATH
    run = best = 0
    for x in seg:
        run = run + 1 if x else 0
        best = max(best, run)
    return best >= 10


def measure(items: list[dict], progress=None, cancelled=lambda: False) -> dict:
    pairs = cut_pairs(items)
    if not pairs:
        raise RuntimeError(L("В монтаже не нашлось склеек — нужен смонтированный ролик, а не исходник",
                             "No cuts found in the edit — it must be an edited sequence, not raw footage"))
    missing = sorted({x["path"] for p in pairs for x in p if not os.path.isfile(x["path"])})
    pairs = [(a, b) for a, b in pairs if os.path.isfile(a["path"]) and os.path.isfile(b["path"])]
    if not pairs:
        raise RuntimeError(L("Не найдены исходники из монтажа: ", "Sources of the edit not found: ") +
                           ", ".join(os.path.basename(m) for m in missing[:4]))
    done = [0]

    def load(pair):
        if cancelled():
            raise Cancelled
        a, b = pair
        ta = max(0.0, a["out"] - WIN)
        tail = load_audio(a["path"], 16000, ta, a["out"] - ta)
        head = load_audio(b["path"], 16000, b["in"], min(WIN, b["out"] - b["in"]))
        done[0] += 1
        if progress:
            progress(0.9 * done[0] / len(pairs), L(f"Слушаю склейки: {done[0]} из {len(pairs)}",
                                                   f"Listening to cuts: {done[0]} of {len(pairs)}"))
        return (a["path"], _edge(tail)), (b["path"], _edge(head))

    with ThreadPoolExecutor(max_workers=4) as ex:
        sides = list(ex.map(load, pairs))

    # порог голоса — по всем кусочкам одного исходника
    by_file: dict[str, list] = {}
    for t, h in sides:
        for path, (env, _v) in (t, h):
            by_file.setdefault(path, []).append(env)
    thr, floor = {}, {}
    for path, envs in by_file.items():
        e = np.concatenate(envs)
        thr[path] = cutter.speech_threshold(e)
        floor[path] = float(np.percentile(e, 15))

    gaps, breaths, overlaps = [], 0, 0
    for (pa, (env_a, vad_a)), (pb, (env_b, vad_b)) in sides:
        loud_a = np.nonzero(env_a > thr[pa])[0]
        loud_b = np.nonzero(env_b > thr[pb])[0]
        if not len(loud_a) or not len(loud_b):
            continue                    # с одной стороны склейки нет голоса — не мерим
        last, first = int(loud_a[-1]), int(loud_b[0])
        tail = (len(env_a) - 1 - last) / cutter.ENV_FPS
        head = first / cutter.ENV_FPS
        if tail < 0.02:
            overlaps += 1               # кусок обрезан прямо по голосу
        gaps.append(tail + head)
        if _breath(env_a, vad_a, last + 5, len(env_a), floor[pa]) or _breath(env_b, vad_b, 0, max(0, first - 5), floor[pb]):
            breaths += 1
    if len(gaps) < 3:
        raise RuntimeError(L("Слишком мало склеек с речью, чтобы понять стиль", "Too few cuts with speech to learn the style"))
    g = np.array(gaps)
    pause = float(np.median(g))
    if overlaps > 0.5 * len(gaps):
        pause = min(pause, 0.0)         # режет встык и по голосу
    return {
        "cuts": len(gaps),
        "pause": round(min(max(pause, -0.3), 1.0), 2),
        "pause_lo": round(float(np.percentile(g, 25)), 2),
        "pause_hi": round(float(np.percentile(g, 75)), 2),
        "breath_share": round(breaths / len(gaps), 3),
        "overlap_share": round(overlaps / len(gaps), 3),
        "missing": [os.path.basename(m) for m in missing[:6]],
    }


def learn(path: str, settings: dict, progress=None, cancelled=lambda: False) -> dict:
    """Читает образец и возвращает отчёт с новыми настройками (ничего не сохраняет)."""
    if progress:
        progress(0.0, L("Читаю монтаж", "Reading the edit"))
    seq, items = read_edit(path)
    if not items:
        raise RuntimeError(L("В файле нет смонтированной последовательности", "The file has no edited sequence"))
    m = measure(items, progress, cancelled)
    cut_breaths = m["breath_share"] < BREATH_SHARE
    before = {k: settings.get(k) for k in ("pause", "cut_breaths", "remove_silence")}
    after = {"pause": m["pause"], "cut_breaths": cut_breaths, "remove_silence": True}
    return {"file": os.path.basename(path), "path": path, "sequence": seq, "pieces": len(items),
            **m, "before": before, "after": after}
