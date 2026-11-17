"""Где программа хранит модели, кеш, превью и настройки.

Порядок: переменная YAITSEREZ_HOME → существующая папка D:\\Program Files\\Yaitserez (так было у автора,
диск C занят) → папка data рядом с программой (обычная установка).
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def app_dir() -> str:
    d = os.environ.get("YAITSEREZ_HOME")
    if not d:
        legacy = r"D:\Program Files\Yaitserez"
        d = legacy if os.path.isdir(legacy) else os.path.join(ROOT, "data")
    os.makedirs(d, exist_ok=True)
    return d


def sub(name: str) -> str:
    d = os.path.join(app_dir(), name)
    os.makedirs(d, exist_ok=True)
    return d


def models_dir() -> str:
    return sub("models")


def cache_dir() -> str:
    return sub("cache")


# Библиотеки HuggingFace по умолчанию кешируют в профиль на диске C — перенаправляем.
os.environ.setdefault("HF_HOME", os.path.join(app_dir(), "hf"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
