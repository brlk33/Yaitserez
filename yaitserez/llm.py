"""Смысловой разбор дублей локальной языковой моделью (Qwen3-4B из VoiceType через llama.cpp).

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
from .paths import cache_dir

PORT = 47661          # свой порт — не мешаем серверу самого VoiceType (47654)
WINDOW = 40           # фраз в окне
ZONE = 24             # по скольким из них модель принимает решение (остальное — контекст впереди)
PARALLEL = 3
PROMPT_VERSION = 3
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _roots():
    for base in (r"D:\Program Files", r"C:\Program Files", r"E:\Program Files",
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        yield os.path.join(base, "VoiceType")


def find() -> tuple[str, str, list[str]] | None:
    """(llama-server.exe, модель .gguf, папки с CUDA-библиотеками) или None."""
    for root in _roots():
        exe = next(iter(glob.glob(os.path.join(root, "tools", "llama", "**", "llama-server.exe"), recursive=True)), None)
        models = sorted(glob.glob(os.path.join(root, "models", "editor", "*.gguf")))
        if exe and models:
            libs = [os.path.dirname(exe), os.path.join(root, ".venv", "Lib", "site-packages", "torch", "lib")]
            libs += glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                           ".venv", "Lib", "site-packages", "nvidia", "*", "bin"))
            return exe, models[0], [d for d in libs if os.path.isdir(d)]
    return None


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
                status(L("Запускаю смысловой разбор (модель Qwen из VoiceType)",
                         "Starting meaning analysis (Qwen model from VoiceType)"))
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
        "response_format": {"type": "json_schema", "json_schema": {"name": "takes", "schema": SCHEMA}},
    }).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        out = json.loads(r.read().decode("utf-8"))
    return json.loads(out["choices"][0]["message"]["content"]).get("drop", [])


def analyze(phrases: list[dict], lang: str = "ru", progress=None, cancelled=lambda: False) -> dict[int, dict]:
    """{id фразы: {"why": ..., "by": ...}} для фраз, которые модель предлагает убрать."""
    if not phrases:
        return {}
    key = hashlib.sha1(json.dumps([PROMPT_VERSION, lang, [p["text"] for p in phrases]],
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
                progress(done[0] / len(starts), L(f"Смысловой разбор: {done[0]} из {len(starts)}",
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
    if not cancelled():
        with open(cpath, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
    return result
