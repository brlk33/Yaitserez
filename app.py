"""Яйцерез — окно приложения (pywebview) и мост между интерфейсом и ядром."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

import webview

from yaitserez import cutter, pipeline, xmlexport
from yaitserez.i18n import L, set_lang
from yaitserez.media import classify, probe
from yaitserez.paths import app_dir, cache_dir
from yaitserez.winctl import WinCtl, native_hwnd

HERE = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(HERE, "ui")
SETTINGS_PATH = os.path.join(app_dir(), "settings.json")
try:
    with open(os.path.join(HERE, "version.txt"), encoding="utf-8-sig") as _f:
        VERSION = _f.read().strip() or "1.0.0"
except OSError:
    VERSION = "1.0.0"

DEFAULTS = {
    "remove_silence": True,
    "max_pause": 0.5,
    "keep_pause": 0.3,
    "pause": 0.2,
    "equalize": True,
    "pause_place": "auto",
    "pre_roll": 0.05,
    "cut_breaths": True,
    "cut_profanity": True,
    "cut_fillers": True,
    "cut_words": [],
    "volume": 1.0,
    "screen_enabled": False,
    "show_screen": False,
    "show_track": 0,
    "breath_sens": 0.6,
    "preview_quality": "original",
    "ui_zoom": 1.0,
    "drop_bad_takes": True,
    "smart_takes": True,
    "takes_strictness": "medium",
    "hotkey_preset": "premiere",
    "snapping": True,
    "llm_model": "9b",
    "asr_engine": "auto",
    "recent_projects": [],
    "screen_view": "cam",
    "xml_names": "source",
    "zoom_a": 100, "zoom_b": 115, "zoom_bx": 0, "zoom_by": 0, "zoom_min": 1.0, "zoom_inside": True,
    "breath_mode": "all",
    "hotkeys": None,
    "keep_alternates": True,
    "prefer_take": "last",
    "alt_gap": 3.0,
    "camera_audio": "muted",
    "keep_silent_clips": True,
    "language": "ru",
    "model": "large-v3-turbo",
    "theme": "system",
    "ui_lang": "ru",
    "learned": None,     # «Учиться на моих правках»: {"params", "examples", "report"}
    "style_ref": None,   # «Стиль нарезки по образцу»: отчёт последнего образца
    "auto_update": True,
}


def load_settings() -> dict:
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        s.update({k: v for k, v in saved.items() if k in DEFAULTS})
        if "pause" not in saved:  # настройки от прошлой версии: переносим паузу, режим — «авто без вдохов»
            s["pause"] = float(saved.get("keep_pause", DEFAULTS["pause"]))
            s["pause_place"] = "auto"
    except (OSError, ValueError):
        pass
    s.update(FIXED)
    return s


# Настройки, убранные из интерфейса: всегда лучшее значение (старые сохранённые не мешают)
FIXED = {"equalize": True, "pause_place": "auto", "smart_takes": True, "prefer_take": "last",
         "camera_audio": "muted", "keep_silent_clips": False, "screen_enabled": False}


DL: dict = {}
LEARN: dict = {"busy": False, "cancel": False}
UPD: dict = {"info": None, "busy": False}


class State:
    def __init__(self):
        self.files: dict[str, object] = {}
        self.next_id = 1
        self.analysis: dict | None = None
        self.overrides: dict[str, str] = {}
        self.word_overrides: dict[str, str] = {}
        self.trims: dict[str, float] = {}
        self.settings = load_settings()
        self.cancel = False
        self.busy = False
        self.class_key = None
        self.project_path = None
        self.model_state = "loading"
        self.model_error = ""
        self.result_json = b"{}"


STATE = State()
WIN = WinCtl()
WINDOW: webview.Window | None = None


# ---------- локальный сервер: интерфейс + видео превью с поддержкой Range ----------
MIME = {".m4a": "audio/mp4", ".aac": "audio/aac", ".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac",
        ".ogg": "audio/ogg", ".opus": "audio/ogg", ".mov": "video/mp4", ".mp4": "video/mp4", ".m4v": "video/mp4"}
CHUNK = 8 << 20
SCREEN_NAME = re.compile(r"screen|экран|скрин|obs|capture|display|desktop", re.I)  # отдаём большие исходники кусками, браузер дозапрашивает сам


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=UI_DIR, **kw)

    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.startswith("/api/result"):
            body = STATE.result_json
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        m = re.match(r"^/(media|audio|light|half|screen)/(\d+)", self.path)
        if not m:
            return super().do_GET()
        an = STATE.analysis
        idx = int(m.group(2))
        kind = m.group(1)
        if kind == "screen":
            scr = (an or {}).get("screens") or []
            if idx >= len(scr):
                return self.send_error(404)
            clip = {"proxy_ready": True, "video_src": scr[idx]["path"]}
            kind = "media"
        elif not an or idx >= len(an["clips"]):
            return self.send_error(404)
        else:
            clip = an["clips"][idx]
        if kind == "light":
            path = clip.get("light") if clip.get("light_ready") else None
        elif kind == "half":
            path = clip.get("half") if clip.get("half_ready") else None
        elif not clip.get("proxy_ready"):
            return self.send_error(404)
        else:
            path = clip["video_src"] if kind == "media" else clip.get("audio_src")
        if not path or not os.path.isfile(path):
            return self.send_error(404)
        size = os.path.getsize(path)
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng:
            mm = re.match(r"bytes=(\d*)-(\d*)", rng)
            if mm:
                if mm.group(1):
                    start = int(mm.group(1))
                    end = min(int(mm.group(2)), size - 1) if mm.group(2) else min(start + CHUNK - 1, size - 1)
                else:
                    start = max(0, size - int(mm.group(2)))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            end = min(CHUNK - 1, size - 1) if size > CHUNK else size - 1
            self.send_response(206 if end < size - 1 else 200)
            if end < size - 1:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        ext = os.path.splitext(path)[1].lower()
        self.send_header("Content-Type", MIME.get(ext, "video/mp4"))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (ConnectionError, OSError):
            pass


def start_server() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


def push(fn: str, payload) -> None:
    if WINDOW is not None:
        try:
            WINDOW.evaluate_js(f"window.App && App.{fn}({json.dumps(payload, ensure_ascii=False)})")
        except Exception:  # noqa: BLE001
            pass


WAVE_FPS = 200


def waveforms(an: dict) -> list[str]:
    """Громкость звука микрофона для дорожки A1: 25 значений в секунду, 0–255, base64 по клипу."""
    import base64

    import numpy as np

    if an.get("peaks"):
        return [base64.b64encode(p).decode("ascii") for p in an["peaks"]]
    out = []
    for env in an.get("env") or []:
        e = np.repeat(np.asarray(env, dtype=np.float32), 2)   # старый анализ без пиков: 100 → 200 в секунду
        v = np.clip((e + 60.0) / 54.0, 0.0, 1.0) * 255.0
        out.append(base64.b64encode(v.astype(np.uint8).tobytes()).decode("ascii"))
    return out


def fmt_info(info) -> str:
    if info.kind == "video":
        fps = info.fps
        fps_s = f"{fps:.3f}".rstrip("0").rstrip(".")
        return f"{info.width}×{info.height} · {fps_s} " + L("к/с", "fps")
    ch = {1: L("моно", "mono"), 2: L("стерео", "stereo")}.get(info.channels, f"{info.channels} ch")
    return f"{info.sample_rate / 1000:g} " + L("кГц", "kHz") + f" · {ch}"


def file_public(fid: str, info) -> dict:
    return {"id": fid, "name": info.name, "kind": info.kind, "duration": info.duration, "info": fmt_info(info),
            "path": info.path, "noaudio": not info.has_audio, "noVideo": not info.has_video,
            "w": info.width, "h": info.height, "fps": round(info.fps, 3), "sr": info.sample_rate, "ch": info.channels}


# ---------- API для интерфейса ----------
def plan_from_edl(an: dict, auto: dict, edl: list, settings: dict) -> dict:
    """Ручной монтаж из интерфейса (куски по порядку) + запасные дубли из автоматики — в формат плана."""
    timeline, t = [], 0.0
    for it in edl:
        c, a, b = int(it["clip"]), float(it["in"]), float(it["out"])
        if b - a <= 0.02:
            continue
        timeline.append({"clip": c, "in": round(a, 3), "out": round(b, 3), "t": round(t, 3), "kind": "main",
                         "phrases": list(it.get("phrases") or []), "lab": it.get("lab"), "z": it.get("z")})
        t += b - a
    main_dur = t
    alts = [x for x in auto["timeline"] if x["kind"] == "alt"]
    alt_start = None
    if alts:
        t += float(settings.get("alt_gap", 3.0))
        alt_start = t
        for x in alts:
            timeline.append({**x, "t": round(t, 3)})
            t += x["out"] - x["in"]
    cutter._attach_screens(an, timeline)
    return {**auto, "timeline": timeline, "duration": round(t, 3), "main_duration": round(main_dur, 3),
            "alt_start": alt_start}


class Api:
    def init(self):
        from yaitserez.transcribe import find_local_model, preload

        local = find_local_model(STATE.settings["model"])
        if STATE.model_state != "ready":
            STATE.model_state = "loading"

            def done(err):
                STATE.model_state = "error" if err else "ready"
                STATE.model_error = err or ""
                push("modelState", {"state": STATE.model_state, "error": STATE.model_error})

            preload(STATE.settings["model"], done)
        return {
            "modelState": STATE.model_state,
            "settings": STATE.settings,
            "version": VERSION,
            "model": "VoiceType" if local else None,
            "gigaam": __import__("yaitserez.transcribe", fromlist=["x"]).gigaam_available(),
            "files": [file_public(k, v) for k, v in STATE.files.items()],
        }

    def save_settings(self, s: dict):
        STATE.settings.update({k: v for k, v in s.items() if k in DEFAULTS})
        set_lang(STATE.settings.get("ui_lang", "ru"))
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(STATE.settings, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
        return True

    def add_paths(self, paths: list[str]):
        added, errors = [], []
        known = {v.path for v in STATE.files.values()}
        expanded = []
        for p in paths:
            if os.path.isdir(p):
                for root, _dirs, names in os.walk(p):
                    expanded += [os.path.join(root, n) for n in sorted(names)]
            else:
                expanded.append(p)
        for p in expanded:
            p = os.path.abspath(p)
            if p in known or not classify(p):
                continue
            try:
                info = probe(p)
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))
                continue
            if info.kind == "audio" and not info.has_audio:
                continue
            if info.kind == "video" and SCREEN_NAME.search(info.name):
                info.kind = "screen"  # запись экрана — по имени файла
            fid = str(STATE.next_id)
            STATE.next_id += 1
            STATE.files[fid] = info
            known.add(p)
            added.append(file_public(fid, info))
        return {"added": added, "errors": errors}

    def pick_files(self):
        res = WINDOW.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=True,
            file_types=(L("Видео и звук", "Video and audio") +
                        " (*.mp4;*.mov;*.mxf;*.mts;*.m2ts;*.avi;*.mkv;*.m4v;*.wav;*.mp3;*.m4a;*.aac;*.flac)",
                        L("Все файлы", "All files") + " (*.*)"))
        if not res:
            return {"added": [], "errors": []}
        return self.add_paths(list(res))

    def remove_file(self, fid: str):
        STATE.files.pop(fid, None)
        return True

    def clear_files(self):
        STATE.files.clear()
        return True

    def set_kind(self, fid: str, kind: str):
        f = STATE.files.get(fid)
        if f is not None and kind in ("video", "audio", "screen") and (kind == "audio" or f.has_video):
            f.kind = kind
        return True

    def start(self, settings: dict):
        if STATE.busy or LEARN["busy"]:
            return False
        self.save_settings(settings)
        STATE.cancel = False
        STATE.busy = True
        STATE.overrides = {}
        STATE.word_overrides = {}
        STATE.trims = {}
        STATE.class_key = None
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def _run(self):
        try:
            STATE.project_path = None   # новая обработка — новый проект
            files = list(STATE.files.values())
            videos = [f for f in files if f.kind == "video"]
            mics = [f for f in files if f.kind == "audio"]
            screens = [f for f in files if f.kind == "screen"]
            def on_proxy(i, n, total, err, light=False):
                push("proxyReady", {"clip": i, "done": n, "total": total, "error": err, "light": light})

            an = pipeline.analyze(videos, mics, STATE.settings,
                                  lambda st, fr, msg: push("progress", {"stage": st, "fraction": fr, "message": msg}),
                                  lambda: STATE.cancel, on_proxy, screens=screens)
            STATE.analysis = an
            self._classify()
            plan = cutter.build_plan(an, STATE.settings, STATE.overrides, STATE.word_overrides, STATE.trims)
            STATE.result_json = json.dumps({"analysis": pipeline.public_analysis(an), "plan": plan,
                                            "wave": waveforms(an), "waveFps": WAVE_FPS},
                                           ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            push("done", {})
        except pipeline.Cancelled:
            push("cancelled", {})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            push("failed", {"message": str(e)})
        finally:
            STATE.busy = False

    def cancel(self):
        STATE.cancel = True
        return True

    def replan(self, settings: dict, overrides: dict, word_overrides: dict | None = None, trims: dict | None = None):
        if not STATE.analysis:
            return None
        self.save_settings(settings)
        STATE.overrides = {str(k): v for k, v in (overrides or {}).items()}
        STATE.word_overrides = {str(k): v for k, v in (word_overrides or {}).items()}
        if trims is not None:
            STATE.trims = {str(k): float(v) for k, v in trims.items() if abs(float(v)) > 1e-4}
        self._classify()
        return cutter.build_plan(STATE.analysis, STATE.settings, STATE.overrides, STATE.word_overrides, STATE.trims)

    def reanalyze(self, settings: dict, overrides: dict, word_overrides: dict, ids: list):
        """«Проанализировать заново» выделенный участок: нейросеть заново разбирает дубли его фраз,
        склейки пересчитываются с текущими настройками. Ручные правки участка интерфейс уже сбросил."""
        if not STATE.analysis or STATE.busy or LEARN["busy"]:
            return None
        self.save_settings(settings)
        STATE.busy = True
        STATE.cancel = False
        try:
            n = pipeline.reanalyze(STATE.analysis, ids, STATE.settings,
                                   progress=lambda fr, msg: push("reanalyzeProgress", {"fraction": fr, "message": msg}),
                                   cancelled=lambda: STATE.cancel)
            STATE.class_key = None
            plan = self.replan(settings, overrides, word_overrides)
            return {"plan": plan, "dropped": n}
        except pipeline.Cancelled:
            return {"cancelled": True}
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return {"error": str(e)}
        finally:
            STATE.busy = False

    def add_tracks(self, paths: list | None = None):
        """Добавить видео на дополнительные дорожки в готовый монтаж (скринкаст, вторая камера…)."""
        if not STATE.analysis:
            return None
        if paths is None:
            res = WINDOW.create_file_dialog(
                webview.FileDialog.OPEN, allow_multiple=True,
                file_types=(L("Видео", "Video") + " (*.mp4;*.mov;*.mxf;*.mts;*.m2ts;*.avi;*.mkv;*.m4v)",))
            paths = list(res or [])
        infos = []
        for p in paths:
            if classify(p) == "video":
                try:
                    infos.append(probe(p))
                except Exception:  # noqa: BLE001
                    pass
        if not infos:
            return {"added": [], "screens": pipeline.public_screens(STATE.analysis)}
        added = pipeline.add_extra(STATE.analysis, infos)
        plan = cutter.build_plan(STATE.analysis, STATE.settings, STATE.overrides, STATE.word_overrides, STATE.trims)
        return {"added": [{"name": c["name"], "ok": c["sync"]["ok"], "track": c.get("track", 0)} for c in added],
                "screens": pipeline.public_screens(STATE.analysis), "plan": plan}

    def add_tracks_dropped(self):
        import time

        from webview.dom import _dnd_state

        for _ in range(20):
            if _dnd_state["paths"]:
                break
            time.sleep(0.05)
        paths = [p for _, p in _dnd_state["paths"]]
        _dnd_state["paths"].clear()
        return self.add_tracks(paths)

    def _classify(self):
        """Разбор дублей зависит только от двух настроек — пересчитываем лишь при их смене."""
        key = (STATE.settings.get("drop_bad_takes"), STATE.settings.get("prefer_take"),
               STATE.settings.get("takes_strictness"),
               json.dumps((STATE.settings.get("learned") or {}).get("params"), sort_keys=True))
        if key != STATE.class_key:
            pipeline.classify(STATE.analysis, STATE.settings)
            STATE.class_key = key

    # --- проекты: нарезка сохраняется в файл .yaitserez и открывается потом ---
    def save_project(self, ui: dict, path: str | None = None, save_as: bool = False):
        import pickle
        import zipfile

        an = STATE.analysis
        if not an:
            return None
        path = path or STATE.project_path
        if save_as or not path:
            first = an["clips"][0]["path"] if an["clips"] else os.path.expanduser("~")
            folder = os.path.dirname(first)
            name = os.path.basename(folder) or "Yaitserez"
            res = WINDOW.create_file_dialog(webview.FileDialog.SAVE, directory=folder,
                                            save_filename=f"{name}.yaitserez",
                                            file_types=(L("Проект Яйцереза", "Yaitserez project") + " (*.yaitserez)",))
            if not res:
                return None
            path = res if isinstance(res, str) else res[0]
            if not path.lower().endswith(".yaitserez"):
                path += ".yaitserez"
        keep = {k: v for k, v in an.items() if k not in ("proxies", "more_proxies", "_breaths", "_onsets", "_offsets")}
        meta = {"format": 1, "version": VERSION, "ui": ui,
                "files": [{"path": f.path, "kind": f.kind} for f in STATE.files.values()],
                "settings": {k: v for k, v in STATE.settings.items() if k not in ("recent_projects", "hotkeys", "learned", "style_ref")}}
        tmp = path + ".tmp"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.writestr("project.json", json.dumps(meta, ensure_ascii=False))
            z.writestr("analysis.pkl", pickle.dumps(keep, protocol=pickle.HIGHEST_PROTOCOL))
        os.replace(tmp, path)
        STATE.project_path = path
        self._remember(path)
        return {"path": path, "name": os.path.basename(path)}

    def _remember(self, path: str):
        rec = [p for p in STATE.settings.get("recent_projects") or [] if p != path and os.path.isfile(p)]
        self.save_settings({"recent_projects": [path] + rec[:7]})

    def recent_projects(self):
        return [{"path": p, "name": os.path.basename(p)} for p in STATE.settings.get("recent_projects") or []
                if os.path.isfile(p)]

    def open_project(self, path: str | None = None):
        import pickle
        import zipfile

        if STATE.busy:
            return {"error": L("Сейчас идёт обработка", "Processing is running")}
        if not path:
            res = WINDOW.create_file_dialog(webview.FileDialog.OPEN,
                                            file_types=(L("Проект Яйцереза", "Yaitserez project") + " (*.yaitserez)",))
            if not res:
                return None
            path = res if isinstance(res, str) else res[0]
        try:
            with zipfile.ZipFile(path) as z:
                meta = json.loads(z.read("project.json").decode("utf-8"))
                an = pickle.loads(z.read("analysis.pkl"))
        except Exception as e:  # noqa: BLE001
            return {"error": L(f"Не удалось открыть проект: {e}", f"Could not open the project: {e}")}
        missing = [c["path"] for c in an["clips"] + an["mics"] if not os.path.isfile(c["path"])]
        if missing:
            return {"error": L("Не найдены исходники: ", "Source files not found: ") + ", ".join(os.path.basename(m) for m in missing[:4])}
        STATE.files.clear()
        self.add_paths([f["path"] for f in meta.get("files", [])])
        kinds = {f["path"]: f["kind"] for f in meta.get("files", [])}
        for info in STATE.files.values():
            info.kind = kinds.get(info.path, info.kind)
        ui = meta.get("ui") or {}
        STATE.overrides = {str(k): v for k, v in (ui.get("overrides") or {}).items()}
        STATE.word_overrides = {str(k): v for k, v in (ui.get("wordOverrides") or {}).items()}
        STATE.trims = {}
        STATE.class_key = None
        for k in ("remove_silence", "pause", "cut_breaths", "breath_sens", "breath_mode", "drop_bad_takes",
                  "takes_strictness", "keep_alternates", "cut_profanity", "cut_fillers", "cut_words", "language"):
            if k in (meta.get("settings") or {}):
                STATE.settings[k] = meta["settings"][k]
        self.save_settings({})

        def on_proxy(i, n, total, err, light=False):
            push("proxyReady", {"clip": i, "done": n, "total": total, "error": err, "light": light})
        an["proxies"] = pipeline.ProxyQueue(an["clips"], an["mics"], on_proxy, lambda: False,
                                            light=STATE.settings.get("preview_quality") == "light")
        STATE.analysis = an
        self._classify()
        plan = cutter.build_plan(an, STATE.settings, STATE.overrides, STATE.word_overrides, STATE.trims)
        STATE.result_json = json.dumps({"analysis": pipeline.public_analysis(an), "plan": plan,
                                        "wave": waveforms(an), "waveFps": WAVE_FPS},
                                       ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        STATE.project_path = path
        self._remember(path)
        return {"ok": True, "ui": ui, "path": path, "name": os.path.basename(path), "settings": STATE.settings}

    # --- дозаписанные исходники: в конец готового монтажа ---
    def append_sources(self, paths: list | None = None):
        if not STATE.analysis or STATE.busy:
            return None
        if paths is None:
            res = WINDOW.create_file_dialog(
                webview.FileDialog.OPEN, allow_multiple=True,
                file_types=(L("Видео и звук", "Video and audio") +
                            " (*.mp4;*.mov;*.mxf;*.mts;*.m2ts;*.avi;*.mkv;*.m4v;*.wav;*.mp3;*.m4a;*.aac;*.flac)",))
            paths = list(res or [])
        known = {c["path"] for c in STATE.analysis["clips"]} | {m["path"] for m in STATE.analysis["mics"]} \
            | {s["path"] for s in STATE.analysis.get("screens") or []}
        before = set(STATE.files)
        self.add_paths([p for p in paths if os.path.abspath(p) not in known])
        new = [STATE.files[k] for k in STATE.files if k not in before]
        videos = [f for f in new if f.kind == "video"]
        mics = [f for f in new if f.kind == "audio"]
        screens = [f for f in new if f.kind == "screen"]
        if not videos and not mics:
            return {"added": 0}
        STATE.busy = True
        STATE.cancel = False
        threading.Thread(target=self._append_run, args=(videos, mics, screens), daemon=True).start()
        return {"started": True, "videos": len(videos), "mics": len(mics), "screens": len(screens)}

    def append_dropped(self):
        import time

        from webview.dom import _dnd_state

        for _ in range(20):
            if _dnd_state["paths"]:
                break
            time.sleep(0.05)
        paths = [p for _, p in _dnd_state["paths"]]
        _dnd_state["paths"].clear()
        return self.append_sources(paths)

    def _append_run(self, videos, mics, screens):
        try:
            def on_proxy(i, n, total, err, light=False):
                push("proxyReady", {"clip": i, "done": n, "total": total, "error": err, "light": light})
            n = pipeline.append_sources(STATE.analysis, videos, mics, screens, STATE.settings,
                                        lambda st, fr, msg: push("progress", {"stage": st, "fraction": fr, "message": msg}),
                                        lambda: STATE.cancel, on_proxy)
            STATE.class_key = None
            self._classify()
            plan = cutter.build_plan(STATE.analysis, STATE.settings, STATE.overrides, STATE.word_overrides, STATE.trims)
            STATE.result_json = json.dumps({"analysis": pipeline.public_analysis(STATE.analysis), "plan": plan,
                                            "wave": waveforms(STATE.analysis), "waveFps": WAVE_FPS},
                                           ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            push("appended", {"added": n})
        except pipeline.Cancelled:
            push("appendFailed", {"message": L("Остановлено", "Stopped")})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            push("appendFailed", {"message": str(e)})
        finally:
            STATE.busy = False

    def set_quality(self, q: str):
        """«original» — исходник + звук микрофона; «light» — лёгкие копии 540p со звуком внутри."""
        q = q if q in ("light", "half") else "original"
        self.save_settings({"preview_quality": q})
        an = STATE.analysis
        for pq in ([an.get("proxies")] + list(an.get("more_proxies") or [])) if an else []:
            if pq is None:
                continue
            if q == "light":
                pq.request_light()
            elif q == "half":
                pq.request_half()
        return True

    # --- модель для разбора дублей ---
    # --- учимся на ручном монтаже ---
    def learn_info(self):
        """Проекты, на которых можно учиться (недавние и открытый), и прошлый отчёт."""
        from yaitserez import llm
        paths = [STATE.project_path] if STATE.project_path else []
        paths += [p for p in STATE.settings.get("recent_projects") or [] if p not in paths]
        llm.CHOICE["model"] = STATE.settings.get("llm_model", "9b")
        learned = STATE.settings.get("learned") or {}
        return {"projects": [{"path": p, "name": os.path.basename(p)} for p in paths if p and os.path.isfile(p)],
                "report": learned.get("report"), "llm": llm.available(), "busy": LEARN["busy"]}

    def learn_add(self):
        res = WINDOW.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                                        file_types=(L("Проект Яйцереза", "Yaitserez project") + " (*.yaitserez)",))
        return [{"path": p, "name": os.path.basename(p)} for p in (res or [])]

    def learn_start(self, paths: list, use_llm: bool = True):
        from yaitserez import learn
        if LEARN["busy"] or STATE.busy or not paths:
            return False
        LEARN.update(busy=True, cancel=False)

        def work():
            from yaitserez import transcribe as tr
            if use_llm:
                tr.release()  # видеопамять — под языковую модель
            try:
                res = learn.run(list(paths), dict(STATE.settings),
                                progress=lambda fr, msg: push("learnProgress", {"fraction": fr, "message": msg}),
                                cancelled=lambda: LEARN["cancel"], use_llm=bool(use_llm))
                self.save_settings({"learned": res, "takes_strictness": res["params"]["takes_strictness"]})
                push("learnDone", {"report": res["report"], "settings": STATE.settings})
            except learn.Cancelled:
                push("learnDone", {"cancelled": True})
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                push("learnDone", {"error": str(e)})
            finally:
                from yaitserez import llm
                llm.SERVER.stop()
                if use_llm:
                    tr.preload(STATE.settings["model"])
                LEARN["busy"] = False

        threading.Thread(target=work, daemon=True).start()
        return True

    def learn_cancel(self):
        LEARN["cancel"] = True
        return True

    def learn_reset(self):
        self.save_settings({"learned": None, "takes_strictness": "medium"})
        return STATE.settings

    # --- стиль нарезки по образцу: XML / проект Premiere ---
    def style_pick(self):
        res = WINDOW.create_file_dialog(webview.FileDialog.OPEN, file_types=(
            L("Монтаж Premiere или DaVinci", "Premiere or DaVinci edit") + " (*.xml;*.prproj)",))
        if not res:
            return None
        return res if isinstance(res, str) else res[0]

    def style_start(self, path: str):
        from yaitserez import style
        if LEARN["busy"] or not path or not os.path.isfile(path):
            return False
        LEARN.update(busy=True, cancel=False)

        def work():
            try:
                rep = style.learn(path, dict(STATE.settings),
                                  progress=lambda fr, msg: push("styleProgress", {"fraction": fr, "message": msg}),
                                  cancelled=lambda: LEARN["cancel"])
                self.save_settings({**rep["after"], "style_ref": rep})
                push("styleDone", {"report": rep, "settings": STATE.settings})
            except style.Cancelled:
                push("styleDone", {"cancelled": True})
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                push("styleDone", {"error": str(e)})
            finally:
                LEARN["busy"] = False

        threading.Thread(target=work, daemon=True).start()
        return True

    def style_undo(self):
        rep = STATE.settings.get("style_ref") or {}
        back = {k: v for k, v in (rep.get("before") or {}).items() if v is not None}
        self.save_settings({**back, "style_ref": None})
        return STATE.settings

    # --- обновления ---
    def check_update(self, manual: bool = False):
        from yaitserez import update
        if not manual and not STATE.settings.get("auto_update", True):
            return None
        try:
            UPD["info"] = update.check(VERSION)
        except Exception:  # noqa: BLE001 — нет интернета или GitHub недоступен: молча
            return None
        return UPD["info"] and {"version": UPD["info"]["version"], "notes": UPD["info"]["notes"],
                                "dev": update.dev_checkout()}

    def install_update(self):
        from yaitserez import update
        if not UPD["info"] or UPD["busy"] or STATE.busy or LEARN["busy"]:
            return False
        UPD["busy"] = True

        def work():
            try:
                update.install(UPD["info"], lambda fr, msg: push("updateProgress", {"fraction": fr, "message": msg}))
                push("updateProgress", {"fraction": 1.0, "message": L("Перезапускаю…", "Restarting…")})
                update.restart()
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                push("updateFailed", {"message": str(e)})
            finally:
                UPD["busy"] = False

        threading.Thread(target=work, daemon=True).start()
        return True

    def llm_status(self):
        from yaitserez import llm
        llm.CHOICE["model"] = STATE.settings.get("llm_model", "9b")
        return {**llm.status(), "busy": bool(DL.get("busy"))}

    def set_llm(self, choice: str):
        from yaitserez import llm
        if choice not in llm.MODELS:
            return False
        self.save_settings({"llm_model": choice})
        llm.CHOICE["model"] = choice
        llm.SERVER.stop()      # следующий разбор запустит выбранную модель
        STATE.class_key = None
        return self.llm_status()

    def download_llm(self, choice: str):
        from yaitserez import llm
        if DL.get("busy") or choice not in llm.MODELS:
            return False
        DL.update(busy=True, cancel=False)

        def run():
            err = None
            try:
                llm.download(choice, lambda fr, g, t: push("llmProgress", {"choice": choice, "fraction": fr, "got": g, "total": t}),
                             lambda: DL.get("cancel"))
            except Exception as e:  # noqa: BLE001
                err = str(e)
            DL.update(busy=False)
            push("llmDone", {"choice": choice, "error": err, "status": self.llm_status()})
        threading.Thread(target=run, daemon=True).start()
        return True

    def cancel_llm_download(self):
        DL["cancel"] = True
        return True

    def set_lang(self, lang: str):
        self.save_settings({"ui_lang": lang})
        return True

    def export(self, edl: list | None = None):
        an = STATE.analysis
        if not an:
            return None
        first = an["clips"][0]["path"]
        folder = os.path.dirname(first)
        name = os.path.basename(folder) or L("Монтаж", "Edit")
        res = WINDOW.create_file_dialog(webview.FileDialog.SAVE, directory=folder,
                                        save_filename=f"{name} — Yaitserez.xml", file_types=("XML (*.xml)",))
        if not res:
            return None
        path = res if isinstance(res, str) else res[0]
        if not path.lower().endswith(".xml"):
            path += ".xml"
        plan = cutter.build_plan(an, STATE.settings, STATE.overrides, STATE.word_overrides, STATE.trims)
        if edl:
            plan = plan_from_edl(an, plan, edl, STATE.settings)
        xmlexport.export(path, an, plan, STATE.settings, name=f"{name} — Yaitserez")
        return path

    # --- окно ---
    def win_drag(self):
        WIN.drag()

    def win_resize(self, edge: str):
        WIN.resize(edge)

    def win_toggle_max(self):
        return WIN.toggle_max()

    def win_min(self):
        WIN.minimize()

    def win_close(self):
        STATE.cancel = True
        threading.Timer(0.05, lambda: os._exit(0)).start()

    def take_dropped(self):
        """Страница зовёт это сразу после drop; WebView2 к этому моменту уже передал настоящие пути."""
        import time

        from webview.dom import _dnd_state

        for _ in range(20):
            if _dnd_state["paths"]:
                break
            time.sleep(0.05)
        paths = [p for _, p in _dnd_state["paths"]]
        _dnd_state["paths"].clear()
        return self.add_paths(paths)

    # --- кеш ---
    def cache_info(self):
        d = cache_dir()
        size = 0
        for root, _dirs, names in os.walk(d):
            for n in names:
                try:
                    size += os.path.getsize(os.path.join(root, n))
                except OSError:
                    pass
        return {"path": d, "size": size}

    def clear_cache(self):
        if STATE.busy:
            return False
        d = cache_dir()
        keep = set()
        if STATE.analysis:  # превью текущего монтажа не трогаем — их сейчас смотрят
            keep = {os.path.normcase(c.get(k) or "") for c in STATE.analysis["clips"] for k in ("video_src", "audio_src")}
        for n in os.listdir(d):
            p = os.path.join(d, n)
            if os.path.isfile(p) and os.path.normcase(p) not in keep:
                try:
                    os.remove(p)
                except OSError:
                    pass
        return self.cache_info()

    def open_folder(self, path: str):
        if os.path.isdir(path):
            os.startfile(path)
        return True

    def reveal(self, path: str):
        if os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        return True


def set_app_identity():
    """Своё имя приложения в Windows: панель задач группирует окно под яйцом, а не под питоном."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Yaytsa.Yaitserez")
    except Exception:  # noqa: BLE001
        pass


