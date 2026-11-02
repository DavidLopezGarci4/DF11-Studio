"""Fast (<0.5s) native desktop launcher for DF11 Face Studio via pywebview WebView2."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

WINDOW_TITLE = "DF11 Face Studio — FM27 & NG_Regens"


def _bind_win32_app_identity_and_icon(ico_path: Path) -> None:
    if sys.platform != "win32" or not ico_path.is_file():
        return
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if hwnd:
            lr_loadfromfile, image_icon, wm_seticon = 0x0010, 1, 0x0080
            small = user32.LoadImageW(None, str(ico_path), image_icon, 16, 16, lr_loadfromfile)
            big = user32.LoadImageW(None, str(ico_path), image_icon, 48, 48, lr_loadfromfile)
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
    os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", str(profile_dir))

    import webview

    bridge = StudioBridge()
    dist_index = WORKSPACE_ROOT / "frontend" / "dist" / "index.html"
    url = str(dist_index) if dist_index.is_file() else "http://localhost:5173"
    win = webview.create_window(
        title=WINDOW_TITLE,
        url=url,
        js_api=bridge,
        width=1140,
        height=760,
        min_size=(940, 640),
        background_color="#090d16",
    )
    bridge._attach_window(win)
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
