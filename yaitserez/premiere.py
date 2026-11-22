"""Чтение проекта Premiere Pro (.prproj): какие куски каких файлов стоят в последовательности.

.prproj — это XML в gzip. Объекты ссылаются друг на друга по ObjectID / ObjectUID:
последовательность → группы дорожек → дорожки → клипы на дорожке (Start/End в тиках) →
SubClip → Clip (InPoint/OutPoint) → MediaSource → Media (путь к файлу).
"""
from __future__ import annotations

import glob
import gzip
import os
import xml.etree.ElementTree as ET

TICKS = 254016000000  # тиков Premiere в секунде


def _load(path: str):
    root = ET.fromstring(gzip.open(path).read())
    by = {}
    for e in root:
        k = e.get("ObjectID") or e.get("ObjectUID")
        if k:
            by[k] = e
    return root, by


def _ref(by: dict, el):
    if el is None:
        return None
    return by.get(el.get("ObjectRef") or el.get("ObjectURef"))


def sequences(path: str) -> dict[str, list[dict]]:
    """{имя последовательности: [клип]}; клип — kind (video/audio), track, start/end (с, на таймлайне),
    in/out (с, в исходнике), path."""
    root, by = _load(path)
    out: dict[str, list[dict]] = {}
    for seq in (e for e in root if e.tag == "Sequence"):
        items: list[dict] = []
        groups = seq.find("TrackGroups")
        for tg in groups if groups is not None else []:
            g = _ref(by, tg.find("Second"))
            trs = g.find("TrackGroup/Tracks") if g is not None else None
            for tr in trs if trs is not None else []:
                t = _ref(by, tr)
                if t is None:
                    continue
                ti = int(t.findtext(".//ClipTrack/Track/Index") or t.findtext(".//Track/Index") or -1)
                for it in t.findall(".//ClipItems/TrackItems/TrackItem"):
                    x = _ref(by, it)
                    cti = x.find("ClipTrackItem") if x is not None else None
                    if cti is None:
                        continue
                    sub = _ref(by, cti.find("SubClip"))
                    clip = _ref(by, sub.find("Clip")) if sub is not None else None
                    c = clip.find("Clip") if clip is not None else None
                    if c is None:
                        continue
                    src = _ref(by, c.find("Source"))
                    media = _ref(by, src.find("MediaSource/Media")) if src is not None else None
                    fp = media.findtext("FilePath") if media is not None else None
                    if not fp:
                        continue
                    items.append({
                        "kind": "video" if x.tag.startswith("Video") else "audio", "track": ti,
                        "start": int(cti.findtext("TrackItem/Start") or 0) / TICKS,
                        "end": int(cti.findtext("TrackItem/End") or 0) / TICKS,
                        "in": int(c.findtext("InPoint") or 0) / TICKS,
                        "out": int(c.findtext("OutPoint") or 0) / TICKS, "path": fp,
                    })
        out[seq.findtext("Name") or ""] = items
    return out


def candidates(folder: str) -> list[str]:
    """Проекты Premiere рядом с проектом Яйцереза, новые первыми (автосохранения тоже)."""
    found = set()
    for base in {folder, os.path.dirname(folder)}:
        for pat in ("*.prproj", os.path.join("Adobe Premiere Pro Auto-Save", "*.prproj")):
            found.update(glob.glob(os.path.join(base, pat)))
    return sorted(found, key=os.path.getmtime, reverse=True)


def final_edit(analysis: dict, folder: str, alt_gap: float = 3.0) -> tuple[list[dict], str] | None:
    """Итоговый монтаж из Premiere по камерам этого проекта: [{clip, in, out}] без блока запасных дублей.
    Берётся самый свежий .prproj, где есть последовательность с этими камерами."""
    names = {os.path.basename(c["path"]).lower(): i for i, c in enumerate(analysis["clips"])}
    for path in candidates(folder)[:4]:
        try:
            seqs = sequences(path)
        except Exception:  # noqa: BLE001 — битый или чужой файл
            continue
        best = None
        for items in seqs.values():
            cam = [x for x in items if x["kind"] == "video" and os.path.basename(x["path"]).lower() in names]
            if cam and (best is None or len(cam) > len(best)):
                best = cam
        if not best:
            continue
        best.sort(key=lambda x: x["start"])
        # запасные дубли Яйцерез ставит после паузы alt_gap — отрезаем всё после первой такой дыры
        end, cut = 0.0, len(best)
        for k, x in enumerate(best):
            if k and x["start"] - end >= alt_gap * 0.95:
                cut = k
                break
            end = max(end, x["end"])
        edl = [{"clip": names[os.path.basename(x["path"]).lower()], "in": x["in"], "out": x["out"]} for x in best[:cut]]
        return edl, path
    return None
