"""Экспорт монтажа в XML (Final Cut Pro 7 XML / xmeml v4).

Этот формат открывают Premiere Pro, DaVinci Resolve, Final Cut Pro 7, Avid (через импорт) и др.
"""
from __future__ import annotations

import os
from urllib.parse import quote
from xml.sax.saxutils import escape

from .i18n import L

STD_RATES = [(24000, 1001, 24, True), (30000, 1001, 30, True), (60000, 1001, 60, True)]


def rate_of(num: int, den: int) -> tuple[int, bool, float]:
    """(timebase, ntsc, точное fps)."""
    fps = num / den
    for n, d, tb, ntsc in STD_RATES:
        if abs(fps - n / d) < 0.01:
            return tb, ntsc, n / d
    tb = int(round(fps)) or 25
    return tb, False, float(tb) if abs(fps - tb) < 0.01 else fps


def pathurl(path: str) -> str:
    p = os.path.abspath(path).replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        drive, rest = p[0], p[2:]
        return "file://localhost/" + drive + "%3a" + quote(rest, safe="/")
    return "file://localhost" + quote(p, safe="/")


def _rate(tb: int, ntsc: bool) -> str:
    return f"<rate><timebase>{tb}</timebase><ntsc>{'TRUE' if ntsc else 'FALSE'}</ntsc></rate>"


def _tc(tb: int, ntsc: bool) -> str:
    return (f"<timecode>{_rate(tb, ntsc)}<string>00:00:00:00</string><frame>0</frame>"
            f"<displayformat>NDF</displayformat></timecode>")


class _Files:
    def __init__(self, tb, ntsc, fps):
        self.tb, self.ntsc, self.fps = tb, ntsc, fps
        self.ids: dict[str, str] = {}

    def ref(self, info: dict) -> str:
        path = info["path"]
        if path in self.ids:
            return f'<file id="{self.ids[path]}"/>'
        fid = f"file-{len(self.ids) + 1}"
        self.ids[path] = fid
        dur = int(round(info["duration"] * self.fps))
        media = ""
        if info.get("has_video"):
            media += (f"<video><samplecharacteristics>{_rate(self.tb, self.ntsc)}<width>{info['width']}</width>"
                      f"<height>{info['height']}</height><pixelaspectratio>square</pixelaspectratio>"
                      f"<fielddominance>none</fielddominance></samplecharacteristics></video>")
        if info.get("has_audio"):
            media += (f"<audio><samplecharacteristics><depth>16</depth><samplerate>{info['sample_rate']}</samplerate>"
                      f"</samplecharacteristics><channelcount>{info['channels']}</channelcount></audio>")
        return (f'<file id="{fid}"><name>{escape(os.path.basename(path))}</name><pathurl>{escape(pathurl(path))}</pathurl>'
                f"{_rate(self.tb, self.ntsc)}<duration>{dur}</duration>{_tc(self.tb, self.ntsc)}<media>{media}</media></file>")


