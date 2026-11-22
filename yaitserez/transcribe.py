"""Распознавание речи (faster-whisper) с таймкодами слов."""
from __future__ import annotations

import glob
import os
import sys
import threading

import numpy as np

from .i18n import L
from .paths import models_dir

_lock = threading.Lock()
_model = None
_model_key = None


def _add_cuda_dlls():
    if sys.platform != "win32":
        return
    import site

    roots = list(site.getsitepackages()) + [site.getusersitepackages()]
    for r in roots:
        for d in glob.glob(os.path.join(r, "nvidia", "*", "bin")):
            try:
                os.add_dll_directory(d)
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            except OSError:
                pass


_add_cuda_dlls()

# Подсказка, чтобы Whisper не «причёсывал» оговорки и записывал речь дословно.
PROMPT = "Ну, э-э, я хотел... я хотел сказать, что, так, сейчас. Сегодня мы... Сегодня мы поговорим о том, как это работает."
PROMPT_EN = "Um, so, I wanted... I wanted to say that, uh, okay. Today we... Today we're going to talk about how it works."


def find_local_model(name: str) -> str | None:
    """Ищет уже установленную модель (в первую очередь — у VoiceType), чтобы не качать вторую копию."""
    env = os.environ.get("YAITSEREZ_WHISPER")
    roots = [env] if env else []
    for base in (r"D:\Program Files", r"C:\Program Files", r"E:\Program Files",
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        roots += [os.path.join(base, "VoiceType", "models", f"whisper-{name}"),
                  os.path.join(base, "VoiceType", "models", name)]
    for r in roots:
        if r and os.path.isfile(os.path.join(r, "model.bin")):
            return r
    return None


def model_source(name: str) -> str:
    local = find_local_model(name)
    return f"VoiceType ({local})" if local else "собственная копия"


def get_model(name: str, status=None):
    global _model, _model_key
    with _lock:
        if _model is not None and _model_key == name:
            return _model
        from faster_whisper import WhisperModel
        import ctranslate2

        local = find_local_model(name)
        if status:
            status(L("Загружаю модель распознавания", "Loading the speech model") + (
                L(" из VoiceType", " from VoiceType") if local else
                L(" (в первый раз она скачивается, ~1,5 ГБ)", " (downloaded once, ~1.5 GB)")))
        root = models_dir()
        src = local or name
        errors = []
        options = []
        if ctranslate2.get_cuda_device_count() > 0:
            options += [("cuda", "float16"), ("cuda", "int8_float16")]
        options += [("cpu", "int8")]
        for device, ctype in options:
            try:
                m = WhisperModel(src, device=device, compute_type=ctype, download_root=root)
                # пробный прогон: проверяет, что CUDA-библиотеки действительно грузятся
                list(m.transcribe(np.zeros(16000, dtype=np.float32), language="ru")[0])
                _model, _model_key = m, name
                return m
            except Exception as e:  # noqa: BLE001
                errors.append(f"{device}/{ctype}: {e}")
        raise RuntimeError(L("Не удалось загрузить модель распознавания:\n", "Could not load the speech model:\n")
                           + "\n".join(errors))


def release() -> None:
    """Выгрузить модель из видеопамяти (перед смысловым разбором). Следующий запуск загрузит её за ~2 с."""
    global _model, _model_key
    with _lock:
        _model, _model_key = None, None
    import gc

    gc.collect()


def preload(name: str, on_done=None) -> None:
    """Загрузить модель заранее в фоне (пока пользователь добавляет файлы)."""
    def work():
        try:
            get_model(name)
            err = None
        except Exception as e:  # noqa: BLE001
            err = str(e)
        if on_done:
            on_done(err)

    threading.Thread(target=work, daemon=True).start()


def transcribe(audio16k: np.ndarray, model_name: str, language: str | None, status=None, on_progress=None) -> list[dict]:
    """Возвращает список слов: {s, e, w, p} (начало, конец, текст, вероятность)."""
    model = get_model(model_name, status)
    total = len(audio16k) / 16000
    lang = None if language in (None, "", "auto") else language
    common = dict(
        language=lang,
        word_timestamps=True,
        initial_prompt=PROMPT_EN if lang == "en" else (PROMPT if lang == "ru" else None),
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 200},
        beam_size=5,
        temperature=0.0,
    )
    if total > 30:
        # пакетный режим: куски речи распознаются параллельно на видеокарте (в 3–4 раза быстрее)
        from faster_whisper import BatchedInferencePipeline

        segments, _info = BatchedInferencePipeline(model=model).transcribe(audio16k, batch_size=16, **common)
    else:
        segments, _info = model.transcribe(audio16k, condition_on_previous_text=False, **common)
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if not text:
                continue
            words.append({"s": float(w.start), "e": float(w.end), "w": text, "p": float(w.probability)})
        if on_progress and total > 0:
            on_progress(min(1.0, seg.end / total))
    return words


