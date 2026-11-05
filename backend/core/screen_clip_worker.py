"""Isolated PerMonitorV2 physical-pixel screen region snipping worker (AV-clean, zero clipboard, stdout PNG)."""

from __future__ import annotations

import ctypes
import io
import sys
from typing import Any

from PIL import Image, ImageDraw

SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
TK_SHIFT_MASK = 0x0001


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


def _virtual_desktop_bounds(frozen_size: tuple[int, int]) -> tuple[int, int, int, int, int]:
    if sys.platform != "win32":
        return (0, 0, frozen_size[0], frozen_size[1], frozen_size[0])
    user32 = ctypes.windll.user32
    vx = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
    vy = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
    vw = max(1, int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)))
    vh = max(1, int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)))
    pw = max(1, int(user32.GetSystemMetrics(SM_CXSCREEN)))
    return (vx, vy, vw, vh, pw)


def _run_interactive_clip() -> int:
    _enable_per_monitor_v2_dpi()
    from PIL import ImageEnhance, ImageGrab, ImageTk
    import tkinter as tk

    frozen = ImageGrab.grab(all_screens=True).convert("RGBA")
    vx, vy, vw, vh, primary_w = _virtual_desktop_bounds(frozen.size)
    if frozen.size != (vw, vh):
        frozen = frozen.resize((vw, vh), Image.Resampling.BILINEAR)
    dimmed = ImageEnhance.Brightness(frozen.convert("RGB")).enhance(0.45)

    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.maxsize(max(16384, vw), max(16384, vh))
    root.geometry(f"{vw}x{vh}+{vx}+{vy}")
    root.configure(bg="#000000", cursor="crosshair")

    dim_tk = ImageTk.PhotoImage(dimmed)
    cv = tk.Canvas(root, width=vw, height=vh, highlightthickness=0, bd=0, bg="#000000", cursor="crosshair")
    cv.pack(fill="both", expand=True)
    cv.create_image(0, 0, image=dim_tk, anchor="nw")

    state: dict[str, Any] = {
        "dragging": False,
        "shift": False,
        "start": (0, 0),
        "current": (0, 0),
        "accepted": None,
        "cancelled": True,
        "live_tk": None,
    }

    def _close_all(cancel: bool, rect: tuple[int, int, int, int] | None = None) -> None:
        state["cancelled"] = cancel
        state["accepted"] = rect
        try:
            root.quit()
        except Exception:
            pass

    def _repaint() -> None:
        shift_lock = bool(state["shift"])
        sel = _compute_selection_rect(state["start"], state["current"], shift_lock) if state["dragging"] else (0, 0, 0, 0)
        sx, sy, sw, sh = sel
        cv.delete("overlay")

        if not state["dragging"] or sw < 2 or sh < 2:
            msg = "DF11 Studio · Arrastra para recortar  |  Shift = Proporción 260×310  |  Esc = Cancelar"
            banner_cx = max(300.0, min(float(vw - 300), float(-vx) + primary_w * 0.5))
            banner_top = max(18.0, float(-vy) + 18.0)
            cv.create_rectangle(
                banner_cx - 290,
                banner_top,
                banner_cx + 290,
                banner_top + 30,
                fill="#090d16",
                outline="#10b981",
                width=1,
                tags="overlay",
            )
            cv.create_text(banner_cx, banner_top + 15, text=msg, fill="#f1f5f9", font=("Segoe UI", 9, "bold"), tags="overlay")
            return

        lx0, ly0 = sx - vx, sy - vy
        lx1, ly1 = lx0 + sw, ly0 + sh
        ix0, iy0 = max(0, lx0), max(0, ly0)
        ix1, iy1 = min(vw, lx1), min(vh, ly1)
        if ix1 > ix0 and iy1 > iy0:
            bright_crop = frozen.crop((ix0, iy0, ix1, iy1))
            state["live_tk"] = ImageTk.PhotoImage(bright_crop)
            cv.create_image(ix0, iy0, image=state["live_tk"], anchor="nw", tags="overlay")

        cv.create_rectangle(lx0, ly0, lx1, ly1, outline="#10b981", width=2, tags="overlay")
        if shift_lock and sh >= 40:
            crown_y = ly0 + round(sh * (21.0 / 310.0))
            eyes_y = ly0 + round(sh * (113.0 / 310.0))
            cv.create_line(lx0 + 4, crown_y, lx1 - 4, crown_y, fill="#38bdf8", dash=(4, 3), tags="overlay")
            cv.create_line(lx0 + 4, eyes_y, lx1 - 4, eyes_y, fill="#38bdf8", dash=(4, 3), tags="overlay")

        min_side = min(sw, sh)
        qual = "Óptimo" if min_side >= 200 else ("Media" if min_side >= 125 else "Baja res.")
        accent = "#10b981" if min_side >= 200 else ("#f59e0b" if min_side >= 125 else "#f43f5e")
        label = f"{sw} × {sh} px · {qual}{' · DF11' if shift_lock else ''}"
        bx = max(6, min(vw - 210, lx0))
        by = ly0 - 28 if ly0 >= 34 else min(vh - 30, ly1 + 6)
        bw = max(148, len(label) * 7 + 16)
        cv.create_rectangle(bx, by, bx + bw, by + 22, fill="#090d16", outline=accent, width=1, tags="overlay")
        cv.create_text(bx + 8, by + 11, text=label, fill=accent, anchor="w", font=("Consolas", 9, "bold"), tags="overlay")

    def _pt_from_event(ev: Any) -> tuple[int, int]:
        xr = getattr(ev, "x_root", None)
        yr = getattr(ev, "y_root", None)
        if xr is not None and yr is not None:
            return (int(xr), int(yr))
        px, py = root.winfo_pointerxy()
        return (int(px), int(py))

    def _sync_shift_from_event(ev: Any) -> None:
        raw_state = getattr(ev, "state", None)
        if isinstance(raw_state, int):
            state["shift"] = bool(raw_state & TK_SHIFT_MASK)

    def _on_down(ev: Any) -> None:
        _sync_shift_from_event(ev)
        pt = _pt_from_event(ev)
        state["dragging"] = True
        state["start"] = pt
        state["current"] = pt
        _repaint()

    def _on_move(ev: Any) -> None:
        if state["dragging"]:
            _sync_shift_from_event(ev)
            state["current"] = _pt_from_event(ev)
            _repaint()

    def _on_up(ev: Any) -> None:
        if not state["dragging"]:
            return
        _sync_shift_from_event(ev)
        state["current"] = _pt_from_event(ev)
        sel = _compute_selection_rect(state["start"], state["current"], bool(state["shift"]))
        state["dragging"] = False
        if sel[2] >= 10 and sel[3] >= 10:
            _close_all(False, sel)
        else:
            _repaint()

    def _on_shift_press(_ev: Any) -> None:
        if not state["shift"]:
            state["shift"] = True
            if state["dragging"]:
                _repaint()

    def _on_shift_release(_ev: Any) -> None:
        if state["shift"]:
            state["shift"] = False
            if state["dragging"]:
                _repaint()

    def _on_cancel(_ev: Any = None) -> None:
        _close_all(True, None)

    for widget in (root, cv):
        widget.bind("<Escape>", _on_cancel)
        widget.bind("<Button-3>", _on_cancel)
        widget.bind("<KeyPress-Shift_L>", _on_shift_press)
        widget.bind("<KeyPress-Shift_R>", _on_shift_press)
        widget.bind("<KeyRelease-Shift_L>", _on_shift_release)
        widget.bind("<KeyRelease-Shift_R>", _on_shift_release)
    cv.bind("<ButtonPress-1>", _on_down)
    cv.bind("<B1-Motion>", _on_move)
    cv.bind("<ButtonRelease-1>", _on_up)

    root.deiconify()
    root.focus_force()
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
