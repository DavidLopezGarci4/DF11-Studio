"""Fast (<0.5s) native desktop launcher for DF11 Face Studio via pywebview WebView2."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

WINDOW_TITLE = "DF11 Face Studio — FM27 & NG_Regens"


def _win32_user32() -> Any:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM
    return user32


def _is_webview_lock_held(profile_dir: Path) -> bool:
    lock_path = profile_dir / "EBWebView" / "lockfile"
    if not lock_path.exists():
        return False
    try:
        with open(lock_path, "rb"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def _cleanup_stale_instance(profile_dir: Path) -> None:
    """Close or evict any lingering previous DF11 Face Studio instance so WebView2 & state stay fresh."""
    if sys.platform != "win32":
        return
    try:
        user32 = _win32_user32()
        wm_close = 0x0010
        my_pid = os.getpid()
        stale_pids: set[int] = set()

        hwnd = int(user32.FindWindowW(None, WINDOW_TITLE) or 0)
        if hwnd:
            pid_val = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_val))
            if pid_val.value and int(pid_val.value) != my_pid:
                stale_pids.add(int(pid_val.value))
            user32.PostMessageW(hwnd, wm_close, 0, 0)

        if not stale_pids:
            return

        deadline = time.perf_counter() + 1.8
        while time.perf_counter() < deadline:
            if not _is_webview_lock_held(profile_dir) and int(user32.FindWindowW(None, WINDOW_TITLE) or 0) == 0:
                return
            time.sleep(0.05)

        for pid in stale_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

        deadline2 = time.perf_counter() + 1.2
        while time.perf_counter() < deadline2 and _is_webview_lock_held(profile_dir):
            time.sleep(0.05)
    except Exception:
        pass


def _bind_win32_app_identity_and_icon(ico_path: Path) -> None:
    if sys.platform != "win32" or not ico_path.is_file():
        return
    try:
        user32 = _win32_user32()
        hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if hwnd:
            lr_flags, image_icon, wm_seticon = 0x0010 | 0x8000, 1, 0x0080  # LR_LOADFROMFILE | LR_SHARED
            small = user32.LoadImageW(None, str(ico_path), image_icon, 16, 16, lr_flags)
            big = user32.LoadImageW(None, str(ico_path), image_icon, 48, 48, lr_flags)
            if small:
                user32.SendMessageW(hwnd, wm_seticon, 0, small)
            if big:
                user32.SendMessageW(hwnd, wm_seticon, 1, big)
    except Exception:
        pass


def main() -> None:
    from backend.bridge import StudioBridge
    from backend.core.paths import ASSETS_DIR, WORKSPACE_ROOT, get_webview_profile_dir

    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DF11FaceStudio.Desktop.1.0")
        except Exception:
            pass

    profile_dir = get_webview_profile_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_stale_instance(profile_dir)
    os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", str(profile_dir))

    import webview

    bridge = StudioBridge()
    dist_index = WORKSPACE_ROOT / "frontend" / "dist" / "index.html"
    url = str(dist_index) if dist_index.is_file() else "http://localhost:5173"
    win = webview.create_window(
        title=WINDOW_TITLE,
        url=url,
        js_api=bridge,
        width=1360,
        height=840,
        min_size=(980, 680),
        background_color="#090d16",
    )
    bridge._attach_window(win)

    def _on_main_window_closed() -> None:
        bridge._shutdown_windows()
        exit_timer = threading.Timer(0.8, os._exit, args=(0,))
        exit_timer.daemon = True
        exit_timer.start()

    win.events.closed += _on_main_window_closed
    ico_path = ASSETS_DIR / "icons" / "app.ico"
    win.events.shown += lambda: _bind_win32_app_identity_and_icon(ico_path)
    webview.start(
        func=bridge.warmup_vision_async,
        debug=False,
        private_mode=False,
        storage_path=str(profile_dir),
    )


if __name__ == "__main__":
    main()
