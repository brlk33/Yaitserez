"""Синхронизация звука с микрофона со звуком камеры через взаимную корреляцию (GCC-PHAT).

Двухступенчато: грубый поиск по всей записи микрофона на 2 кГц (быстро даже для 4 часов),
затем уточнение на 16 кГц в окне ±0,1 с с субсэмпловой точностью.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
from scipy import fft as sfft

from .i18n import L
from .media import MediaInfo, load_audio

COARSE_SR = 2000
FINE_SR = 16000
MAX_CAM_SPAN = 600.0  # для грубого поиска хватает 10 минут звука камеры


@dataclass
class SyncResult:
    mic_index: int | None  # индекс файла микрофона или None
    offset: float  # время_микрофона = время_видео + offset
    confidence: float
    ok: bool


def _prep(x: np.ndarray) -> np.ndarray:
    x = x.astype(np.float32, copy=False)
    if x.size:
        x = x - x.mean()
    s = float(np.std(x)) + 1e-9
    return np.clip(x / s, -6, 6).astype(np.float32)


def _phat(R: np.ndarray) -> np.ndarray:
    mag = np.abs(R)
    R /= mag + 1e-3 * (float(mag.mean()) + 1e-12)
    return R


def _peak(corr: np.ndarray, valid: np.ndarray, sr: int) -> tuple[int, float]:
    c = np.where(valid, corr, -np.inf)
    k = int(np.argmax(c))
    vals = corr[valid]
    mu, sd = float(vals.mean()), float(vals.std()) + 1e-12
    z = (corr[k] - mu) / sd
    w = int(0.05 * sr)
    c[max(0, k - w): k + w + 1] = -np.inf
    z2 = (float(np.max(c)) - mu) / sd if np.isfinite(np.max(c)) else 0.0
    # уверенность: высота пика с поправкой на то, насколько он выделяется среди остальных
    conf = float(z * min(1.0, 2 * (z - z2) / max(z, 1e-6)))
    return k, conf


class MicBank:
    """Спектры файлов микрофона считаются один раз и переиспользуются для всех клипов."""

    def __init__(self, mics: list[MediaInfo], max_cam: float):
        self.items = []
        cam_n = int(min(max_cam, MAX_CAM_SPAN) * COARSE_SR) + COARSE_SR
        for m in mics:
            x = _prep(load_audio(m.path, COARSE_SR))
            n = sfft.next_fast_len(len(x) + cam_n, real=True)
            self.items.append((len(x), n, sfft.rfft(x, n, workers=-1)))

    def coarse(self, cam: np.ndarray) -> list[tuple[float, float]]:
        out = []
        for mlen, n, X in self.items:
            R = _phat(X * np.conj(sfft.rfft(cam, n, workers=-1)))
            corr = sfft.irfft(R, n, workers=-1)
            lags = np.arange(n)
            lags = np.where(lags > n - len(cam), lags - n, lags)
            min_ov = min(2 * COARSE_SR, len(cam) // 2)
            valid = (lags > -len(cam) + min_ov) & (lags < mlen - min_ov)
            k, conf = _peak(corr, valid, COARSE_SR)
            out.append((lags[k] / COARSE_SR, conf))
        return out


def _refine(video: MediaInfo, mic: MediaInfo, offset: float) -> float:
    span = min(40.0, video.duration)
    vs = max(0.0, video.duration / 2 - span / 2)
    cam = _prep(load_audio(video.path, FINE_SR, vs, span))
    ms = vs + offset - 0.5
    mic_x = _prep(load_audio(mic.path, FINE_SR, ms, span + 1.0))
    if len(cam) < FINE_SR // 2 or len(mic_x) < FINE_SR // 2:
        return offset
    n = sfft.next_fast_len(len(mic_x) + len(cam), real=True)
    corr = sfft.irfft(_phat(sfft.rfft(mic_x, n) * np.conj(sfft.rfft(cam, n))), n)
    lags = np.arange(n)
    lags = np.where(lags > n - len(cam), lags - n, lags)
    valid = np.abs(lags - int(0.5 * FINE_SR)) <= int(0.1 * FINE_SR)
    c = np.where(valid, corr, -np.inf)
    k = int(np.argmax(c))
    frac = 0.0
    if 0 < k < n - 1:
        y0, y1, y2 = corr[k - 1], corr[k], corr[k + 1]
        d = y0 - 2 * y1 + y2
        if abs(d) > 1e-12:
            frac = float(np.clip(0.5 * (y0 - y2) / d, -0.5, 0.5))
    return ms + (lags[k] + frac) / FINE_SR - vs


def sync_videos(videos: list[MediaInfo], mics: list[MediaInfo], progress=None, threshold: float = 7.0) -> list[SyncResult]:
    if not mics:
        return [SyncResult(None, 0.0, 0.0, False) for _ in videos]
    if progress:
        progress(0.0, L("Читаю звук с микрофона", "Reading microphone audio"))
    bank = MicBank(mics, max((v.duration for v in videos), default=60.0))
    done = [0]

    def one(v: MediaInfo) -> SyncResult:
        if not v.has_audio:
            return SyncResult(None, 0.0, 0.0, False)
        # для очень длинных клипов берём середину — этого с запасом хватает для поиска
        span = min(v.duration, MAX_CAM_SPAN)
        start = max(0.0, (v.duration - span) / 2)
        cam = _prep(load_audio(v.path, COARSE_SR, start, span))
        cands = bank.coarse(cam)
        best = int(np.argmax([c for _, c in cands]))
        off, conf = cands[best]
        off -= start
        ok = conf >= threshold
        if ok:
            try:
                off = _refine(v, mics[best], off)
            except Exception:  # noqa: BLE001
                pass
        done[0] += 1
        if progress:
            progress(done[0] / len(videos), L(f"Синхронизировано {done[0]} из {len(videos)}",
                                              f"Synced {done[0]} of {len(videos)}"))
        return SyncResult(best if ok else None, float(off), float(conf), ok)

    # FFT внутри уже многопоточный; 3 клипа параллельно — чтобы ffmpeg и FFT шли одновременно
    with ThreadPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(one, videos))
    return results
