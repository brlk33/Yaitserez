"""Учимся на ручном монтаже.

Для каждого проекта берём итоговый монтаж человека (финал из Premiere, если рядом есть .prproj,
иначе ручную нарезку в самом Яйцерезе) и смотрим, какие слова он оставил. Дальше:

* подбираем настройки разбора дублей, при которых авто-нарезка ближе всего к его решениям
  (строгость, порог «модель + общие слова», пауза посреди предложения);
* собираем примеры его решений «эта фраза переговорена дальше / эта — нет» для нейросети;
* пишем отчёт: насколько авто-нарезка совпадала и совпадает теперь, что она оставляет лишнего.

Метрика — доля слов, где авто-нарезка и человек решили одинаково (оставить / вырезать).
"""
from __future__ import annotations

import datetime
import json
import math
import os
import pickle
import zipfile
from itertools import product

from . import cutter, premiere, takes
from .i18n import L

# что подбираем: значения по умолчанию — первые
GRID = {
    "takes_strictness": ["medium", "soft", "strict"],
    "pair_cov": [0.35, 0.25, 0.5],
    "continuation_gap": [2.2, 0.0, 1.5, 3.0],
}
DEFAULTS = {k: v[0] for k, v in GRID.items()}
MIN_GAIN = 0.003      # меньше — шум, оставляем как было
MAX_EXAMPLES = 6


class Cancelled(Exception):
    pass


def current_params(settings: dict) -> dict:
    """Настройки разбора дублей, с которыми программа режет сейчас."""
    learned = (settings.get("learned") or {}).get("params") or {}
    return {**DEFAULTS, **{k: v for k, v in learned.items() if k in GRID},
            "takes_strictness": settings.get("takes_strictness", DEFAULTS["takes_strictness"])}


def load_project(path: str) -> tuple[dict, dict]:
    with zipfile.ZipFile(path) as z:
        meta = json.loads(z.read("project.json").decode("utf-8"))
        an = pickle.loads(z.read("analysis.pkl"))
    return an, meta


def word_keep(words: list[dict], edl: list[dict]) -> list[bool]:
    """Слово в монтаже, если в него попала больше чем половина его длины."""
    by: dict[int, list] = {}
    for it in edl:
        by.setdefault(int(it["clip"]), []).append((float(it["in"]), float(it["out"])))
    for v in by.values():
        v.sort()
    out = []
    for w in words:
        d, s = max(w["e"] - w["s"], 1e-3), 0.0
        for a, b in by.get(w["clip"], []):
            if a >= w["e"]:
                break
            s += max(0.0, min(b, w["e"]) - max(a, w["s"]))
        out.append(s / d > 0.5)
    return out


def truth(an: dict, meta: dict, path: str, settings: dict) -> tuple[list[dict], str, str] | None:
    """(итоговый монтаж, откуда он, путь) или None, если человек ничего не правил."""
    try:
        fin = premiere.final_edit(an, os.path.dirname(path), float(settings.get("alt_gap", 3.0)))
    except Exception:  # noqa: BLE001
        fin = None
    if fin and len(fin[0]) >= 10:
        return fin[0], "premiere", fin[1]
    ui = meta.get("ui") or {}
    if ui.get("manual") and ui.get("edl"):
        return ui["edl"], "yaitserez", path
    return None


def _status_keep(an: dict, settings: dict, params: dict, hints: dict) -> list[bool]:
    """Быстрая оценка без построения склеек: слово остаётся, если его фраза основная и само слово
    не вырезано (мат, «э-э», повтор). Края кусков от настроек дублей не зависят."""
    words, phrases = an["words"], an["phrases"]
    takes.classify(words, phrases, enabled=settings.get("drop_bad_takes", True),
                   prefer=settings.get("prefer_take", "last"), llm=hints,
                   strictness=params["takes_strictness"], pair_cov=params["pair_cov"],
                   continuation_gap=params["continuation_gap"])
    cut = cutter.word_cut_reasons(an, settings, {})
    return [phrases[w["phrase"]]["auto"] == "main" and i not in cut for i, w in enumerate(words)]


def _agree(a: list[bool], b: list[bool]) -> float:
    return sum(x == y for x, y in zip(a, b)) / max(1, len(a))


