"""Разбор речи на фразы и поиск дублей.

Логика:
* фраза — кусок речи до знака конца предложения или длинной паузы;
* если фраза начинается заново внутри себя («Сегодня мы... Сегодня мы поговорим»), начало
  отрезается в отдельный фрагмент — это оборванный дубль;
* похожие фразы, идущие рядом, считаются дублями одной фразы;
* договорённый до конца дубль — удачный, оборванный — неудачный (в монтаж не идёт);
* из удачных в монтаж ставится последний (или первый — настройка), остальные — в запасные.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

TERMINAL = re.compile(r"[.!?…]+[»\"')\]]*$")
CUTOFF_END = re.compile(r"(\.\.\.|…|[-—–])[»\"')\]]*$")

HANGING = {
    "и", "а", "но", "или", "что", "чтобы", "в", "во", "на", "с", "со", "к", "ко", "по", "за", "из",
    "у", "о", "об", "от", "до", "для", "при", "про", "же", "который", "которая", "которые", "которое",
    "когда", "если", "потому", "ни",
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "at", "with", "for", "from", "that",
    "because", "so", "if", "when", "which", "who", "whose", "into", "about", "than", "my", "your", "our",
}
JUNK = {
    "э", "ээ", "эээ", "э-э", "э-э-э", "мм", "ммм", "м-м", "хм", "эм", "стоп", "блин", "заново", "ещё",
    "еще", "раз", "давай", "давайте", "сначала", "погоди", "подожди", "секунду", "сорри", "извините",
    "короче", "ну", "так", "ладно", "сейчас", "щас", "окей", "ок", "дубль", "снова", "ой", "um", "uh",
    "stop", "again", "sorry", "okay", "ok", "one", "more", "time", "take", "uhm", "erm", "hmm", "wait", "hold",
    "on", "let", "me", "start", "over", "redo", "cut", "damn", "oops", "sec", "second", "like", "so", "well",
}
# реплики самому себе / в сторону: «ладно, заново скажу», «если чё, вырежу», «зря я это записал».
# Выучено на ручном монтаже: такие фразы всегда уходили целиком, а не только мат в них.
ASIDE = re.compile(
    r"(заново скаж|скажу заново|скажу ещё раз|ещё раз скаж|давай заново|похуй заново|"
    r"вырежу|потом вырежу|если ч[её],? вырежу|зря (я )?(это )?(вообще )?записал|потом допишу|"
    r"наговорю|подзаеб|заебал|продолжаем хайп|^дальше идём,? погнали|^вроде вс[её] запустил|"
    r"^а,? я понял|^а,? нет|^ой|^так,? стоп|^стоп|"
    r"let me (say|do) (it|that) again|i'?ll cut (it|this)|start over)")
LEGIT_DOUBLES = {"да", "нет", "очень", "ну", "так", "ага", "вот", "давай", "very", "no", "yes"}
STOP = HANGING | {"я", "мы", "ты", "вы", "он", "она", "они", "мне", "нам", "все", "всё", "ну", "вот", "да"}


def norm(w: str) -> str:
    w = w.lower().replace("ё", "е")
    return re.sub(r"[^\w-]+", "", w).strip("-")


# «э-э», «эм», «м-м»: колебание, а не конец мысли (GigaAM их честно записывает, часто с многоточием)
HESITATION = re.compile(r"(э+|м+|хм+|а+м+|э+м+|аа+|ы+м*)(-[аэм]+)*")


def build_phrases(words_by_clip: list[list[dict]], gap: float = 1.0) -> tuple[list[dict], list[dict]]:
    """Возвращает (слова, фразы). Слова получают поля clip, n, phrase, cut."""
    words: list[dict] = []
    phrases: list[dict] = []

    def close(cur: list[int]):
        if not cur:
            return
        for part in _split_restarts(cur, words):
            pid = len(phrases)
            for wi in part:
                words[wi]["phrase"] = pid
            phrases.append({"id": pid, "clip": words[part[0]]["clip"], "words": part})

    for ci, clip_words in enumerate(words_by_clip):
        cur: list[int] = []
        prev = None
        for w in clip_words:
            n = norm(w["w"])
            if not n:
                # чистая пунктуация — приклеиваем к предыдущему слову
                if prev is not None:
                    words[prev]["w"] += w["w"]
                continue
            # после «э-э…» фраза продолжается, если говорящий заговорил снова в пределах 3 секунд
            hes = prev is not None and HESITATION.fullmatch(words[prev]["n"])
            if prev is not None and ((TERMINAL.search(words[prev]["w"]) and not hes)
                                     or w["s"] - words[prev]["e"] > (3.0 if hes else gap)):
                close(cur)
                cur = []
            idx = len(words)
            words.append({**w, "clip": ci, "n": n, "phrase": -1, "cut": None})
            cur.append(idx)
            prev = idx
        close(cur)

    for p in phrases:
        ws = [words[i] for i in p["words"]]
        p["start"] = ws[0]["s"]
        p["end"] = ws[-1]["e"]
        p["text"] = " ".join(w["w"] for w in ws)
        p["tokens"] = [w["n"] for w in ws]
    _mark_stutters(words, phrases)
    return words, phrases


def _split_restarts(idx: list[int], words: list[dict]) -> list[list[int]]:
    """«Сегодня мы... сегодня мы поговорим» → [«Сегодня мы...»], [«сегодня мы поговорим»]."""
    toks = [words[i]["n"] for i in idx]
    if len(toks) < 4:
        return [idx]
    cut = 0
    for j in range(1, len(toks) - 1):
        if toks[j] == toks[0] and toks[j + 1] == toks[1]:
            cut = j
    if not cut:
        return [idx]
    return [idx[:cut]] + _split_restarts(idx[cut:], words)


def _mark_stutters(words: list[dict], phrases: list[dict]) -> None:
    """Повторы внутри фразы («о том, о том, как») — первое вхождение вырезается."""
    for p in phrases:
        ids = p["words"]
        toks = [words[i]["n"] for i in ids]
        i = 0
        while i < len(toks):
            hit = 0
            for k in (4, 3, 2, 1):
                if i + 2 * k <= len(toks) and toks[i:i + k] == toks[i + k:i + 2 * k]:
                    if k == 1 and (toks[i] in LEGIT_DOUBLES or len(toks[i]) > 6):
                        continue
                    hit = k
                    break
            if hit:
                for wi in ids[i:i + hit]:
                    words[wi]["cut"] = "повтор"
                i += hit
            else:
                i += 1


def _ratio(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


LEAD = {"а", "и", "ну", "вот", "но", "да", "так", "and", "so", "well", "but"}


def _core(t: list[str]) -> list[str]:
    """Без вводных «а», «и», «ну» в начале и без «э-э» — дубль часто начинают по-разному."""
    t = [x for x in t if not HESITATION.fullmatch(x)]
    k = 0
    while k < len(t) - 2 and t[k] in LEAD:
        k += 1
    return t[k:]


def _similar(a: list[str], b: list[str]) -> bool:
    """b — повтор (дубль) фразы a?"""
    a, b = _core(a), _core(b)
    if not a or not b:
        return False
    if a == b:
        return True  # дословный повтор — даже из одного слова («Система.» → «Система.»)
    if len(a) >= 2 and len(b) >= 2 and a[:2] == b[:2] and not (a[0] in STOP and a[1] in STOP):
        return _ratio(a, b) >= 0.3 or len(a) <= 3
    if len(a) >= 2 and a[0] == b[0] and a[0] not in STOP and len(a[0]) >= 4:
        return _ratio(a, b[:len(a)]) >= 0.6
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    # у короткой фразы с одним значимым словом совпадение держится на служебных словах
    # («Как мы её делаем?» ≠ «Как вообще мы делаем ролики?») — для неё нужен почти дословный повтор
    strict = len(_stems(short)) < 2
    # короткая фраза целиком (подряд) входит в более длинную: «По порядку.» → «Давайте по порядку.»
    if 2 <= len(short) < len(long_) and any(long_[k:k + len(short)] == short for k in range(len(long_) - len(short) + 1)):
        return True
    if len(short) >= 3 and _ratio(short, long_[:len(short) + 1]) >= (0.9 if strict else 0.75):
        return True
    return len(a) >= 4 and len(b) >= 4 and _ratio(a, b) >= (0.9 if strict else 0.65)


def _cut_off(p: dict, words: list[dict]) -> list | None:
    last = words[p["words"][-1]]
    if CUTOFF_END.search(last["w"]):
        return ["cutoff"]
    if last["n"] in HANGING and not TERMINAL.search(last["w"]):
        return ["hanging", last['w'].strip('.,!?')]
    return None


PROFANITY = ("бля", "хуй", "хуё", "хуе", "пизд", "ёба", "еба", "ебл", "ебу", "ебат", "ебан", "сука", "суки",
             "мудак", "мудил", "залуп", "пидор", "пидар", "шлюх", "fuck", "shit", "bitch", "damn", "asshole")


def is_profane(token: str) -> bool:
    t = token.lower().replace("ё", "е")
    return any(t.startswith(x.replace("ё", "е")) or (len(x) >= 4 and x.replace("ё", "е") in t) for x in PROFANITY)


SEM_STOP = STOP | {
    "очень", "тогда", "этом", "этот", "эта", "эти", "это", "такой", "такие", "так", "как", "какой", "какие", "будет",
    "есть", "можно", "нужно", "тоже", "также", "просто", "сейчас", "потом", "здесь", "там", "тут", "еще", "уже",
    "все", "всё", "весь", "свой", "своему", "наш", "наши", "нашу", "ваш", "мой", "моем", "моём", "его", "её", "их",
    "который", "которые", "чтобы", "этого", "того", "тот", "той", "том", "там", "вот", "ну", "раз", "один", "одна",
    "буду", "будем", "будет", "будут", "будешь", "было", "был", "была", "были", "быть", "есть", "над", "под", "через",
    "время", "можно", "очень", "много", "мало", "какой-то", "какие-то", "что-то", "где-то", "когда-то",
    "the", "this", "that", "these", "those", "very", "just", "also", "then", "there", "here", "our", "your", "my",
    "will", "would", "was", "were", "been", "be", "is", "are", "have", "has", "had",
}


def _stems(tokens: list[str]) -> set[str]:
    """Значимые слова фразы, обрезанные до основы (5 букв) — грубая, но рабочая морфология для сравнения."""
    return {t[:5] for t in tokens if t not in SEM_STOP and len(t) >= 3}


def _coverage(p: dict, later: list[dict], weight=None) -> tuple[float, int]:
    """Какая доля смысловых слов фразы p встречается во фразах later (и сколько их всего совпало).
    weight — вес основы: редкие для этой записи слова весят больше частых."""
    a = _stems(p["tokens"])
    if not a:
        return 0.0, 0
    b = set().union(*(_stems(x["tokens"]) for x in later))
    w = weight or (lambda _s: 1.0)
    shared = a & b
    return sum(w(x) for x in shared) / sum(w(x) for x in a), len(shared)


def _prefix_of(p: dict, q: dict) -> bool:
    """p — начало фразы q (оборванная попытка), а не самостоятельная фраза."""
    a, b = p["tokens"], q["tokens"]
    return len(a) < len(b) and _ratio(a, b[:len(a) + 1]) >= 0.7


def classify(words: list[dict], phrases: list[dict], *, enabled: bool = True, prefer: str = "last",
             strictness: str = "medium",
             window: int = 12, max_distance: float = 150.0, llm: dict | None = None,
             continuation_gap: float = 2.2, pair_cov: float = 0.35) -> None:
    """Проставляет каждой фразе auto-статус: main / alt / bad и причину.

    Фраза убирается, если её ЗАМЕНЯЕТ более поздняя: дословный дубль, перефраз (смысловые слова
    покрыты одной или 2–3 следующими фразами подряд — так ловится и «переговорил по кусочкам»).
    Подсказки языковой модели (llm: {id: {"why", "by"}}) снижают порог для перефразов и помечают
    реплики не для зрителя; номер замены, который называет модель, не используется — его ищем сами.
    Оборванное в монтаж не попадает никогда.
    """
    llm = (llm or {}) if strictness != "soft" else {}
    # порог «перефраз без подсказки модели»: мягко — почти дословно, строго — смелее
    base_need = {"soft": 0.75, "medium": 0.62, "strict": 0.6}.get(strictness, 0.62)
    for p in phrases:
        p["group"] = p["id"]
        p["auto"] = "main"
        p["reason"] = None
        p["take"] = 1
        p["takes"] = 1
        p.pop("joins_next", None)
    if not enabled:
        return
    n = len(phrases)
    import math
    df: dict[str, int] = {}
    for p in phrases:
        for st in _stems(p["tokens"]):
            df[st] = df.get(st, 0) + 1

    def weight(st: str) -> float:
        return math.log(1 + n / df.get(st, 1))

    # 1. брак сам по себе: оборвана, мусор/мат, короткая реплика, которую модель считает лишней
    bad: dict[int, list] = {}
    for p in phrases:
        why = _cut_off(p, words)
        if not why and all(t in JUNK or is_profane(t) for t in p["tokens"]):
            why = ["junk"]
        text = " ".join(p["tokens"])
        if not why and len(p["tokens"]) <= 10 and ASIDE.search(text):
            why = ["offscript"]
        # короткая реплика с матом («Угу, похуй.», «Ага, похуй.») — уходит целиком, не только мат
        if not why and len(p["tokens"]) <= 4 and any(is_profane(t) for t in p["tokens"]):
            why = ["offscript"]
        hint = llm.get(p["id"])
        if not why and hint and not _stems(p["tokens"]):
            why = ["offscript"]  # модель считает лишней, а смысловых слов нет вообще («вот как-то так нужно»)
        if not why and hint and hint["why"] == "offscript" and (
                any(is_profane(t) for t in p["tokens"]) or len(_stems(p["tokens"])) <= 1):
            why = ["offscript"]
        if not why and hint and hint["why"] == "unfinished":
            last = words[p["words"][-1]]["w"]
            if not TERMINAL.search(last):
                why = ["unfinished"]
        if why:
            bad[p["id"]] = why

    # 2. замены: кто какую фразу перекрывает позже
    replaced_by: dict[int, int] = {}
    idx0 = {p["id"]: k for k, p in enumerate(phrases)}
    for i, p in enumerate(phrases):
        if p["id"] in bad and bad[p["id"]][0] in ("junk", "offscript"):
            continue
        hint = llm.get(p["id"])
        need, need_n = (0.5, 2) if hint and hint["why"] == "repeat" else (base_need, 3)
        n_stems = len(_stems(p["tokens"]))
        best = None
        for j in range(i + 1, min(n, i + 1 + window)):
            q = phrases[j]
            if q["start"] - p["end"] > max_distance and q["clip"] == p["clip"]:
                break
            if q["id"] in bad:
                continue
            if _similar(p["tokens"], q["tokens"]):
                best = q["id"]
                break
            cov1, shared1 = _coverage(p, [q], weight)
            if cov1 >= need and shared1 >= max(2, min(need_n, n_stems)):
                best = q["id"]
                break
            # переговорил по кусочкам: несколько фраз подряд, первая из них уже похожа
            span = [x for x in phrases[j:j + 3] if x["id"] not in bad]
            if len(span) > 1 and cov1 >= 0.25:
                cov, shared = _coverage(p, span, weight)
                if cov >= need + 0.05 and shared >= max(2, min(need_n + 1, n_stems)):
                    best = q["id"]
                    break
        # модель прямо назвала более позднюю фразу, которая переговаривает эту: верим, если у них есть
        # общие смысловые слова (одна модель ошибается часто, вместе со словами — редко)
        if best is None and hint and hint.get("why") == "repeat" and isinstance(hint.get("by"), int):
            q = phrases[idx0[hint["by"]]] if hint["by"] in idx0 else None
            if q is not None and q["id"] > p["id"] and q["id"] not in bad:
                cov, sh = _coverage(p, [q], weight)
                if cov >= pair_cov and sh >= 1:
                    best = q["id"]
        if best is not None:
            replaced_by[p["id"]] = best

    # 2. пауза посреди предложения: «…для переноса я использую» → «AUX-плагин.» — фраза не брошена,
    #    следующая её продолжает. Выучено на ручном монтаже: такие «оборванные» фразы почти всегда
    #    возвращали в монтаж. Не трогаем, если следующая фраза начинает ту же мысль заново.
    for k, p in enumerate(phrases[:-1]):
        why = bad.get(p["id"])
        if not why or why[0] not in ("hanging", "unfinished") or p["id"] in replaced_by or len(p["tokens"]) < 2:
            continue
        q = phrases[k + 1]
        if q["clip"] != p["clip"] or q["start"] - p["end"] > continuation_gap:
            continue
        qb = bad.get(q["id"])
        if qb and qb[0] in ("junk", "offscript", "cutoff"):
            continue
        a, b = _core(p["tokens"]), _core(q["tokens"])
        if not b or (a[:1] == b[:1] and not q["text"][:1].islower()) or _similar(p["tokens"], q["tokens"])                 or _prefix_of(p, q):
            continue
        del bad[p["id"]]
        p["joins_next"] = True

    idx = {p["id"]: k for k, p in enumerate(phrases)}
    # средне и строго: цепочку, переговорённую ещё раз, видим всегда (это безопасно)
    if strictness != "soft":
        # 2а. цепочка переговорена ещё раз: если ЛЮБОЙ вариант из цепочки дублей повторяется позже её
        #     последнего варианта, значит весь кусок сказан заново — последний вариант цепочки тоже не финальный.
        for _round in range(4):
            members: dict[int, list[int]] = {}
            for a_id in replaced_by:
                end = a_id
                seen = set()
                while end in replaced_by and end not in seen:
                    seen.add(end)
                    end = replaced_by[end]
                members.setdefault(end, []).append(a_id)
            moved = False
            for last_id, earlier in members.items():
                if last_id in replaced_by or last_id in bad:
                    continue
                li = idx[last_id]
                found = None
                for k in range(li + 1, min(n, li + 1 + window)):
                    q = phrases[k]
                    if q["id"] in bad or q["start"] - phrases[li]["end"] > max_distance:
                        continue
                    # позднее место должно повторять и сам последний вариант (а не только длинный ранний)
                    span = [x for x in phrases[k:k + 3] if x["id"] not in bad]
                    cl, shl = _coverage(phrases[li], span, weight)
                    if not (_similar(phrases[li]["tokens"], q["tokens"]) or (cl >= 0.4 and shl >= 2)):
                        continue
                    for e_id in earlier + [last_id]:
                        pe = phrases[idx[e_id]]
                        cov, sh = _coverage(pe, [q], weight)
                        if _similar(pe["tokens"], q["tokens"]) or (cov >= 0.62 and sh >= 2):
                            found = q["id"]
                            break
                    if found is not None:
                        break
                if found is not None:
                    replaced_by[last_id] = found
                    moved = True
            if not moved:
                break

    # только «строго»: смелые правила по смыслу для целых абзацев
    if strictness == "strict":
        # 2б. брошенная попытка абзаца: если фраза i перезаписана фразой j через несколько фраз,
        #     всё между ними — неудачный дубль целого куска. Для этих фраз ищем повтор смысла дальше,
        #     на длину всей новой попытки, с более мягким порогом.
        idx = {p["id"]: k for k, p in enumerate(phrases)}
        for a_id, b_id in sorted(replaced_by.items()):
            i, j = idx[a_id], idx[b_id]
            if j - i < 2:
                continue
            horizon = min(n, j + 3 * (j - i) + 8)
            for m in range(i + 1, j):
                pm = phrases[m]
                if pm["id"] in bad or pm["id"] in replaced_by or len(_stems(pm["tokens"])) < 2:
                    continue
                for k in range(j, horizon):
                    q = phrases[k]
                    if q["id"] in bad or q["start"] - pm["end"] > max_distance * 2:
                        continue
                    span = [x for x in phrases[k:k + 3] if x["id"] not in bad]
                    cov1, sh1 = _coverage(pm, [q], weight)
                    cov, sh = _coverage(pm, span, weight)
                    if (cov1 >= 0.4 and sh1 >= 2) or (cov1 >= 0.2 and cov >= 0.5 and sh >= 2):
                        replaced_by[pm["id"]] = q["id"]
                        break

        # 2в. соседи брошенной попытки: если фразу перед p заменила далёкая фраза q, то и p, скорее всего,
        #     переговорена рядом с q — проверяем мягче в окрестности q.
        changed = True
        while changed:
            changed = False
            for m in range(1, n):
                pm, prev = phrases[m], phrases[m - 1]
                if pm["id"] in bad or pm["id"] in replaced_by or prev["id"] not in replaced_by:
                    continue
                qk = idx[replaced_by[prev["id"]]]
                if qk - m < 2 or len(_stems(pm["tokens"])) < 2:
                    continue
                for k in range(max(m + 1, qk - 2), min(n, qk + 5)):
                    q = phrases[k]
                    if q["id"] in bad:
                        continue
                    cov, sh = _coverage(pm, [q], weight)
                    if cov >= 0.45 and sh >= 2:
                        replaced_by[pm["id"]] = q["id"]
                        changed = True
                        break

    # 3. группы для подписи «дубль N из M»
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in replaced_by.items():
        parent[find(a)] = find(b)
    groups: dict[int, list[dict]] = {}
    for p in phrases:
        groups.setdefault(find(p["id"]), []).append(p)
    for gid, members in groups.items():
        members.sort(key=lambda p: p["id"])
        for k, p in enumerate(members):
            p["group"], p["take"], p["takes"] = gid, k + 1, len(members)

    # 4. статусы
    by_id = {p["id"]: p for p in phrases}
    if prefer == "first":
        # первый удачный вариант остаётся, более поздние повторы — в запасные
        for a in sorted(replaced_by):
            b = replaced_by[a]
            if a not in bad and by_id[b]["auto"] != "alt" and b not in bad:
                by_id[b]["auto"] = "alt"
                by_id[b]["reason"] = ["alt", by_id[b]["take"], by_id[b]["takes"]]
    for p in phrases:
        pid = p["id"]
        if pid in bad:
            p["auto"], p["reason"] = "bad", bad[pid]
        elif prefer != "first" and pid in replaced_by:
            q = by_id[replaced_by[pid]]
            # законченное предложение — запасной дубль; без точки в конце и начало более поздней — брошено
            unfinished = not TERMINAL.search(words[p["words"][-1]]["w"]) and (
                _prefix_of(p, q) or len(p["tokens"]) < 0.6 * len(q["tokens"]))
            if unfinished:
                p["auto"], p["reason"] = "bad", ["unfinished"]
            else:
                p["auto"], p["reason"] = "alt", ["alt", p["take"], p["takes"]]
        elif p["auto"] == "main" and p["takes"] > 1:
            p["reason"] = ["take", p["take"], p["takes"]]
