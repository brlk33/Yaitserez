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