def export(path: str, analysis: dict, plan: dict, settings: dict, name: str = "Yaitserez") -> None:
    clips = analysis["clips"]
    mics = analysis["mics"]
    phrases = analysis["phrases"]
    first = next((c for c in clips if not c.get("audio_only")), clips[0])
    tb, ntsc, fps = rate_of(first.get("fps_num") or 25, first.get("fps_den") or 1)
    width, height = first["width"] or 1920, first["height"] or 1080
    files = _Files(tb, ntsc, fps)
    cam_audio = settings.get("camera_audio", "muted")  # "muted" | "on" | "off"

    def F(t: float) -> int:
        return int(round(t * fps))

    v_items, a_mic, a_cam = [], [], []
    v_tracks: dict[int, list[str]] = {}
    screens = analysis.get("screens") or []
    scr_on = "TRUE" if settings.get("screen_enabled", False) else "FALSE"
    markers = []
    pos = 0
    n = 0
    alt_started = False
    for item in plan["timeline"]:
        clip = clips[item["clip"]]
        src_in, src_out = F(item["in"]), F(item["out"])
        if src_out <= src_in:
            continue
        # таймлайн — в целых кадрах; позиция берётся из накопленных кадров, чтобы не было дыр
        if item["kind"] == "alt" and not alt_started:
            alt_started = True
            pos += F(float(settings.get("alt_gap", 3.0))) if (v_items or a_mic) else 0
        start = pos
        end = start + (src_out - src_in)
        pos = end
        n += 1
        vid, mid, cid = f"clipitem-v{n}", f"clipitem-m{n}", f"clipitem-c{n}"
        sync = clip["sync"]
        has_mic = sync["ok"] and sync["mic"] is not None
        audio_only = bool(clip.get("audio_only"))   # проект без видео: только дорожка звука
        links = [] if audio_only else [(vid, "video", 1, len(v_items) + 1)]
        mic_xml = None
        if has_mic:
            mic = mics[sync["mic"]]
            m_in = F(item["in"] + sync["offset"])
            m_out = m_in + (src_out - src_in)
            if m_in >= 0 and m_out <= F(mic["duration"]) + 1:
                links.append((mid, "audio", 1, len(a_mic) + 1))
                mic_xml = (mid, mic, m_in, m_out)
        cam_on = not audio_only and clip["has_audio"] and (cam_audio != "off" or mic_xml is None)
        if cam_on:
            links.append((cid, "audio", 2, len(a_cam) + 1))

        def link_xml():
            return "".join(
                f"<link><linkclipref>{ref}</linkclipref><mediatype>{mt}</mediatype><trackindex>{ti}</trackindex>"
                f"<clipindex>{ci}</clipindex>{'<groupindex>1</groupindex>' if mt == 'audio' else ''}</link>"
                for ref, mt, ti, ci in links)

        # метки цветом из Яйцереза → цвета меток Premiere; запасные дубли — Mango, как раньше
        LABEL_NAMES = {1: "Rose", 2: "Mango", 3: "Yellow", 4: "Forest", 5: "Cerulean", 6: "Violet"}
        lab = LABEL_NAMES.get(item.get("lab")) or ("Mango" if item["kind"] == "alt" else None)
        label = lab is not None
        # название клипа: как у исходника или по фразе, которая в нём звучит
        cname = escape(clip["name"])
        if settings.get("xml_names") == "phrase" and item.get("phrases"):
            txt = " ".join(phrases[i]["text"] for i in item["phrases"] if 0 <= i < len(phrases)).strip()
            if txt:
                cname = escape(txt[:120])
        z = item.get("z") or None
        motion = ""
        if z and not audio_only:
            w_, h_ = clip.get("width") or width, clip.get("height") or height
            motion = ("<filter><effect><name>Basic Motion</name><effectid>basic</effectid><effectcategory>motion</effectcategory>"
                      "<effecttype>motion</effecttype><mediatype>video</mediatype>"
                      f"<parameter><parameterid>scale</parameterid><name>Scale</name><valuemin>0</valuemin><valuemax>1000</valuemax><value>{float(z.get('s', 100)):.2f}</value></parameter>"
                      f"<parameter><parameterid>center</parameterid><name>Center</name><value><horiz>{float(z.get('x', 0)) / w_:.5f}</horiz><vert>{float(z.get('y', 0)) / h_:.5f}</vert></value></parameter>"
                      "</effect></filter>")
        if not audio_only:
          v_items.append(
            f'<clipitem id="{vid}"><name>{cname}</name><enabled>TRUE</enabled>'
            f"<duration>{F(clip['duration'])}</duration>{_rate(tb, ntsc)}<start>{start}</start><end>{end}</end>"
            f"<in>{src_in}</in><out>{src_out}</out>{files.ref(clip)}"
            f"{motion}{f'<labels><label2>{lab}</label2></labels>' if label else ''}{link_xml()}</clipitem>")
        for scr in item.get("scr") or []:
            if scr[0] >= len(screens):
                continue
            # та же нарезка с дополнительной дорожки: тот же момент по времени микрофона
            sc = screens[scr[0]]
            s_in = F(scr[1])
            s_start, s_out = start, s_in + (src_out - src_in)
            if s_in < 0:  # запись экрана началась позже начала куска
                s_start, s_in = start - s_in, 0
            s_out = min(s_out, F(sc["duration"]))
            if s_out - s_in > 1:
                v_tracks.setdefault(sc.get("track", 0), []).append(
                    f'<clipitem id="clipitem-s{n}-{scr[0]}"><name>{escape(sc["name"])}</name><enabled>{scr_on}</enabled>'
                    f"<duration>{F(sc['duration'])}</duration>{_rate(tb, ntsc)}<start>{s_start}</start>"
                    f"<end>{s_start + (s_out - s_in)}</end><in>{s_in}</in><out>{s_out}</out>{files.ref(sc)}</clipitem>")
        if mic_xml:
            _, mic, m_in, m_out = mic_xml
            a_mic.append(
                f'<clipitem id="{mid}"><name>{escape(mic["name"])}</name><enabled>TRUE</enabled>'
                f"<duration>{F(mic['duration'])}</duration>{_rate(tb, ntsc)}<start>{start}</start><end>{end}</end>"
                f"<in>{m_in}</in><out>{m_out}</out>{files.ref(mic)}"
                f"{f'<labels><label2>{lab}</label2></labels>' if label else ''}"
                f"<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>{link_xml()}</clipitem>")
        if cam_on:
            enabled = "TRUE" if (cam_audio == "on" or mic_xml is None) else "FALSE"
            a_cam.append(
                f'<clipitem id="{cid}"><name>{cname}</name><enabled>{enabled}</enabled>'
                f"<duration>{F(clip['duration'])}</duration>{_rate(tb, ntsc)}<start>{start}</start><end>{end}</end>"
                f"<in>{src_in}</in><out>{src_out}</out>{files.ref(clip)}"
                f"<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>{link_xml()}</clipitem>")
        if item["kind"] == "alt" and item.get("phrase") is not None:
            p = phrases[item["phrase"]]
            if not markers or markers[-1][2] != p["id"]:
                markers.append((start, L("Запасной дубль: ", "Alt take: ") + p["text"][:80], p["id"]))

    if plan.get("alt_start") is not None and markers:
        markers.insert(0, (markers[0][0], L("▼ ЗАПАСНЫЕ ДУБЛИ", "▼ ALTERNATE TAKES"), -1))

    total = pos
    marker_xml = "".join(
        f"<marker><name>{escape(m[1])}</name><comment></comment><in>{m[0]}</in><out>-1</out></marker>" for m in markers)
    vfmt = (f"<format><samplecharacteristics>{_rate(tb, ntsc)}<width>{width}</width><height>{height}</height>"
            f"<anamorphic>FALSE</anamorphic><pixelaspectratio>square</pixelaspectratio>"
            f"<fielddominance>none</fielddominance></samplecharacteristics></format>")
    afmt = "<format><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics></format>"
    tracks_a = ""
    for items in (a_mic, a_cam):
        tracks_a += f"<track><enabled>TRUE</enabled><locked>FALSE</locked>{''.join(items)}</track>"
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">'
        f'<sequence id="sequence-1"><name>{escape(name)}</name><duration>{total}</duration>{_rate(tb, ntsc)}'
        f"{_tc(tb, ntsc)}<media><video>{vfmt}<track><enabled>TRUE</enabled><locked>FALSE</locked>{''.join(v_items)}</track>"
        + "".join(f"<track><enabled>TRUE</enabled><locked>FALSE</locked>{''.join(v_tracks[t])}</track>"
                  for t in sorted(v_tracks))
        + "</video>"
        f"<audio><numOutputChannels>2</numOutputChannels>{afmt}{tracks_a}</audio></media>{marker_xml}</sequence></xmeml>\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
