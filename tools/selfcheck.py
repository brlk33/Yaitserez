"""Самопроверка новых частей без видеокарты и моделей: python tools/selfcheck.py

* стиль по образцу: синтетическая «речь» с известной паузой на склейках → XML → измеренная пауза;
* автообновление: архив релиза ставится в пустую папку, лишнее не копируется.
"""
import io
import os
import sys
import tempfile
import wave
import zipfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from yaitserez import style, update  # noqa: E402
from yaitserez.xmlexport import pathurl  # noqa: E402

SR, FPS = 16000, 25
HEAD, TAIL = 0.04, 0.16          # сколько тишины монтажёр оставил до и после голоса


def make_source(path: str, n: int = 8) -> list[tuple[float, float]]:
    """«Фразы» по 1,2 с через 1,5 с тишины; перед каждой второй — тихий вдох. Возвращает края голоса."""
    rng = np.random.default_rng(1)
    t, out, parts = 1.0, [], []
    x = rng.normal(0, 0.0007, int((n * 2.7 + 2) * SR)).astype(np.float32)
    for k in range(n):
        a = int(t * SR)
        tt = np.arange(int(1.2 * SR)) / SR
        x[a:a + len(tt)] += 0.25 * (np.sin(2 * np.pi * 180 * tt) + 0.5 * np.sin(2 * np.pi * 360 * tt))
        if k % 2:
            b = int((t - 0.35) * SR)
            x[b:b + int(0.3 * SR)] += rng.normal(0, 0.003, int(0.3 * SR))
        out.append((t, t + 1.2))
        t += 2.7
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return out


def make_xml(path: str, src: str, voice: list[tuple[float, float]]) -> None:
    items, t = [], 0
    for a, b in voice:
        i, o = round((a - HEAD) * FPS), round((b + TAIL) * FPS)
        items.append(f"<clipitem><start>{t}</start><end>{t + o - i}</end><in>{i}</in><out>{o}</out>"
                     f'<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate><file id="f1">'
                     f"<pathurl>{pathurl(src)}</pathurl>"
                     f"</file></clipitem>")
        t += o - i
    xml = (f"<?xml version='1.0'?><xmeml version='4'><sequence><name>Тест</name><rate><timebase>{FPS}</timebase>"
           f"<ntsc>FALSE</ntsc></rate><media><video><track>{''.join(items)}</track></video></media></sequence></xmeml>")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)


def check_style(tmp: str) -> None:
    src = os.path.join(tmp, "сырой звук.wav")
    voice = make_source(src)
    xml = os.path.join(tmp, "монтаж.xml")
    make_xml(xml, src, voice)
    seq, items = style.read_edit(xml)
    assert seq == "Тест" and len(items) == len(voice), (seq, len(items))
    assert os.path.normcase(items[0]["path"]) == os.path.normcase(os.path.normpath(src)), items[0]["path"]
    rep = style.learn(xml, {"pause": 0.5, "cut_breaths": True})
    assert rep["cuts"] == len(voice) - 1, rep
    assert abs(rep["pause"] - (HEAD + TAIL)) <= 0.03, rep
    # вдох перед каждой второй фразой оставлен (голова куска 0,04 с не захватывает вдох за 0,35 с до голоса)
    assert rep["breath_share"] < style.BREATH_SHARE and rep["after"]["cut_breaths"] is True, rep
    assert rep["before"]["pause"] == 0.5
    print(f"style: пауза {rep['pause']} с (ожидалось {HEAD + TAIL:.2f}), склеек {rep['cuts']}")


def check_update(tmp: str) -> None:
    assert update.parse("v1.10.0") > update.parse("1.9.3") and update.parse("1.4") == (1, 4, 0)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for rel, body in {"app.py": "new", "version.txt": "9.9.9", "yaitserez/x.py": "x", "ui/app.js": "js",
                          "tools/make_exe.py": "t", "Yaitserez-Setup.exe": "MZ", "installer/installer.nsi": "n",
                          ".gitignore": "g", "tools/uv/uv.exe": "no"}.items():
            z.writestr("brlk33-Yaitserez-abc/" + rel, body)
    dst = os.path.join(tmp, "install")
    os.makedirs(dst)
    old_root, old_dl = update.ROOT, update._download
    update.ROOT, update._download = dst, (lambda url, progress: buf.getvalue())
    try:
        update.install({"zip": "x", "version": "9.9.9"})
    finally:
        update.ROOT, update._download = old_root, old_dl
    got = sorted(os.path.relpath(os.path.join(r, n), dst).replace("\\", "/") for r, _d, ns in os.walk(dst) for n in ns)
    assert got == ["app.py", "tools/make_exe.py", "ui/app.js", "version.txt", "yaitserez/x.py"], got
    print("update: поставлены", ", ".join(got))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        check_style(d)
        check_update(d)
    print("OK")
