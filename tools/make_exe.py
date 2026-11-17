"""Собирает Yaitserez.exe — своё имя процесса и иконка-яйцо вместо питона — и ярлык на рабочем столе.

Yaitserez.exe — это копия оконного pythonw.exe рядом с виртуальным окружением, в ресурсы которой
записаны иконка и название (как у VoiceType). Окно и панель задач показывают яйцо, а не питона.
"""
import os
import shutil
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, ".venv", "Scripts")
EXE = os.path.join(SCRIPTS, "Yaitserez.exe")
ICO = os.path.join(ROOT, "ui", "icon.ico")
RCEDIT_URL = "https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe"


def base_python_dir() -> str:
    with open(os.path.join(ROOT, ".venv", "pyvenv.cfg"), encoding="utf-8") as f:
        for line in f:
            k, _, v = line.partition("=")
            if k.strip() == "home":
                return v.strip()
    raise RuntimeError("в pyvenv.cfg нет home")


def find_rcedit() -> str:
    for p in (os.path.join(ROOT, "tools", "rcedit.exe"), r"D:\Program Files\VoiceType\tools\rcedit.exe"):
        if os.path.isfile(p):
            return p
    dst = os.path.join(ROOT, "tools", "rcedit.exe")
    urllib.request.urlretrieve(RCEDIT_URL, dst)
    return dst


def version() -> str:
    p = os.path.join(ROOT, "version.txt")
    return open(p, encoding="utf-8").read().strip() if os.path.isfile(p) else "1.0.0"


def main():
    home = base_python_dir()
    shutil.copy2(os.path.join(home, "pythonw.exe"), EXE)
    for dll in ("python312.dll", "python3.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        src = os.path.join(home, dll)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(SCRIPTS, dll))
    v = version()
    subprocess.run([find_rcedit(), EXE, "--set-icon", ICO,
                    "--set-version-string", "FileDescription", "Яйцерез",
                    "--set-version-string", "ProductName", "Яйцерез",
                    "--set-version-string", "CompanyName", "Яйца",
                    "--set-version-string", "InternalName", "Yaitserez",
                    "--set-version-string", "OriginalFilename", "Yaitserez.exe",
                    "--set-file-version", v, "--set-product-version", v], check=True)
    print(EXE)


if __name__ == "__main__":
    main()