# ---------------- GigaAM-v3: русский точнее Whisper ----------------
def _voicetype_roots():
    for base in (r"D:\Program Files", r"C:\Program Files", r"E:\Program Files",
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        yield os.path.join(base, "VoiceType")


def gigaam_find() -> tuple[str, str] | None:
    """(python VoiceType с пакетом gigaam, папка с моделью v3_e2e_rnnt) или None."""
    for root in _voicetype_roots():
        py = os.path.join(root, ".venv", "Scripts", "python.exe")
        mdir = os.path.join(root, "models")
        if os.path.isfile(py) and os.path.isfile(os.path.join(mdir, "v3_e2e_rnnt.ckpt")) \
                and os.path.isdir(os.path.join(root, ".venv", "Lib", "site-packages", "gigaam")):
            return py, mdir
    return None


_GIGA = {"proc": None}


def _giga_proc(py: str, mdir: str):
    """Один процесс на всю обработку: модель грузится один раз (~20 с), дальше клипы идут подряд."""
    import subprocess
    import sys as _sys

    p = _GIGA["proc"]
    if p is not None and p.poll() is None:
        return p
    worker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gigaam_worker.py")
    flags = 0x08000000 if _sys.platform == "win32" else 0
    from .paths import cache_dir
    log_path = os.path.join(cache_dir(), "gigaam.log")
    log = open(log_path, "w", encoding="utf-8", errors="replace")   # не в трубу: полная труба остановила бы процесс
    p = subprocess.Popen([py, "-u", worker, mdir], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                         text=True, encoding="utf-8", errors="replace", creationflags=flags)
    p.log_path = log_path
    while True:
        line = p.stdout.readline()
        if not line:
            raise RuntimeError("GigaAM: " + _tail(log_path))
        if line.startswith("READY"):
            break
    _GIGA["proc"] = p
    return p


def _tail(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()[-400:]
    except OSError:
        return ""


def gigaam_stop() -> None:
    p = _GIGA["proc"]
    _GIGA["proc"] = None
    if p is not None and p.poll() is None:
        try:
            p.stdin.write("QUIT" + chr(10))
            p.stdin.flush()
            p.wait(timeout=10)
        except Exception:  # noqa: BLE001
            p.kill()


def gigaam_available() -> bool:
    return gigaam_find() is not None


def transcribe_gigaam(audio16k: np.ndarray, workdir: str, status=None, on_progress=None) -> list[dict]:
    """Режем запись на куски речи (Silero VAD, до 20 с — столько GigaAM берёт за раз) и распознаём
    GigaAM-v3 с пунктуацией и временем каждого слова. Работает в отдельном процессе питона VoiceType."""
    import json
    import subprocess
    import sys as _sys

    from faster_whisper.vad import VadOptions, get_speech_timestamps

    found = gigaam_find()
    if not found:
        raise RuntimeError("GigaAM не найден")
    py, mdir = found
    sr = 16000
    ts = get_speech_timestamps(audio16k, VadOptions(max_speech_duration_s=20, min_silence_duration_ms=250,
                                                     speech_pad_ms=250))
    segs = [[round(t["start"] / sr, 3), round(t["end"] / sr, 3)] for t in ts]
    if not segs:
        return []
    os.makedirs(workdir, exist_ok=True)
    a_path, s_path, o_path = (os.path.join(workdir, n) for n in ("gigaam_audio.npy", "gigaam_segs.json", "gigaam_out.json"))
    np.save(a_path, audio16k.astype(np.float32))
    with open(s_path, "w", encoding="utf-8") as f:
        json.dump(segs, f)
    if status:
        status("GigaAM-v3")
    p = _giga_proc(py, mdir)
    for pth in (o_path,):
        if os.path.isfile(pth):
            os.remove(pth)
    p.stdin.write(f"{a_path}|{s_path}|{o_path}" + chr(10))
    p.stdin.flush()
    while True:
        line = p.stdout.readline()
        if not line:
            gigaam_stop()
            raise RuntimeError("GigaAM: " + _tail(getattr(p, "log_path", "")))
        if line.startswith("P ") and on_progress:
            try:
                on_progress(float(line[2:]))
            except ValueError:
                pass
        elif line.startswith("DONE"):
            break
        elif line.startswith("ERR"):
            raise RuntimeError("GigaAM: " + line[4:].strip())
    with open(o_path, encoding="utf-8") as f:
        words = json.load(f)
    for pth in (a_path, s_path, o_path):
        try:
            os.remove(pth)
        except OSError:
            pass
    return words
