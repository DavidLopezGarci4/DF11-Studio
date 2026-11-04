"""Isolated PerMonitorV2 physical-pixel screen region snipping worker (zero clipboard, stdout PNG)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import io
import sys
from typing import Any

from PIL import Image, ImageDraw

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
VK_SHIFT = 0x10


def _enable_per_monitor_v2_dpi() -> None:
    if sys.platform != "win32":
        return
    user32 = ctypes.windll.user32
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def _enum_monitor_rects(vx: int, vy: int, vw: int, vh: int) -> list[tuple[int, int, int, int]]:
    if sys.platform != "win32":
        return [(vx, vy, vw, vh)]
    rects: list[tuple[int, int, int, int]] = []
    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    def _cb(_hmon: int, _hdc: int, lprect: Any, _lparam: int) -> int:
        r = lprect.contents
        w, h = int(r.right - r.left), int(r.bottom - r.top)
        if w > 0 and h > 0:
            rects.append((int(r.left), int(r.top), w, h))
        return 1

    try:
        ctypes.windll.user32.EnumDisplayMonitors(None, None, MonitorEnumProc(_cb), 0)
    except Exception:
        pass
    return rects or [(vx, vy, vw, vh)]


def _cursor_screen_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def _is_shift_down() -> bool:
    if sys.platform != "win32":
        return False
    return bool(ctypes.windll.user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)


def _write_png_stdout(im: Image.Image) -> None:
    buf = io.BytesIO()
    im.save(buf, format="PNG", compress_level=3)
    out = sys.stdout.buffer
    out.write(buf.getvalue())
    out.flush()


def _run_self_test() -> int:
    im = Image.new("RGBA", (64, 64), (9, 13, 22, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([16, 16, 47, 47], fill=(16, 185, 129, 255))
    _write_png_stdout(im)
    return 0


def _compute_selection_rect(
    start_pt: tuple[int, int],
    cur_pt: tuple[int, int],
    lock_df11_aspect: bool,
) -> tuple[int, int, int, int]:
    dx = cur_pt[0] - start_pt[0]
    dy = cur_pt[1] - start_pt[1]
    if lock_df11_aspect and (abs(dx) > 2 or abs(dy) > 2):
        sx = 1 if dx >= 0 else -1
        sy = 1 if dy >= 0 else -1
        w = float(abs(dx))
        h = float(abs(dy))
        ratio = 260.0 / 310.0
        if w / max(h, 1.0) > ratio:
            h = round(w / ratio)
        else:
            w = round(h * ratio)
        dx = sx * int(w)
        dy = sy * int(h)
    x0 = min(start_pt[0], start_pt[0] + dx)
    y0 = min(start_pt[1], start_pt[1] + dy)
    return (x0, y0, abs(dx), abs(dy))


def _run_interactive_clip() -> int:
    _enable_per_monitor_v2_dpi()
    from PIL import ImageEnhance, ImageGrab, ImageTk
    import tkinter as tk

    user32 = ctypes.windll.user32
    vx = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
    vy = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
    vw = max(1, int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)))
    vh = max(1, int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)))

    frozen = ImageGrab.grab(all_screens=True).convert("RGBA")
    if frozen.size != (vw, vh):
        frozen = frozen.resize((vw, vh), Image.Resampling.BILINEAR)
    dimmed = ImageEnhance.Brightness(frozen.convert("RGB")).enhance(0.45)
    monitors = _enum_monitor_rects(vx, vy, vw, vh)

    root = tk.Tk()
    root.withdraw()

    state: dict[str, Any] = {
        "dragging": False,
        "start": (0, 0),
        "current": (0, 0),
        "accepted": None,
        "cancelled": True,
    }
    views: list[dict[str, Any]] = []

    def _close_all(cancel: bool, rect: tuple[int, int, int, int] | None = None) -> None:
        state["cancelled"] = cancel
        state["accepted"] = rect
        try:
            root.quit()
        except Exception:
            pass

    def _repaint() -> None:
        shift_lock = _is_shift_down()
        sel = _compute_selection_rect(state["start"], state["current"], shift_lock) if state["dragging"] else (0, 0, 0, 0)
        sx, sy, sw, sh = sel
        cur_x, cur_y = state["current"] if state["dragging"] else _cursor_screen_pos()

        for v in views:
            cv: tk.Canvas = v["canvas"]
            mx, my, mw, mh = v["rect"]
            cv.delete("overlay")
            if not state["dragging"] or sw < 2 or sh < 2:
                if mx <= cur_x < mx + mw and my <= cur_y < my + mh:
                    msg = "DF11 Studio · Arrastra para recortar  |  Shift = Proporción 260×310  |  Esc = Cancelar"
                    cx = mw * 0.5
                    cv.create_rectangle(cx - 290, 18, cx + 290, 48, fill="#090d16", outline="#10b981", width=1, tags="overlay")
                    cv.create_text(cx, 33, text=msg, fill="#f1f5f9", font=("Segoe UI", 9, "bold"), tags="overlay")
                continue

            lx0, ly0 = sx - mx, sy - my
            lx1, ly1 = lx0 + sw, ly0 + sh
            ix0, iy0 = max(0, lx0), max(0, ly0)
            ix1, iy1 = min(mw, lx1), min(mh, ly1)
            if ix1 > ix0 and iy1 > iy0:
                bright_crop = v["bright_pil"].crop((ix0, iy0, ix1, iy1))
                v["live_tk"] = ImageTk.PhotoImage(bright_crop)
                cv.create_image(ix0, iy0, image=v["live_tk"], anchor="nw", tags="overlay")

            cv.create_rectangle(lx0, ly0, lx1, ly1, outline="#10b981", width=2, tags="overlay")
            if shift_lock and sh >= 40:
                crown_y = ly0 + round(sh * (21.0 / 310.0))
                eyes_y = ly0 + round(sh * (113.0 / 310.0))
                cv.create_line(lx0 + 4, crown_y, lx1 - 4, crown_y, fill="#38bdf8", dash=(4, 3), tags="overlay")
                cv.create_line(lx0 + 4, eyes_y, lx1 - 4, eyes_y, fill="#38bdf8", dash=(4, 3), tags="overlay")

            if mx <= cur_x < mx + mw and my <= cur_y < my + mh:
                min_side = min(sw, sh)
                qual = "Óptimo" if min_side >= 200 else ("Media" if min_side >= 125 else "Baja res.")
                accent = "#10b981" if min_side >= 200 else ("#f59e0b" if min_side >= 125 else "#f43f5e")
                label = f"{sw} × {sh} px · {qual}{' · DF11' if shift_lock else ''}"
                bx = max(6, min(mw - 210, lx0))
                by = ly0 - 28 if ly0 >= 34 else min(mh - 30, ly1 + 6)
                bw = max(148, len(label) * 7 + 16)
                cv.create_rectangle(bx, by, bx + bw, by + 22, fill="#090d16", outline=accent, width=1, tags="overlay")
                cv.create_text(bx + 8, by + 11, text=label, fill=accent, anchor="w", font=("Consolas", 9, "bold"), tags="overlay")

    def _on_down(_ev: Any) -> None:
        pt = _cursor_screen_pos()
        state["dragging"] = True
        state["start"] = pt
        state["current"] = pt
        _repaint()

    def _on_move(_ev: Any) -> None:
        if state["dragging"]:
            state["current"] = _cursor_screen_pos()
            _repaint()

    def _on_up(_ev: Any) -> None:
        if not state["dragging"]:
            return
        state["current"] = _cursor_screen_pos()
        sel = _compute_selection_rect(state["start"], state["current"], _is_shift_down())
        state["dragging"] = False
        if sel[2] >= 10 and sel[3] >= 10:
            _close_all(False, sel)
        else:
            _repaint()

    def _on_cancel(_ev: Any = None) -> None:
        _close_all(True, None)

    for mx, my, mw, mh in monitors:
        top = tk.Toplevel(root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.geometry(f"{mw}x{mh}+{mx}+{my}")
        top.configure(bg="#000000", cursor="crosshair")

        sx0, sy0 = max(0, mx - vx), max(0, my - vy)
        bright_slice = frozen.crop((sx0, sy0, min(vw, sx0 + mw), min(vh, sy0 + mh)))
        dim_slice = dimmed.crop((sx0, sy0, min(vw, sx0 + mw), min(vh, sy0 + mh)))
        dim_tk = ImageTk.PhotoImage(dim_slice)

        cv = tk.Canvas(top, width=mw, height=mh, highlightthickness=0, bd=0, bg="#000000", cursor="crosshair")
        cv.pack(fill="both", expand=True)
        cv.create_image(0, 0, image=dim_tk, anchor="nw")

        for widget in (top, cv):
            widget.bind("<Escape>", _on_cancel)
            widget.bind("<Button-3>", _on_cancel)
            widget.bind("<KeyPress>", lambda _e: _repaint() if state["dragging"] else None)
            widget.bind("<KeyRelease>", lambda _e: _repaint() if state["dragging"] else None)
        cv.bind("<ButtonPress-1>", _on_down)
        cv.bind("<B1-Motion>", _on_move)
        cv.bind("<ButtonRelease-1>", _on_up)

        views.append({"top": top, "canvas": cv, "rect": (mx, my, mw, mh), "bright_pil": bright_slice, "dim_tk": dim_tk, "live_tk": None})

    if views:
        views[0]["top"].focus_force()
        _repaint()

    root.mainloop()
    try:
        root.destroy()
    except Exception:
        pass

    rect = state["accepted"]
    if state["cancelled"] or not rect:
        return 1
    rx, ry, rw, rh = rect
    cx0 = max(0, rx - vx)
    cy0 = max(0, ry - vy)
    cx1 = min(vw, rx - vx + rw)
    cy1 = min(vh, ry - vy + rh)
    if cx1 - cx0 < 4 or cy1 - cy0 < 4:
        return 1
    cropped = frozen.crop((cx0, cy0, cx1, cy1))
    _write_png_stdout(cropped)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if any(a.lower() == "--self-test" for a in args):
        return _run_self_test()
    try:
        return _run_interactive_clip()
    except Exception:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
