"""Fast (<0.5s) native desktop launcher for DF11 Face Studio via pywebview WebView2."""

from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    from backend.bridge import StudioBridge
    from backend.core.paths import WORKSPACE_ROOT, get_webview_profile_dir

    profile_dir = get_webview_profile_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", str(profile_dir))

    import webview

    bridge = StudioBridge()
    dist_index = WORKSPACE_ROOT / "frontend" / "dist" / "index.html"
    url = str(dist_index) if dist_index.is_file() else "http://localhost:5173"
    win = webview.create_window(
        title="DF11 Face Studio — FM27 & NG_Regens",
        url=url,
        js_api=bridge,
        width=1140,
        height=760,
        min_size=(940, 640),
        background_color="#090d16",
    )
    bridge.attach_window(win)
    webview.start(func=bridge.warmup_vision_async, debug=False)


if __name__ == "__main__":
    main()
