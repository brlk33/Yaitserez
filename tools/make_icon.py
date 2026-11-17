"""Логотип Яйцереза в стиле семейства «Яйца» (Яйцетаймер, Яйца Cloud):
скруглённый квадрат с диагональным градиентом и белое яйцо — здесь разрезанное яйцерезкой на дольки.

Пишет ui/logo.svg (для интерфейса), ui/logo.png (256 px) и ui/icon.ico (16–256 px).
Растеризация своя (numpy), чтобы не тянуть графические библиотеки.
"""
import math
import os
import struct
import zlib

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C1 = (74, 222, 156)    # верх-лево
C2 = (14, 157, 183)    # низ-право
RADIUS = 0.225         # скругление плашки
INSET = 0.035          # поля вокруг плашки
EGG_C = (0.5, 0.535)
EGG_A, EGG_B, EGG_K = 0.235, 0.315, 0.2   # полуширина, полувысота, сужение кверху
CUT_ANGLE = math.radians(-24)             # наклон проволок яйцерезки
CUTS = (0.47, 0.64)                       # где проволоки пересекают вертикаль x=0.5
CUT_W = 0.04
YOLK_C, YOLK_R = (0.5, 0.6), 0.0  # без желтка: на 16–38 px он сливался с разрезами в «6»


def egg_field(x, y):
    dy = (y - EGG_C[1]) / EGG_B
    dx = (x - EGG_C[0]) / (EGG_A * (1 + EGG_K * dy))
    return dx * dx + dy * dy  # <= 1 внутри


def cut_dist(x, y, cy):
    """Расстояние до наклонной линии разреза, проходящей через (0.5, cy)."""
    return (y - cy) * math.cos(CUT_ANGLE) - (x - 0.5) * math.sin(CUT_ANGLE)


def render(size: int, ss: int = 4) -> np.ndarray:
    n = size * ss
    y, x = (np.mgrid[0:n, 0:n].astype(np.float64) + 0.5) / n
    # плашка
    lo, hi = INSET, 1 - INSET
    qx = np.clip(np.maximum(lo + RADIUS - x, x - (hi - RADIUS)), 0, None)
    qy = np.clip(np.maximum(lo + RADIUS - y, y - (hi - RADIUS)), 0, None)
    tile = (np.hypot(qx, qy) <= RADIUS) & (x >= lo) & (x <= hi) & (y >= lo) & (y <= hi)
    g = np.clip(((x - lo) + (y - lo)) / (2 * (hi - lo)), 0, 1)[..., None]
    rgb = np.array(C1) * (1 - g) + np.array(C2) * g
    # яйцо с разрезами и желтком
    egg = egg_field(x, y) <= 1
    for cy in CUTS:
        egg &= np.abs(cut_dist(x, y, cy)) > CUT_W / 2
    yolk = np.hypot(x - YOLK_C[0], y - YOLK_C[1]) <= YOLK_R
    white = egg & ~yolk
    rgb = np.where(white[..., None], 255.0, rgb)
    img = np.zeros((n, n, 4))
    img[..., :3] = rgb
    img[..., 3] = tile * 255.0
    img = img.reshape(size, ss, size, ss, 4).mean(axis=(1, 3))
    a = img[..., 3:4]
    img[..., :3] = np.where(a > 0, img[..., :3] * 255 / np.maximum(a, 1e-6) * (a / 255), 0)
    # премультипликация обратно не нужна: усреднили цвет только по пикселям плашки
    col = np.zeros_like(img)
    num = (np.where(tile[..., None], np.concatenate([rgb, np.ones((n, n, 1)) * 255], -1), 0)
           .reshape(size, ss, size, ss, 4).sum(axis=(1, 3)))
    cnt = tile.reshape(size, ss, size, ss).sum(axis=(1, 3))[..., None]
    col[..., :3] = num[..., :3] / np.maximum(cnt, 1)
    col[..., 3] = cnt[..., 0] / (ss * ss) * 255
    return np.clip(col, 0, 255).astype(np.uint8)


def png(img: np.ndarray) -> bytes:
    h, w = img.shape[:2]
    raw = b"".join(b"\x00" + img[i].tobytes() for i in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def egg_path(scale=100) -> str:
    """Контур яйца для SVG — по той же формуле, что и растр."""
    pts = []
    for i in range(96):
        t = 2 * math.pi * i / 96
        # решаем egg_field = 1 вдоль луча из центра
        lo, hi = 0.0, 0.6
        for _ in range(40):
            mid = (lo + hi) / 2
            if egg_field(EGG_C[0] + mid * math.cos(t), EGG_C[1] + mid * math.sin(t)) <= 1:
                lo = mid
            else:
                hi = mid
        pts.append((EGG_C[0] + lo * math.cos(t), EGG_C[1] + lo * math.sin(t)))
    return "M" + " L".join(f"{px * scale:.2f} {py * scale:.2f}" for px, py in pts) + "Z"


def svg() -> str:
    s = 100
    deg = math.degrees(CUT_ANGLE)
    cuts = "".join(f'<rect x="-50" y="{(cy - CUT_W / 2) * s:.2f}" width="200" height="{CUT_W * s:.2f}" fill="#000" '
                   f'transform="rotate({deg:.2f} 50 {cy * s:.2f})"/>' for cy in CUTS)
    lo, side, r = INSET * s, (1 - 2 * INSET) * s, RADIUS * s
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        f'<defs><linearGradient id="yg" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="rgb{C1}"/><stop offset="1" stop-color="rgb{C2}"/></linearGradient>'
        f'<mask id="ym"><rect width="100" height="100" fill="#fff"/>{cuts}'
        '</mask></defs>'
        f'<rect x="{lo}" y="{lo}" width="{side}" height="{side}" rx="{r}" fill="url(#yg)"/>'
        f'<path d="{egg_path()}" fill="#fff" mask="url(#ym)"/></svg>'
    )


def main():
    ui = os.path.join(ROOT, "ui")
    with open(os.path.join(ui, "logo.svg"), "w", encoding="utf-8") as f:
        f.write(svg())
    with open(os.path.join(ui, "logo.png"), "wb") as f:
        f.write(png(render(256)))
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    blobs = [png(render(sz, 8 if sz <= 48 else 4)) for sz in sizes]
    out = struct.pack("<HHH", 0, 1, len(sizes))
    off = 6 + 16 * len(sizes)
    for sz, b in zip(sizes, blobs):
        out += struct.pack("<BBBBHHII", sz % 256, sz % 256, 0, 0, 1, 32, len(b), off)
        off += len(b)
    with open(os.path.join(ui, "icon.ico"), "wb") as f:
        f.write(out + b"".join(blobs))
    print("ok")


if __name__ == "__main__":
    main()