def set_window_icon(hwnd: int):
    try:
        import ctypes

        u32 = ctypes.windll.user32
        u32.LoadImageW.restype = ctypes.c_void_p
        u32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        ico = os.path.join(HERE, "ui", "icon.ico")
        for size, which in ((16, 0), (32, 1)):  # ICON_SMALL, ICON_BIG
            h = u32.LoadImageW(None, ico, 1, size * 2 if which else size, size * 2 if which else size, 0x10)
            if h:
                u32.SendMessageW(hwnd, 0x0080, which, h)  # WM_SETICON
    except Exception:  # noqa: BLE001
        pass


def main():
    global WINDOW
    set_app_identity()
    set_lang(STATE.settings.get("ui_lang", "ru"))
    port = start_server()
    theme = STATE.settings.get("theme", "system")
    dark = theme == "dark"
    if theme == "system":
        try:
            import winreg

            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            dark = winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        except OSError:
            pass
    WINDOW = webview.create_window(
        "Яйцерез", f"http://127.0.0.1:{port}/index.html", js_api=Api(), width=1240, height=840,
        min_size=(860, 600), background_color="#191919" if dark else "#FFFFFF", text_select=False,
        frameless=True, easy_drag=False, shadow=True)

    def on_start():
        from webview.dom import _dnd_state

        # WebView2 будет отдавать настоящие пути перетащенных файлов (см. Api.take_dropped)
        _dnd_state["num_listeners"] = max(1, _dnd_state["num_listeners"])
        try:
            WIN.attach(native_hwnd(WINDOW))
            set_window_icon(WIN.hwnd)
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    webview.start(on_start, private_mode=False, storage_path=os.path.join(app_dir(), "webview"),
                  debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
