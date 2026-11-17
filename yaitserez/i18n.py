"""Язык сообщений ядра (ru / en)."""
LANG = "ru"


def set_lang(lang: str) -> None:
    global LANG
    LANG = "en" if lang == "en" else "ru"


def L(ru: str, en: str) -> str:
    return en if LANG == "en" else ru
