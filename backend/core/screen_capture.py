"""Zero-clipboard, AV-clean PerMonitorV2 screen region capture and optional Win32 hotkey listener."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image

from backend.core.image_guard import load_guarded_image
from backend.core.paths import WORKSPACE_ROOT

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_X = 0x58
HOTKEY_ID = 0xDF11
DWM_HIDE_SETTLE_SECONDS = 0.26


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
    """Build child command using the PSF Authenticode-signed GUI Python interpreter (pythonw.exe)."""
    exe = Path(sys.executable)
    if sys.platform == "win32":
        gui_sib = exe.with_name("pythonw.exe")
        if gui_sib.is_file():
            exe = gui_sib
    return [str(exe), "-m", "backend.core.screen_clip_worker"]


def _hide_windows_for_capture(windows: list[Any]) -> list[Any]:
    hidden: list[Any] = []
    for win in windows:
        if win is None or not hasattr(win, "hide"):
            continue
        try:
            win.hide()
            hidden.append(win)
        except Exception:
            pass
    if hidden:
        if sys.platform == "win32":
            try:
                ctypes.windll.dwmapi.DwmFlush()
            except Exception:
                pass
        time.sleep(DWM_HIDE_SETTLE_SECONDS)
    return hidden


def _restore_windows_after_capture(hidden_windows: list[Any]) -> None:
    for win in hidden_windows:
        try:
            if hasattr(win, "show"):
                win.show()
        except Exception:
            pass


def capture_screen_png(
    clipper_cmd: list[str] | None = None,
    host_window: Any = None,
    extra_windows: list[Any] | None = None,
    restore_after: bool = True,
) -> ScreenCaptureResult | None:
    """Launch PSF-signed PerMonitorV2 screen_clip_worker after DWM finishes hiding app windows."""
    cmd = [*(clipper_cmd or get_screen_clipper_cmd()), "--watch-stdin"]
    all_wins = [w for w in [host_window, *(extra_windows or [])] if w is not None]
    hidden_wins = _hide_windows_for_capture(all_wins)
    proc: subprocess.Popen[bytes] | None = None
    timed_out = threading.Event()
    watchdog: threading.Timer | None = None
    stdout_bytes = b""
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(WORKSPACE_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        watchdog = threading.Timer(300.0, lambda: (timed_out.set(), proc.kill()))
        watchdog.daemon = True
        watchdog.start()
        if proc.stdout is not None:
            stdout_bytes = proc.stdout.read()
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        if proc is not None:
            proc.kill()
        return None
    finally:
        if watchdog is not None:
            watchdog.cancel()
        if proc is not None and proc.stdin is not None:
            try:
                proc.stdin.close()
            except Exception:
                pass
        if restore_after:
            _restore_windows_after_capture(hidden_wins)

    if timed_out.is_set() or proc is None or proc.returncode == 1 or not stdout_bytes:
        return None
    if proc.returncode != 0:
        raise RuntimeError("El capturador nativo de pantalla devolvió un error inesperado.")

    guarded = load_guarded_image(stdout_bytes)
    w, h = guarded.original_size
    drm_warn = detect_drm_black_frame(guarded.image)
    low_res = bool(min(w, h) < 150)
    return ScreenCaptureResult(
        png_bytes=stdout_bytes,
        width=w,
        height=h,
        drm_black_warning=drm_warn,
        low_res_warning=low_res,
    )


class GlobalCaptureHotkey:
    """Optional non-intrusive Win32 shortcut (Ctrl+Shift+X) via standard RegisterHotKey."""

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
        msg = wintypes.MSG()
        # Force Win32 thread message queue creation before exposing _thread_id / _ready to stop()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        self._thread_id = int(kernel32.GetCurrentThreadId())
        ok = bool(user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_X))
        self._registered = ok
        self._ready.set()
        if not ok:
            return
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    threading.Thread(target=self._on_trigger, daemon=True).start()
        finally:
            try:
                user32.UnregisterHotKey(None, HOTKEY_ID)
            except Exception:
                pass
            self._registered = False
