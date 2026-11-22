"""Скачать нейросеть для разбора дублей (вызывается из install.bat): python tools/get_llm.py 9b|4b"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from yaitserez import llm  # noqa: E402
from yaitserez.paths import app_dir  # noqa: E402


def main() -> int:
    choice = (sys.argv[1] if len(sys.argv) > 1 else "9b").lower()
    if choice not in llm.MODELS:
        print("No AI model selected - it can be downloaded later in Settings.")
        return 0
    m = llm.MODELS[choice]
    print(f"Downloading {m['file']} ({m['size'] / 1e9:.1f} GB)...", flush=True)
    last = [-1]

    def progress(fr, got, total):
        pct = int(fr * 100)
        if pct // 5 != last[0]:
            last[0] = pct // 5
            print(f"  {pct}%  {got / 1e9:.2f} / {(total or m['size']) / 1e9:.2f} GB", flush=True)

    try:
        llm.download(choice, progress)
    except Exception as e:  # noqa: BLE001 — без нейросети программа работает, скачать можно в настройках
        print(f"Could not download the AI model: {e}")
        print("Yaitserez works without it; download it later in Settings.")
        return 0
    path = os.path.join(app_dir(), "settings.json")
    data = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
    data["llm_model"] = choice
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("AI model ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
