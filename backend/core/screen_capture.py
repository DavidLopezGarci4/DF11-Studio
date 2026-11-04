"""Zero-clipboard, PerMonitorV2 native screen region capture and optional Win32 hotkey listener."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from backend.core.image_guard import load_guarded_image
from backend.core.paths import WORKSPACE_ROOT

WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011
SW_HIDE = 0
SW_SHOW = 5
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_X = 0x58
HOTKEY_ID = 0xDF11


@dataclass(frozen=True, slots=True)
class ScreenCaptureResult:
    """Validated lossless PNG screen crop kept strictly in RAM."""

    png_bytes: bytes
    width: int
    height: int
    drm_black_warning: bool
    low_res_warning: bool


def detect_drm_black_frame(img_rgba: Image.Image) -> bool:
    """Detect hardware DRM blackout (e.g. Widevine/PlayReady) in the inner 80% ROI without blocking black kits."""
    arr = np.asarray(img_rgba.convert("RGBA"), dtype=np.uint8)
    h, w = arr.shape[:2]
    if h < 16 or w < 16:
        return False
    y0, y1 = max(0, int(h * 0.10)), min(h, int(h * 0.90))
    x0, x1 = max(0, int(w * 0.10)), min(w, int(w * 0.90))
    roi = arr[y0:y1, x0:x1, :3].astype(np.float32)
    if roi.size == 0:
        return False
    luma = 0.2126 * roi[:, :, 0] + 0.7152 * roi[:, :, 1] + 0.0722 * roi[:, :, 2]
    p92 = float(np.percentile(luma, 92))
    std_l = float(np.std(luma))
    return bool(p92 < 18.0 and std_l < 2.2)


def get_screen_clipper_cmd() -> list[str]:
    """Build isolated child command using the signed venv Python interpreter (zero AV false positives)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        console_sib = exe.with_name("python.exe")
        if console_sib.is_file():
            exe = console_sib
    return [str(exe), "-m", "backend.core.screen_clip_worker"]


def _exclude_hwnd_from_capture(hwnd: int | None) -> tuple[bool, bool]:
    """Exclude host window in 0ms via WDA_EXCLUDEFROMCAPTURE, falling back to SW_HIDE + DwmFlush if unsupported."""
    if sys.platform != "win32" or not hwnd:
        return (False, False)
    try:
        user32 = ctypes.windll.user32
        if user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), wintypes.DWORD(WDA_EXCLUDEFROMCAPTURE)):
            try:
                ctypes.windll.dwmapi.DwmFlush()
            except Exception:
                pass
            return (True, False)
        user32.ShowWindow(wintypes.HWND(hwnd), SW_HIDE)
        try:
            ctypes.windll.dwmapi.DwmFlush()
        except Exception:
            time.sleep(0.04)
        return (False, True)
    except Exception:
        return (False, False)


def _restore_hwnd_after_capture(hwnd: int | None, used_affinity: bool, used_hide: bool) -> None:
    if sys.platform != "win32" or not hwnd:
        return
    try:
        user32 = ctypes.windll.user32
        if used_affinity:
            user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), wintypes.DWORD(WDA_NONE))
        if used_hide:
            user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOW)
        user32.SetForegroundWindow(wintypes.HWND(hwnd))
    except Exception:
        pass


def capture_screen_png(
    hwnd: int | None = None,
    clipper_cmd: list[str] | None = None,
) -> ScreenCaptureResult | None:
    """Launch isolated PerMonitorV2 screen_clip_worker and read lossless PNG bytes from stdout."""
    cmd = clipper_cmd or get_screen_clipper_cmd()
    used_affinity, used_hide = _exclude_hwnd_from_capture(hwnd)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            timeout=180,
            check=False,
            creationflags=creationflags,
        )
    finally:
        _restore_hwnd_after_capture(hwnd, used_affinity, used_hide)

    if proc.returncode == 1 or not proc.stdout:
        return None
    if proc.returncode != 0:
        raise RuntimeError("El capturador nativo de pantalla devolvió un error inesperado.")

    guarded = load_guarded_image(proc.stdout)
    w, h = guarded.original_size
    drm_warn = detect_drm_black_frame(guarded.image)
    low_res = bool(min(w, h) < 150)
    return ScreenCaptureResult(
        png_bytes=proc.stdout,
        width=w,
        height=h,
        drm_black_warning=drm_warn,
        low_res_warning=low_res,
    )


class GlobalCaptureHotkey:
    """Optional non-intrusive Win32 hotkey (Ctrl+Shift+X) message loop."""

    def __init__(self, on_trigger: Callable[[], None]) -> None:
        self._on_trigger = on_trigger
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._thread_id: int = 0
        self._ready = threading.Event()
        self._registered = False

    @property
    def is_running(self) -> bool:
        return self._registered and self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if sys.platform != "win32":
            return False
        with self._lock:
            if self.is_running:
                return True
            self._ready.clear()
            self._registered = False
            t = threading.Thread(target=self._loop, name="df11-capture-hotkey", daemon=True)
            self._thread = t
            t.start()
        self._ready.wait(timeout=1.5)
        return self.is_running

    def stop(self) -> None:
        with self._lock:
            tid = self._thread_id
            t = self._thread
            self._thread = None
            self._thread_id = 0
            self._registered = False
        if sys.platform == "win32" and tid:
            try:
                ctypes.windll.user32.PostThreadMessageW(wintypes.DWORD(tid), WM_QUIT, 0, 0)
            except Exception:
                pass
        if t is not None and t.is_alive():
            t.join(timeout=1.0)

    def _loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = int(kernel32.GetCurrentThreadId())
        ok = bool(user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_X))
        self._registered = ok
        self._ready.set()
        if not ok:
            return
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    threading.Thread(target=self._on_trigger, daemon=True).start()
        finally:
            try:
                user32.UnregisterHotKey(None, HOTKEY_ID)
            except Exception:
                pass
            self._registered = False
