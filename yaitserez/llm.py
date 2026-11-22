"""Смысловой разбор дублей локальной языковой моделью (Qwen3.5 9B или 4B через llama.cpp).

Правила по словам не видят перефразов («Для него это главный способ…» → «Для школы это один из
главных способов…»). Модель читает расшифровку окнами и отмечает фразы, которые не должны попасть
в монтаж: мысль сказана заново позже, фраза брошена на середине, реплика не для зрителя.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .i18n import L
from .paths import app_dir, cache_dir

PORT = 47661          # свой порт — не мешаем серверу самого VoiceType (47654)
WINDOW = 40           # фраз в окне
ZONE = 24             # по скольким из них модель принимает решение (остальное — контекст впереди)
PARALLEL = 3
PROMPT_VERSION = 4
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# Модели для разбора дублей: пользователь выбирает размер (точнее / меньше места)
MODELS = {
    "9b": {"file": "Qwen3.5-9B-Q4_K_M.gguf", "size": 5_680_000_000,
           "url": "https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/main/Qwen3.5-9B-Q4_K_M.gguf"},
    "4b": {"file": "Qwen3.5-4B-Q4_K_M.gguf", "size": 2_740_000_000,
           "url": "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf"},
}
LLAMA_BUILD = "b12502"
LLAMA_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_BUILD}/llama-{LLAMA_BUILD}-bin-win-cuda-12.4-x64.zip"
CHOICE = {"model": "9b"}   # из настроек (llm_model)


def models_dir() -> str:
    return os.path.join(app_dir(), "models")


def own_llama_dir() -> str:
    return os.path.join(app_dir(), "llama")


def model_path(choice: str) -> str:
    return os.path.join(models_dir(), MODELS[choice]["file"])


def has_model(choice: str) -> bool:
    return os.path.isfile(model_path(choice))


def _roots():
    for base in (r"D:\Program Files", r"C:\Program Files", r"E:\Program Files",
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        yield os.path.join(base, "VoiceType")


def _server() -> tuple[str, list[str]] | None:
    """llama-server.exe: свой (скачан установщиком) или из VoiceType."""
    own = next(iter(glob.glob(os.path.join(own_llama_dir(), "**", "llama-server.exe"), recursive=True)), None)
    venv_libs = glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                       ".venv", "Lib", "site-packages", "nvidia", "*", "bin"))
    if own:
        return own, [os.path.dirname(own)] + venv_libs
    for root in _roots():
        exe = next(iter(glob.glob(os.path.join(root, "tools", "llama", "**", "llama-server.exe"), recursive=True)), None)
        if exe:
            return exe, [os.path.dirname(exe), os.path.join(root, ".venv", "Lib", "site-packages", "torch", "lib")] + venv_libs
    return None


def _model() -> str | None:
    """Выбранная модель; если её нет — другая скачанная; в крайнем случае — Qwen из VoiceType."""
    pick = CHOICE.get("model", "9b")
    for c in [pick] + [k for k in MODELS if k != pick]:
        if c in MODELS and has_model(c):
            return model_path(c)
    for root in _roots():
        models = sorted(glob.glob(os.path.join(root, "models", "editor", "*.gguf")))
        if models:
            return models[0]
    return None


def find() -> tuple[str, str, list[str]] | None:
    """(llama-server.exe, модель .gguf, папки с CUDA-библиотеками) или None."""
    srv, m = _server(), _model()
    if not srv or not m:
        return None
    exe, libs = srv
    return exe, m, [d for d in libs if os.path.isdir(d)]


def status() -> dict:
    srv, m = _server(), _model()
    return {"choice": CHOICE.get("model", "9b"), "server": bool(srv), "using": os.path.basename(m) if m else None,
            **{f"has_{k}": has_model(k) for k in MODELS},
            **{f"size_{k}": v["size"] for k, v in MODELS.items()}}


def _fetch(url: str, dst: str, progress=None, cancelled=lambda: False, total_hint: int = 0) -> None:
    """Скачать с докачкой (.part), прогресс 0…1."""
    part = dst + ".part"
    have = os.path.getsize(part) if os.path.isfile(part) else 0
    req = urllib.request.Request(url, headers={"User-Agent": "Yaitserez", **({"Range": f"bytes={have}-"} if have else {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        if have and r.status != 206:
            have = 0
        total = have + int(r.headers.get("Content-Length") or 0) or total_hint
        with open(part, "ab" if have else "wb") as f:
            got, last = have, 0.0
            while True:
                if cancelled():
                    raise RuntimeError(L("Скачивание остановлено", "Download stopped"))
                buf = r.read(1 << 20)
                if not buf:
                    break
                f.write(buf)
                got += len(buf)
                now = time.time()
                if progress and now - last > 0.3:
                    last = now
                    progress(got / total if total else 0.0, got, total)
    os.replace(part, dst)


def download(choice: str, progress=None, cancelled=lambda: False) -> str:
    """Скачать выбранную модель (и llama-server, если его нет ни у нас, ни в VoiceType)."""
    os.makedirs(models_dir(), exist_ok=True)
    if _server() is None:
        import zipfile
        z = os.path.join(models_dir(), f"llama-{LLAMA_BUILD}.zip")
        _fetch(LLAMA_URL, z, (lambda fr, g, t: progress(fr * 0.06, g, t)) if progress else None, cancelled)
        os.makedirs(own_llama_dir(), exist_ok=True)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(own_llama_dir())
        os.remove(z)
    m = MODELS[choice]
    if not has_model(choice):
        _fetch(m["url"], model_path(choice), (lambda fr, g, t: progress(0.06 + fr * 0.94, g, t)) if progress else None,
               cancelled, m["size"])
    return model_path(choice)


def available() -> bool:
    return find() is not None


class Server:
    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()

    def _health(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1) as r:
                return r.status == 200
        except Exception:  # noqa: BLE001
            return False

    def ensure(self, status=None):
        with self.lock:
            if self.proc and self.proc.poll() is None and self._health():
                return
            found = find()
            if not found:
                raise RuntimeError(L("Языковая модель VoiceType не найдена", "VoiceType language model not found"))
            exe, model, libs = found
            self.stop_locked()
            if status:
                status(L(f"Запускаю смысловой разбор ({os.path.basename(model).split('-Q')[0]})",
                         f"Starting meaning analysis ({os.path.basename(model).split('-Q')[0]})"))
            env = dict(os.environ)
            env["PATH"] = os.pathsep.join(libs + [env.get("PATH", "")])
            log = open(os.path.join(cache_dir(), "llm.log"), "w", encoding="utf-8", errors="replace")
            self.proc = subprocess.Popen(
                [exe, "-m", model, "--host", "127.0.0.1", "--port", str(PORT), "-ngl", "99",
                 "-c", str(2816 * PARALLEL), "-np", str(PARALLEL), "--no-webui", "-fa", "on"],
                cwd=os.path.dirname(exe), env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=_NO_WINDOW)
            t0 = time.time()
            while time.time() - t0 < 120:
                if self.proc.poll() is not None:
                    raise RuntimeError(L("Языковая модель не запустилась (см. llm.log в папке кеша)",
                                         "Language model failed to start (see llm.log in the cache folder)"))
                if self._health():
                    return
                time.sleep(0.3)
            raise RuntimeError(L("Языковая модель не ответила за 2 минуты", "Language model did not respond in 2 minutes"))

    def stop_locked(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def stop(self):
        with self.lock:
            self.stop_locked()


SERVER = Server()

SYSTEM_RU = (
    "Ты — опытный видеомонтажёр. Перед тобой расшифровка черновой записи монолога. Спикер часто сбивается: "
    "начинает фразу заново, повторяет ту же мысль другими словами, иногда переговаривает длинную фразу "
    "по частям, иногда комментирует саму запись («блин», «стоп», «вот как-то так нужно», мат). "
    "Из записи собирают чистый монтаж, где каждая мысль звучит один раз — в последнем удачном варианте."
)
TASK_RU = (
    "Отметь фразы с номерами от {a} до {b}, которые НЕ должны попасть в монтаж. Остальные фразы — только контекст.\n"
    "Причины:\n"
    "- repeat — та же мысль позже сказана заново (дословно или другими словами, целиком или по частям в "
    "нескольких следующих фразах). В by укажи номер более поздней фразы, которая её заменяет.\n"
    "- unfinished — фраза оборвана или брошена, и мысль не доведена.\n"
    "- offscript — реплика не для зрителя: ругательство, комментарий к записи, обращение к оператору.\n"
    "Не отмечай фразу, если она добавляет новую мысль, которой нет в следующих фразах, или просто продолжает "
    "предыдущую. Если мысль больше не повторяется — оставь фразу. Сомневаешься — оставь.\n"
    "Ответ — только JSON."
)
SYSTEM_EN = (
    "You are an experienced video editor. Below is a transcript of a raw monologue recording. The speaker often "
    "stumbles: restarts a sentence, repeats the same idea in different words, re-records a long sentence in parts, "
    "and sometimes comments on the recording itself (swearing, 'stop', 'let me try again'). "
    "The goal is a clean edit where every idea is said once — in its last good version."
)
TASK_EN = (
    "Mark the phrases numbered {a} to {b} that must NOT go into the edit. Other phrases are context only.\n"
    "Reasons:\n"
    "- repeat — the same idea is said again LATER (verbatim or reworded, whole or split across later phrases). "
    "Put the number of the later phrase that replaces it in `by`.\n"
    "- unfinished — the phrase is cut off or abandoned.\n"
    "- offscript — not meant for the audience: swearing, comments about the recording, talking to the crew.\n"
    "Do not mark a phrase that adds an idea not present in later phrases or simply continues the previous one. "
    "If the idea is not repeated later — keep it. When in doubt — keep it.\n"
    "Answer with JSON only."
)
SCHEMA = {
    "type": "object",
    "properties": {"drop": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "why": {"type": "string", "enum": ["repeat", "unfinished", "offscript"]},
                       "by": {"type": ["integer", "null"]}},
        "required": ["id", "why", "by"]}}},
    "required": ["drop"],
}


def _ask(lines: list[str], a: int, b: int, lang: str) -> list[dict]:
    en = lang == "en"
    user = "\n".join(lines) + "\n\n" + (TASK_EN if en else TASK_RU).format(a=a, b=b)
    body = json.dumps({
        "messages": [{"role": "system", "content": SYSTEM_EN if en else SYSTEM_RU}, {"role": "user", "content": user}],
        "temperature": 0, "max_tokens": 900, "cache_prompt": True,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_schema", "json_schema": {"name": "takes", "schema": SCHEMA}},
    }).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        out = json.loads(r.read().decode("utf-8"))
    return json.loads(out["choices"][0]["message"]["content"]).get("drop", [])


PAIR_SYS_RU = ("Ты — опытный видеомонтажёр. Перед тобой кусок расшифровки черновой записи урока. Спикер часто "
               "переговаривает: говорит мысль, а потом сразу говорит её же заново, другими словами или точнее, "
               "иногда по частям. В монтаж идёт только последний вариант.")
PAIR_TASK_RU = ("Фраза A: «{a}»\n\nДальше спикер говорит:\n{nexts}\n\n"
                "Говорит ли спикер в одной из этих фраз ту же мысль, что во фразе A, заново (переговаривает A)? "
                "Если да — укажи номер этой фразы. Если фраза A добавляет свою мысль, а следующие фразы её продолжают "
                "или говорят о другом — ответь 0.")
PAIR_SYS_EN = ("You are an experienced video editor. Below is part of a raw lesson transcript. The speaker often "
               "re-records: says an idea and then says the same idea again, reworded or more precisely, sometimes "
               "in parts. Only the last version goes into the edit.")
PAIR_TASK_EN = ("Phrase A: \"{a}\"\n\nThen the speaker says:\n{nexts}\n\n"
                "Does the speaker say the same idea as phrase A again in one of these phrases (re-recording A)? "
                "If yes, give that phrase's number. If phrase A adds its own idea and the next phrases continue it "
                "or talk about something else, answer 0.")
PAIR_SCHEMA = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
PAIR_NEXT = 5          # сколько следующих фраз показываем
PAIR_HORIZON = 90.0    # и не дальше стольких секунд


def _pair_prompt(a: str, nexts: list[str], lang: str) -> str:
    lst = "\n".join(f"{k + 1}. {t}" for k, t in enumerate(nexts))
    return (PAIR_TASK_EN if lang == "en" else PAIR_TASK_RU).format(a=a, nexts=lst)


def _ask_pair(phrases: list[dict], i: int, lang: str, examples: list[dict] | None = None) -> int | None:
    """Номер (id) более поздней фразы, которая переговаривает фразу i, или None.
    Точечный вопрос про одну фразу модель решает заметно точнее, чем «отметь лишнее в окне»
    (проверено на ручном монтаже: 9B в окне помечает почти всё подряд)."""
    p = phrases[i]
    nx = [q for q in phrases[i + 1:i + 1 + PAIR_NEXT] if q["clip"] == p["clip"] and q["start"] - p["end"] < PAIR_HORIZON]
    if not nx:
        return None
    en = lang == "en"
    prev = " ".join(q["text"] for q in phrases[max(0, i - 2):i] if q["clip"] == p["clip"])
    head = ""
    if prev:
        head = f"Before that: \"{prev}\"\n\n" if en else f"Перед этим: «{prev}»\n\n"
    user = head + _pair_prompt(p["text"], [q["text"] for q in nx], lang)
    # примеры решений самого монтажёра (из «Учиться на моих правках») — как прошлые ответы в диалоге.
    # Проверено на отложенной половине записи: модель реже называет повтором то, что монтажёр оставляет
    shots = []
    for ex in examples or []:
        shots += [{"role": "user", "content": _pair_prompt(ex["a"], ex["nexts"], lang)},
                  {"role": "assistant", "content": json.dumps({"n": int(ex["n"])})}]
    body = json.dumps({
        "messages": [{"role": "system", "content": PAIR_SYS_EN if en else PAIR_SYS_RU}] + shots +
                    [{"role": "user", "content": user}],
        "temperature": 0, "max_tokens": 20, "cache_prompt": True,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_schema", "json_schema": {"name": "pair", "schema": PAIR_SCHEMA}},
    }).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read().decode("utf-8"))
    n = int(json.loads(out["choices"][0]["message"]["content"]).get("n", 0) or 0)
    return nx[n - 1]["id"] if 1 <= n <= len(nx) else None


def analyze(phrases: list[dict], lang: str = "ru", progress=None, cancelled=lambda: False,
            examples: list[dict] | None = None) -> dict[int, dict]:
    """{id фразы: {"why": ..., "by": ...}} для фраз, которые модель предлагает убрать."""
    if not phrases:
        return {}
    found = find()
    mname = os.path.basename(found[1]) if found else ""
    key = hashlib.sha1(json.dumps([PROMPT_VERSION, lang, mname, [p["text"] for p in phrases], examples or []],
                                  ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    cpath = os.path.join(cache_dir(), f"llm_{key}.json")
    if os.path.isfile(cpath):
        with open(cpath, encoding="utf-8") as f:
            return {int(k): v for k, v in json.load(f).items()}
    SERVER.ensure(lambda m: progress and progress(0.0, m))
    n = len(phrases)
    starts = list(range(0, n, ZONE))
    done = [0]
    lock = threading.Lock()

    def one(st):
        if cancelled():
            return []
        a, b = st, min(st + ZONE, n) - 1
        win = phrases[st:st + WINDOW]
        lines = [f"{p['id']}: {p['text']}" for p in win]
        try:
            res = _ask(lines, phrases[a]["id"], phrases[b]["id"], lang)
        except Exception:  # noqa: BLE001  — один сбойный кусок не должен ронять весь разбор
            res = []
        with lock:
            done[0] += 1
            if progress:
                progress(0.5 * done[0] / len(starts), L(f"Смысловой разбор: {done[0]} из {len(starts)}",
                                                  f"Meaning analysis: {done[0]} of {len(starts)}"))
        ids = {p["id"] for p in win}
        zone = {p["id"] for p in phrases[a:b + 1]}
        out = []
        for d in res:
            pid, why, by = d.get("id"), d.get("why"), d.get("by")
            if pid not in zone or why not in ("repeat", "unfinished", "offscript"):
                continue
            if why == "repeat" and not (isinstance(by, int) and by in ids and by > pid):
                continue  # повтор без более поздней замены — не верим
            out.append((pid, {"why": why, "by": by if why == "repeat" else None}))
        return out

    result: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
        for part in ex.map(one, starts):
            result.update(part)

    # второй проход: про каждую фразу отдельно — переговорена ли она дальше. Дополняет первый:
    # где первый проход не назвал фразу повтором, берём ответ второго (с номером замены)
    done2 = [0]

    def pair(i):
        if cancelled():
            return i, None
        try:
            r = _ask_pair(phrases, i, lang, examples)
        except Exception:  # noqa: BLE001
            r = None
        with lock:
            done2[0] += 1
            if progress and done2[0] % 10 == 0:
                progress(0.5 + 0.5 * done2[0] / n, L(f"Ищу переговорённые фразы: {done2[0]} из {n}",
                                         f"Looking for re-recorded phrases: {done2[0]} of {n}"))
        return i, r

    with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
        for i, by in ex.map(pair, range(n)):
            pid = phrases[i]["id"]
            if by is not None and by > pid and (pid not in result or result[pid]["why"] != "repeat"):
                result[pid] = {"why": "repeat", "by": by}
    if not cancelled():
        with open(cpath, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
    return result