def _examples(an: dict, keep: list[bool], hints: dict) -> tuple[list[dict], list[dict]]:
    """Примеры для нейросети: «переговорил дальше» (человек вырезал фразу и оставил похожую позже)
    и «не повтор» (модель считала повтором, а человек оставил)."""
    phrases = an["phrases"]
    n = len(phrases)
    df: dict[str, int] = {}
    for p in phrases:
        for st in takes._stems(p["tokens"]):
            df[st] = df.get(st, 0) + 1

    def weight(st):
        return math.log(1 + n / df.get(st, 1))

    def kept(p):
        return sum(keep[i] for i in p["words"]) / max(1, len(p["words"])) > 0.5

    pos, neg = [], []
    for k, p in enumerate(phrases):
        if not 4 <= len(p["tokens"]) <= 30:
            continue
        nx = [q for q in phrases[k + 1:k + 6] if q["clip"] == p["clip"] and q["start"] - p["end"] < 90]
        if not nx:
            continue
        item = {"a": p["text"], "nexts": [q["text"] for q in nx]}
        if not kept(p):
            best = max(nx, key=lambda q: takes._coverage(p, [q], weight)[0])
            cov, sh = takes._coverage(p, [best], weight)
            if kept(best) and cov >= 0.3 and sh >= 1:
                pos.append({**item, "n": nx.index(best) + 1})
        else:
            h = hints.get(p["id"])
            if h and h.get("why") == "repeat":
                neg.append({**item, "n": 0})
    return pos, neg


def _refresh_hints(an: dict, settings: dict, examples: list[dict], progress, cancelled) -> dict:
    """Подсказки нейросети текущей версии (с точечным проходом). Без модели — те, что сохранены в проекте."""
    from . import llm

    llm.CHOICE["model"] = settings.get("llm_model", "9b")
    if not llm.available():
        return an.get("llm") or {}
    lang = "en" if settings.get("language") == "en" else "ru"
    return llm.analyze(an["phrases"], lang, progress=progress, cancelled=cancelled, examples=examples)


