"""Автообновление: новая версия — это релиз на GitHub (тег vX.Y.Z).

Проверяем последний релиз, скачиваем архив исходников этого тега, при смене requirements.txt
доставляем библиотеки (старая версия от этого не ломается), потом заменяем файлы программы
и перезапускаемся. Папки .venv, data, tools/ffmpeg и т. п. не трогаем.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from .i18n import L

REPO = "brlk33/Yaitserez"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "Yaitserez-updater", "Accept": "application/vnd.github+json"}
TOP_FILES = {"app.py", "version.txt", "requirements.txt", "README.md", "install.bat", "Яйцерез.bat"}
NO_WINDOW = 0x08000000


def parse(v: str) -> tuple[int, ...]:
    v = v.strip().lstrip("vV")
    out = []
    for part in v.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits or 0))
    return tuple(out + [0] * (3 - len(out)))


def dev_checkout() -> bool:
    """Запуск из git-клона: файлы не перезаписываем, обновляются через git."""
    return os.path.isdir(os.path.join(ROOT, ".git"))


def check(current: str, timeout: float = 8.0) -> dict | None:
    """{"version", "notes", "zip"} если на GitHub версия новее, иначе None."""
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest", headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        rel = json.loads(r.read().decode("utf-8"))
    tag = rel.get("tag_name") or ""
    if not tag or parse(tag) <= parse(current):
        return None
    return {"version": tag.lstrip("vV"), "notes": (rel.get("body") or "")[:2000],
            "zip": f"https://codeload.github.com/{REPO}/zip/refs/tags/{tag}"}


def _download(url: str, progress) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
    buf = io.BytesIO()
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0)
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            buf.write(chunk)
            if progress:
                progress(min(0.6, 0.6 * buf.tell() / total) if total else 0.3,
                         L("Скачиваю обновление…", "Downloading the update…"))
    return buf.getvalue()


def wanted(rel: str) -> bool:
    """Какие файлы из архива — код программы (остальное в установке своё и не трогается)."""
    if "/" not in rel:
        return rel in TOP_FILES
    top, rest = rel.split("/", 1)
    if top == "yaitserez":
        return rest.endswith(".py") and "/" not in rest
    if top == "ui":
        return "/" not in rest
    if top == "tools":
        return rest.endswith(".py") and "/" not in rest
    return False


def install(info: dict, progress=None) -> None:
    """Скачивает и ставит обновление. Исключение — значит ничего не заменено."""
    if dev_checkout():
        raise RuntimeError(L("Программа запущена из git-клона — обновите её через git pull",
                             "Running from a git clone — update with git pull"))
    data = _download(info["zip"], progress)
    z = zipfile.ZipFile(io.BytesIO(data))
    names = [n for n in z.namelist() if not n.endswith("/")]
    prefix = next((n[: -len("app.py")] for n in names if n.endswith("/app.py") and n.count("/") == 1), None)
    if prefix is None:
        raise RuntimeError(L("В архиве обновления нет программы", "The update archive has no program"))
    files = {n[len(prefix):]: n for n in names if n.startswith(prefix) and wanted(n[len(prefix):])}

    # библиотеки — до замены файлов: если не поставятся, остаёмся на старой версии
    new_req = z.read(files["requirements.txt"]) if "requirements.txt" in files else b""
    try:
        old_req = open(os.path.join(ROOT, "requirements.txt"), "rb").read()
    except OSError:
        old_req = b""
    if new_req and new_req.strip() != old_req.strip():
        if progress:
            progress(0.7, L("Ставлю новые библиотеки…", "Installing new libraries…"))
        _pip(new_req)

    if progress:
        progress(0.9, L("Заменяю файлы…", "Replacing files…"))
    for rel, name in files.items():
        dst = os.path.join(ROOT, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + ".new"
        with open(tmp, "wb") as f:
            f.write(z.read(name))
        os.replace(tmp, dst)
    _registry_version(info["version"])


def _pip(req: bytes) -> None:
    uv = os.path.join(ROOT, "tools", "uv", "uv.exe")
    py = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    if not (os.path.isfile(uv) and os.path.isfile(py)):
        return  # не обычная установка — библиотеки ставит сам человек
    fd, path = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "wb") as f:
        f.write(req)
    env = {**os.environ, "UV_CACHE_DIR": os.path.join(ROOT, "data", "uv-cache"),
           "UV_PYTHON_INSTALL_DIR": os.path.join(ROOT, "tools", "python"), "UV_HTTP_TIMEOUT": "300"}
    try:
        r = subprocess.run([uv, "pip", "install", "--python", py, "-r", path], env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    finally:
        os.remove(path)
    if r.returncode:
        raise RuntimeError(L("Не удалось поставить библиотеки: ", "Could not install libraries: ") + r.stderr[-400:])


def _registry_version(v: str) -> None:
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Yaitserez",
                           0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, v)
    except OSError:
        pass


def restart() -> None:
    """Запустить программу заново через пару секунд (старое окно успеет закрыться) и выйти."""
    cmd = f'ping -n 3 127.0.0.1 >nul & start "" "{sys.executable}" "{os.path.join(ROOT, "app.py")}"'
    subprocess.Popen(["cmd", "/c", cmd], cwd=ROOT, creationflags=NO_WINDOW)
    os._exit(0)
