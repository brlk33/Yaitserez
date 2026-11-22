"""Экспорт монтажа в XML (Final Cut Pro 7 XML / xmeml v4).

Этот формат открывают Premiere Pro, DaVinci Resolve, Final Cut Pro 7, Avid (через импорт) и др.
"""
from __future__ import annotations

import os
import re
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


def _ensure_streams(info: dict) -> None:
    """Старые проекты не знают, сколько аудиопотоков в файле — дочитываем."""
    if not info.get("has_audio") or info.get("audio_channels"):
        return
    try:
        from .media import probe
        info["audio_channels"] = probe(info["path"]).audio_channels or [info.get("channels") or 2]
    except Exception:
        info["audio_channels"] = [info.get("channels") or 2]


def _stream_sources(sc: dict, out_dir: str) -> list[dict]:
    """Звук скринкаста: [первый поток из самого файла, остальные непустые — отдельными WAV].
    Premiere из MP4 читает только первый аудиопоток, поэтому дорожки OBS «звук компьютера» и т. п.
    вынимаем в «<папка XML>/Звук скринкаста/». Пустые (тишина) пропускаем."""
    if not sc.get("has_audio"):
        return []
    out = [sc]
    chans = sc.get("audio_channels") or [sc.get("channels") or 2]
    if len(chans) < 2:
        return out
    from .media import ffmpeg, run
    silent = sc.setdefault("silent_streams", {})
    folder = os.path.join(out_dir, L("Звук скринкаста", "Screen audio"))
    for k in range(1, len(chans)):
        if str(k) not in silent:
            p = run([ffmpeg(), "-nostdin", "-vn", "-i", sc["path"], "-map", f"0:a:{k}", "-af", "volumedetect",
                     "-f", "null", "-"])
            txt = p.stderr.decode("utf-8", "replace")
            mx = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", txt)
            silent[str(k)] = (mx is None) or mx.group(1) == "-inf" or float(mx.group(1)) < -60
        if silent[str(k)]:
            continue
        wav = os.path.join(folder, f"{os.path.splitext(sc['name'])[0]} a{k + 1}.wav")
        if not os.path.isfile(wav):
            os.makedirs(folder, exist_ok=True)
            run([ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", sc["path"], "-map", f"0:a:{k}",
                 "-c:a", "pcm_s16le", wav])
        if os.path.isfile(wav):
            out.append({"path": wav, "name": os.path.basename(wav), "duration": sc["duration"], "has_video": False,
                        "has_audio": True, "sample_rate": sc.get("sample_rate") or 48000, "channels": chans[k],
                        "stream": k})
    return out


def _track(items: list[str], channels: int) -> str:
    kind = "Mono" if channels == 1 else "Stereo"
    return (f'<track currentExplodedTrackIndex="0" totalExplodedTrackCount="1" premiereTrackType="{kind}">'
            f"<enabled>TRUE</enabled><locked>FALSE</locked>{''.join(items)}</track>")


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
    screens = analysis.get("screens") or []
    scr_on = "TRUE" if settings.get("screen_enabled", False) else "FALSE"
    out_dir = os.path.dirname(os.path.abspath(path))
    used = {s[0] for it in plan["timeline"] for s in it.get("scr") or []}
    srcs = []
    for i, sc in enumerate(screens):
        if i in used:
            _ensure_streams(sc)
        srcs.append(_stream_sources(sc, out_dir) if i in used else [])
    # дорожки видео скринкастов (V2…) и их звука (A3…): номер дорожки → порядок в XML
    v_keys = sorted({sc.get("track", 0) for sc in screens})
    a_keys = sorted({(sc.get("track", 0), src.get("stream", 0)) for sc, ss in zip(screens, srcs) for src in ss})
    a_ch = {k: 2 for k in a_keys}
    for sc, ss in zip(screens, srcs):
        for src in ss:
            if src["channels"] == 1:
                a_ch[(sc.get("track", 0), src.get("stream", 0))] = 1
    v_tracks = {t: [] for t in v_keys}
    sa_tracks: dict[tuple, list[str]] = {k: [] for k in a_keys}
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
                t = sc.get("track", 0)
                s_end = s_start + (s_out - s_in)
                base = f"clipitem-s{n}-{scr[0]}"
                slinks = [(base, "video", 2 + v_keys.index(t), len(v_tracks[t]) + 1)]
                ss = srcs[scr[0]]
                n_str = len(ss)
                for src in ss:
                    k = src.get("stream", 0)
                    slinks.append((f"{base}-a{k + 1}", "audio", 3 + a_keys.index((t, k)), len(sa_tracks[(t, k)]) + 1))
                slink = "".join(
                    f"<link><linkclipref>{ref}</linkclipref><mediatype>{mt}</mediatype><trackindex>{ti}</trackindex>"
                    f"<clipindex>{ci}</clipindex>{'<groupindex>1</groupindex>' if mt == 'audio' else ''}</link>"
                    for ref, mt, ti, ci in slinks) if n_str else ""
                common = (f"<duration>{F(sc['duration'])}</duration>{_rate(tb, ntsc)}<start>{s_start}</start>"
                          f"<end>{s_end}</end><in>{s_in}</in><out>{s_out}</out>")
                v_tracks[t].append(
                    f'<clipitem id="{base}"><name>{escape(sc["name"])}</name><enabled>{scr_on}</enabled>'
                    f"{common}{files.ref(sc)}{slink}</clipitem>")
                for src in ss:
                    k = src.get("stream", 0)
                    sa_tracks[(t, k)].append(
                        f'<clipitem id="{base}-a{k + 1}"><name>{escape(src["name"])}</name><enabled>TRUE</enabled>'
                        f"{common}{files.ref(src)}"
                        f"<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>"
                        f"{slink}</clipitem>")
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
    mic_ch = 1 if mics and all((m.get("channels") or 1) == 1 for m in mics) else 2
    cam_ch = 1 if clips and all((c.get("channels") or 2) == 1 for c in clips) else 2
    tracks_a += _track(a_mic, mic_ch) + _track(a_cam, cam_ch)
    for k in a_keys:
        tracks_a += _track(sa_tracks[k], a_ch[k])
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
