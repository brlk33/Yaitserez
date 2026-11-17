"""Окно без системной рамки: перетаскивание, ресайз и разворот через Win32 (как в VoiceType)."""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

IS_WIN = sys.platform == "win32"


class WinCtl:
    def __init__(self):
        self.hwnd = None
        self.maxed = False
        self.normal = None
        if IS_WIN:
            self.u32 = ctypes.windll.user32
            self.u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                              ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            self.u32.SetWindowPos.restype = wintypes.BOOL

    def attach(self, hwnd: int) -> None:
        self.hwnd = hwnd
        self.corners(True)

    def corners(self, round_: bool) -> None:
        try:  # Windows 11: DWMWA_WINDOW_CORNER_PREFERENCE = 33; ROUND = 2, DONOTROUND = 1
            v = ctypes.c_int(2 if round_ else 1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(self.hwnd, 33, ctypes.byref(v), 4)
        except Exception:  # noqa: BLE001
            pass

    def _cursor(self):
        pt = wintypes.POINT()
        self.u32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def _rect(self):
        r = wintypes.RECT()
        self.u32.GetWindowRect(self.hwnd, ctypes.byref(r))
        return r.left, r.top, r.right, r.bottom

    def _down(self):
        vk = 0x02 if self.u32.GetSystemMetrics(23) else 0x01  # кнопки мыши поменяны местами
        return self.u32.GetAsyncKeyState(vk) & 0x8000

    def _set(self, x, y, w, h):
        self.u32.SetWindowPos(self.hwnd, 0, int(x), int(y), int(w), int(h), 0x0004 | 0x0010)

    def _scale(self):
        try:
            return self.u32.GetDpiForWindow(self.hwnd) / 96.0
        except Exception:  # noqa: BLE001
            return 1.0

    def _work_area(self):
        class MI(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
        mi = MI()
        mi.cbSize = ctypes.sizeof(MI)
        mon = self.u32.MonitorFromWindow(self.hwnd, 2)
        self.u32.GetMonitorInfoW(mon, ctypes.byref(mi))
        r = mi.rcWork
        return r.left, r.top, r.right, r.bottom

    def drag(self):
        if not self.hwnd:
            return
        cx, cy = self._cursor()
        l, t, r, b = self._rect()
        if self.maxed:
            nl, nt, nr, nb = self.normal
            w, h = nr - nl, nb - nt
            frac = (cx - l) / max(1, r - l)
            l = cx - int(w * frac)
            moved = False
            while self._down():
                x, y = self._cursor()
                if abs(x - cx) + abs(y - cy) > 6:
                    moved = True
                    break
                time.sleep(0.01)
            if not moved:
                return
            self.maxed = False
            self.corners(True)
            self._set(l, t, w, h)
        ox, oy = cx - l, cy - t
        while self._down():
            x, y = self._cursor()
            self.u32.SetWindowPos(self.hwnd, 0, x - ox, y - oy, 0, 0, 0x0001 | 0x0004 | 0x0010)
            time.sleep(0.006)

    def resize(self, edge: str):
        if not self.hwnd or self.maxed:
            return
        sx, sy = self._cursor()
        l, t, r, b = self._rect()
        sc = self._scale()
        mw, mh = int(860 * sc), int(600 * sc)
        while self._down():
            x, y = self._cursor()
            dx, dy = x - sx, y - sy
            L, T, R, B = l, t, r, b
            if "e" in edge:
                R = max(r + dx, l + mw)
            if "s" in edge:
                B = max(b + dy, t + mh)
            if "w" in edge:
                L = min(l + dx, r - mw)
            if "n" in edge:
                T = min(t + dy, b - mh)
            self._set(L, T, R - L, B - T)
            time.sleep(0.012)

    def toggle_max(self) -> bool:
        if not self.hwnd:
            return False
        if self.maxed:
            l, t, r, b = self.normal
            self.maxed = False
            self.corners(True)
            self._set(l, t, r - l, b - t)
        else:
            self.normal = self._rect()
            l, t, r, b = self._work_area()
            self.maxed = True
            self.corners(False)
            self._set(l, t, r - l, b - t)
        return self.maxed

    def minimize(self):
        if self.hwnd:
            self.u32.ShowWindow(self.hwnd, 6)  # SW_MINIMIZE


def native_hwnd(win, timeout=60) -> int:
    """HWND окна pywebview. Ждём before_show: чтение .Handle во время конструктора формы виснет."""
    if not win.events.before_show.wait(timeout):
        raise TimeoutError("window was not created in time")
    return int(str(win.native.Handle.ToInt64()))