def run(paths: list[str], settings: dict, progress=lambda fr, msg: None, cancelled=lambda: False,
        use_llm: bool = True) -> dict:
    """Возвращает {"params", "examples", "report"}; ничего не сохраняет."""
    projects = []
    n = len(paths)
    for k, path in enumerate(paths):
        if cancelled():
            raise Cancelled
        name = os.path.splitext(os.path.basename(path))[0]
        progress(k / max(1, n) * 0.1, L(f"Читаю проект {name}", f"Reading project {name}"))
        try:
            an, meta = load_project(path)
        except Exception as e:  # noqa: BLE001
            projects.append({"name": name, "path": path, "error": str(e)})
            continue
        st = {**settings, **{k2: v for k2, v in (meta.get("settings") or {}).items()
                             if k2 in ("cut_profanity", "cut_fillers", "cut_words", "drop_bad_takes", "prefer_take")}}
        tr = truth(an, meta, path, st)
        if tr is None:
            projects.append({"name": name, "path": path, "error": L("в проекте нет ручных правок",
                                                                     "the project has no manual edits")})
            continue
        fin_dur = sum(float(x["out"]) - float(x["in"]) for x in tr[0])
        auto_dur = sum(float(x["out"]) - float(x["in"]) for x in (meta.get("ui") or {}).get("autoEdl") or []) or             sum(w["e"] - w["s"] for w in an["words"])
        if fin_dur < 0.4 * auto_dur:
            projects.append({"name": name, "path": path, "error": L(
                "итоговый монтаж слишком короткий (" + f"{fin_dur / 60:.1f}".replace(".", ",") + " мин) — похоже на черновик, пропускаю",
                f"the final edit is too short ({fin_dur / 60:.1f} min) — looks like a draft, skipped")})
            continue
        projects.append({"name": name, "path": path, "an": an, "st": st, "edl": tr[0], "source": tr[1],
                         "source_path": tr[2], "keep": word_keep(an["words"], tr[0])})
    good = [p for p in projects if "an" in p]
    if not good:
        raise RuntimeError(L("Не нашлось проектов с ручными правками", "No projects with manual edits found"))

    # подсказки нейросети: сначала без примеров; примеры для каждого проекта — только из ДРУГИХ проектов
    for k, p in enumerate(good):
        if cancelled():
            raise Cancelled
        hints = p["an"].get("llm") or {}
        if use_llm:
            def prog(fr, msg, k=k):
                if cancelled():
                    raise Cancelled
                progress(0.1 + (k + fr) / len(good) * 0.75, f"{p['name']}: {msg}")
            try:
                hints = _refresh_hints(p["an"], p["st"], [], prog, cancelled)
            except Cancelled:
                raise
            except Exception:  # noqa: BLE001 — без модели учимся на сохранённых подсказках
                pass
        p["hints"] = hints

    # подбор настроек по всем проектам сразу
    progress(0.86, L("Подбираю настройки", "Tuning settings"))
    combos = [dict(zip(GRID, vals)) for vals in product(*GRID.values())]
    scores = []
    for c in combos:
        if cancelled():
            raise Cancelled
        tot = sum(_agree(_status_keep(p["an"], p["st"], c, p["hints"]), p["keep"]) * len(p["keep"]) for p in good)
        scores.append(tot / sum(len(p["keep"]) for p in good))
    base = scores[combos.index(DEFAULTS)]
    best_i = max(range(len(combos)), key=lambda i: (scores[i], combos[i] == DEFAULTS))
    params = combos[best_i] if scores[best_i] - base >= MIN_GAIN else dict(DEFAULTS)

    # отчёт по каждому проекту: точная оценка с настоящими склейками, до и после
    progress(0.93, L("Считаю, что изменилось", "Measuring the difference"))
    current = current_params(settings)
    rows, pos_all, neg_all = [], [], []
    for p in good:
        before = _full(p, current, p["an"].get("llm") or {})
        after = _full(p, params, p["hints"])
        pos, neg = _examples(p["an"], p["keep"], p["hints"])
        pos_all += pos
        neg_all += neg
        rows.append({"name": p["name"], "source": p["source"], "source_file": os.path.basename(p["source_path"]),
                     "words": len(p["keep"]), "before": before, "after": after})
    for p in projects:
        if "error" in p:
            rows.append({"name": p["name"], "error": p["error"]})
    examples = _pick(pos_all, MAX_EXAMPLES // 2) + _pick(neg_all, MAX_EXAMPLES - MAX_EXAMPLES // 2)
    return {
        "params": params,
        "examples": examples,
        "report": {"date": datetime.date.today().isoformat(), "projects": rows, "params": params,
                   "defaults": DEFAULTS, "changed": params != DEFAULTS, "n_examples": len(examples),
                   "llm": use_llm},
    }


def _pick(items: list[dict], k: int) -> list[dict]:
    """Короткие и разные: по одному из разных мест записи."""
    items = sorted(items, key=lambda x: len(x["a"]) + sum(map(len, x["nexts"])))
    if len(items) <= k:
        return items
    step = len(items) / k
    return [items[int(i * step)] for i in range(k)]


def _full(p: dict, params: dict, hints: dict) -> dict:
    """Точная оценка: настоящий план со склейками → какие слова попали в монтаж."""
    an, st = p["an"], p["st"]
    takes.classify(an["words"], an["phrases"], enabled=st.get("drop_bad_takes", True),
                   prefer=st.get("prefer_take", "last"), llm=hints, strictness=params["takes_strictness"],
                   pair_cov=params["pair_cov"], continuation_gap=params["continuation_gap"])
    plan = cutter.build_plan(an, st, {}, {}, {})
    auto = [x for x in plan["timeline"] if x["kind"] == "main"]
    ka = word_keep(an["words"], auto)
    words, keep = an["words"], p["keep"]
    extra = [i for i in range(len(words)) if ka[i] and not keep[i]]
    lost = [i for i in range(len(words)) if keep[i] and not ka[i]]

    def phrase_list(idx):
        """Фразы, которые почти целиком разошлись, — самые длинные первыми."""
        cnt: dict[int, int] = {}
        for i in idx:
            cnt[words[i]["phrase"]] = cnt.get(words[i]["phrase"], 0) + 1
        ph = [an["phrases"][k] for k, c in cnt.items() if c >= 0.8 * len(an["phrases"][k]["words"])]
        ph.sort(key=lambda x: -len(x["words"]))
        return [x["text"][:140] for x in ph[:6]]

    return {"agree": round(_agree(ka, keep), 4), "extra": len(extra), "lost": len(lost),
            "minutes": round(sum(x["out"] - x["in"] for x in auto) / 60, 1),
            "target_minutes": round(sum(float(x["out"]) - float(x["in"]) for x in p["edl"]) / 60, 1),
            "extra_examples": phrase_list(extra), "lost_examples": phrase_list(lost)}
