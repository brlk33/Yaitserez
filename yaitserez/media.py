"""Работа с ffmpeg/ffprobe: поиск бинарников, чтение метаданных, загрузка звука."""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

import numpy as np

VIDEO_EXT = {".mp4", ".mov", ".mxf", ".mts", ".m2ts", ".avi", ".mkv", ".m4v", ".webm", ".mpg", ".mpeg", ".3gp"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".aif", ".aiff", ".wma"}

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _find_tool(name: str) -> str:
    exe = name + (".exe" if sys.platform == "win32" else "")
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    from .paths import app_dir

    for local in (os.path.join(here, "bin", exe), os.path.join(here, "tools", "ffmpeg", "bin", exe),
                  os.path.join(here, "tools", "ffmpeg", exe), os.path.join(app_dir(), "ffmpeg", exe)):
        if os.path.isfile(local):
            return local
    found = shutil.which(name)
    if found:
        return found
    la = os.environ.get("LOCALAPPDATA", "")
    candidates = [os.path.join(la, "Microsoft", "WinGet", "Links", exe)]
    candidates += glob.glob(os.path.join(la, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "*", "bin", exe))
    for c in candidates:
        if os.path.isfile(c):
            return c
    raise RuntimeError(f"Не найден {name}. Установите ffmpeg (winget install Gyan.FFmpeg).")


FFMPEG = None
FFPROBE = None


def ffmpeg() -> str:
    global FFMPEG
    if FFMPEG is None:
        FFMPEG = _find_tool("ffmpeg")
    return FFMPEG


def ffprobe() -> str:
    global FFPROBE
    if FFPROBE is None:
        FFPROBE = _find_tool("ffprobe")
    return FFPROBE


def run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, creationflags=_NO_WINDOW, **kw)


@dataclass
class MediaInfo:
    path: str
    kind: str  # "video" | "audio"
    duration: float
    has_video: bool = False
    has_audio: bool = False
    width: int = 0
    height: int = 0
    fps_num: int = 25
    fps_den: int = 1
    sample_rate: int = 48000
    channels: int = 2
    creation_time: str | None = None
    timecode: str | None = None
    video_codec: str = ""
    pix_fmt: str = ""
    profile: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def fps(self) -> float:
        return self.fps_num / self.fps_den

    @property
    def name(self) -> str:
        return os.path.basename(self.path)


def probe(path: str) -> MediaInfo:
    p = run([ffprobe(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    if p.returncode != 0:
        raise RuntimeError(f"Не удалось прочитать файл: {os.path.basename(path)}")
    data = json.loads(p.stdout.decode("utf-8", "replace"))
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    ext = os.path.splitext(path)[1].lower()
    kind = "video" if v is not None and ext not in AUDIO_EXT else "audio"
    dur = float(fmt.get("duration") or (v or a or {}).get("duration") or 0)
    info = MediaInfo(path=path, kind=kind, duration=dur, has_video=v is not None, has_audio=a is not None)
    tags = dict(fmt.get("tags", {}))
    if v is not None:
        info.width = int(v.get("width") or 0)
        info.height = int(v.get("height") or 0)
        info.video_codec = v.get("codec_name", "")
        info.pix_fmt = v.get("pix_fmt", "") or ""
        info.profile = v.get("profile", "") or ""
        rate = v.get("r_frame_rate") or v.get("avg_frame_rate") or "25/1"
        try:
            n, d = (int(x) for x in rate.split("/"))
            if n > 0 and d > 0:
                info.fps_num, info.fps_den = n, d
        except ValueError:
            pass
        tags.update(v.get("tags", {}))
    if a is not None:
        info.sample_rate = int(a.get("sample_rate") or 48000)
        info.channels = int(a.get("channels") or 2)
    info.creation_time = tags.get("creation_time")
    info.timecode = tags.get("timecode")
    return info


def load_audio(path: str, sr: int, start: float = 0.0, duration: float | None = None) -> np.ndarray:
    """Моно float32 с частотой sr. Отрицательный start дополняется тишиной слева."""
    pad = 0
    if start < 0:
        pad = int(round(-start * sr))
        if duration is not None:
            duration = duration + start
        start = 0.0
    args = [ffmpeg(), "-v", "error", "-nostdin"]
    if start > 0:
        args += ["-ss", f"{start:.6f}"]
    args += ["-i", path]
    if duration is not None:
        if duration <= 0:
            return np.zeros(pad, dtype=np.float32)
        args += ["-t", f"{duration:.6f}"]
    args += ["-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    p = run(args)
    if p.returncode != 0:
        raise RuntimeError(f"Не удалось прочитать звук: {os.path.basename(path)}")
    x = np.frombuffer(p.stdout, dtype=np.float32).copy()
    if pad:
        x = np.concatenate([np.zeros(pad, dtype=np.float32), x])
    return x


def browser_playable(info: MediaInfo) -> bool:
    """Может ли встроенный браузер (WebView2) сам проиграть это видео — тогда превью не нужно."""
    ext = os.path.splitext(info.path)[1].lower()
    return (info.video_codec == "h264" and info.pix_fmt in ("yuv420p", "yuvj420p")
            and "4:2:2" not in info.profile and "10" not in info.profile and "4:4:4" not in info.profile
            and ext in (".mp4", ".mov", ".m4v") and info.width <= 4096)


def classify(path: str) -> str | None:
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    return None
