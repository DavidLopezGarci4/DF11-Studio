"""Isolated PerMonitorV2 physical-pixel screen region snipping worker (AV-clean, zero clipboard, stdout PNG)."""

from __future__ import annotations

import ctypes
import io
import sys
import time
from typing import Any

from PIL import Image, ImageDraw

SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
TK_SHIFT_MASK = 0x0001
DRAG_THRESHOLD_PX = 5
MIN_COMMIT_PX = 10
SHIFT_RELEASE_GRACE_SEC = 0.090


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


class _ClipStateController:
    """Pure, deterministic state machine for two-stage screen snipping (Select -> Re-drag -> Intro/Esc)."""

    def __init__(self) -> None:
        self.pending_press: bool = False
        self.dragging: bool = False
        self.shift: bool = False
        self.shift_released_at: float = 0.0
        self.last_shift_move_pt: tuple[int, int] = (0, 0)
        self.start: tuple[int, int] = (0, 0)
        self.current: tuple[int, int] = (0, 0)
        self.committed_sel: tuple[int, int, int, int] | None = None
        self.committed_df11_lock: bool = False
        self.accepted: tuple[int, int, int, int] | None = None
        self.cancelled: bool = True
        self.closed: bool = False

    def _effective_drag_shift(self, pt: tuple[int, int], now: float | None = None) -> bool:
        if self.shift:
            return True
        if self.shift_released_at <= 0.0:
            return False
        t_now = time.perf_counter() if now is None else float(now)
        cheb = max(abs(pt[0] - self.last_shift_move_pt[0]), abs(pt[1] - self.last_shift_move_pt[1]))
        return bool((t_now - self.shift_released_at) <= SHIFT_RELEASE_GRACE_SEC and cheb <= 2)

    def on_down(self, pt: tuple[int, int], shift: bool | None = None, now: float | None = None) -> None:
        if shift is not None:
            self.set_shift(bool(shift), now=now)
        self.pending_press = True
        self.dragging = False
        self.start = (int(pt[0]), int(pt[1]))
        self.current = self.start
        if self.shift:
            self.last_shift_move_pt = self.start

    def on_move(self, pt: tuple[int, int], shift: bool | None = None, now: float | None = None) -> bool:
        if not self.pending_press and not self.dragging:
            return False
        if shift is not None:
            self.set_shift(bool(shift), now=now)
        cur = (int(pt[0]), int(pt[1]))
        self.current = cur
        if self.shift:
            self.last_shift_move_pt = cur
        if self.pending_press and not self.dragging:
            cheb = max(abs(cur[0] - self.start[0]), abs(cur[1] - self.start[1]))
            if cheb >= DRAG_THRESHOLD_PX:
                self.dragging = True
                self.pending_press = False
                return True
            return False
        return True

    def on_up(self, pt: tuple[int, int], shift: bool | None = None, now: float | None = None) -> None:
        if not self.pending_press and not self.dragging:
            return
        cur = (int(pt[0]), int(pt[1]))
        self.current = cur
        if shift is not None:
            self.set_shift(bool(shift), now=now)
        if self.pending_press and not self.dragging:
            cheb = max(abs(cur[0] - self.start[0]), abs(cur[1] - self.start[1]))
            self.pending_press = False
            if cheb < DRAG_THRESHOLD_PX:
                return
            self.dragging = True

        eff_lock = self._effective_drag_shift(cur, now=now)
        sel = _compute_selection_rect(self.start, cur, eff_lock)
        self.dragging = False
        self.pending_press = False
        if sel[2] >= MIN_COMMIT_PX and sel[3] >= MIN_COMMIT_PX:
            self.committed_sel = sel
            self.committed_df11_lock = eff_lock

    def set_shift(self, active: bool, now: float | None = None) -> bool:
        t_now = time.perf_counter() if now is None else float(now)
        prev = self.shift
        if active and not prev:
            self.shift = True
            self.shift_released_at = 0.0
            self.last_shift_move_pt = self.current
            return self.dragging
        if not active and prev:
            self.shift = False
            self.shift_released_at = t_now
            return self.dragging
        return False

    def on_key(self, keysym: str) -> bool:
        ks = str(keysym or "")
        if ks == "Escape":
            self.cancelled = True
            self.accepted = None
            self.closed = True
            return True
        if ks in ("Return", "KP_Enter"):
            if self.committed_sel is not None and not self.dragging and not self.pending_press:
                self.cancelled = False
                self.accepted = self.committed_sel
                self.closed = True
                return True
        return False

    def active_rect_and_lock(self, now: float | None = None) -> tuple[tuple[int, int, int, int], bool, str]:
        if self.dragging:
            eff_lock = self._effective_drag_shift(self.current, now=now)
            sel = _compute_selection_rect(self.start, self.current, eff_lock)
            return sel, eff_lock, "DRAGGING"
        if self.committed_sel is not None:
            return self.committed_sel, self.committed_df11_lock, "SELECTED"
        return (0, 0, 0, 0), bool(self.shift), "IDLE"


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
    primary_h = int(ctypes.windll.user32.GetSystemMetrics(SM_CYSCREEN)) if sys.platform == "win32" else vh
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
    cv = tk.Canvas(
        root,
        width=vw,
        height=vh,
        highlightthickness=0,
        bd=0,
        bg="#000000",
        cursor="crosshair",
        takefocus=1,
    )
    cv.pack(fill="both", expand=True)
    cv.create_image(0, 0, image=dim_tk, anchor="nw")

    ctrl = _ClipStateController()
    live_holder: dict[str, Any] = {"live_tk": None}

    def _ensure_focus() -> None:
        try:
            root.lift()
            root.attributes("-topmost", True)
            root.focus_force()
            cv.focus_set()
        except Exception:
            pass

    def _maybe_quit() -> None:
        if ctrl.closed:
            try:
                root.quit()
            except Exception:
                pass

    def _draw_hud_banner(ly0_sel: int | None, mode_str: str) -> None:
        if mode_str == "SELECTED":
            msg = "✓ Área seleccionada · Pulsa Intro para enviar a DF11 Studio  |  Arrastra de nuevo para cambiar  |  Esc = Cancelar"
            border_col = "#34d399"
            half_w = 395.0
        else:
            msg = "DF11 Studio · Arrastra con el ratón para enmarcar  |  Shift = Proporción 260×310  |  Intro = Aceptar  |  Esc = Cancelar"
            border_col = "#10b981"
            half_w = 405.0

        banner_cx = max(half_w + 12.0, min(float(vw) - half_w - 12.0, float(-vx) + primary_w * 0.5))
        top_y = max(18.0, float(-vy) + 18.0)
        if ly0_sel is not None and ly0_sel < float(-vy) + 76.0:
            bot_y = min(float(vh - 48), float(-vy) + max(240.0, float(primary_h) - 54.0))
            banner_top = bot_y
        else:
            banner_top = top_y

        cv.create_rectangle(
            banner_cx - half_w,
            banner_top,
            banner_cx + half_w,
            banner_top + 30,
            fill="#090d16",
            outline=border_col,
            width=1,
            tags="overlay",
        )
        cv.create_text(
            banner_cx,
            banner_top + 15,
            text=msg,
            fill="#f1f5f9",
            font=("Segoe UI", 9, "bold"),
            tags="overlay",
        )

    def _repaint() -> None:
        sel, shift_lock, mode_str = ctrl.active_rect_and_lock()
        sx, sy, sw, sh = sel
        cv.delete("overlay")

        if mode_str == "IDLE" or sw < 2 or sh < 2:
            _draw_hud_banner(None, "IDLE")
            return

        lx0, ly0 = sx - vx, sy - vy
        lx1, ly1 = lx0 + sw, ly0 + sh
        ix0, iy0 = max(0, lx0), max(0, ly0)
        ix1, iy1 = min(vw, lx1), min(vh, ly1)
        if ix1 > ix0 and iy1 > iy0:
            bright_crop = frozen.crop((ix0, iy0, ix1, iy1))
            live_holder["live_tk"] = ImageTk.PhotoImage(bright_crop)
            cv.create_image(ix0, iy0, image=live_holder["live_tk"], anchor="nw", tags="overlay")

        is_selected = mode_str == "SELECTED"
        outline_col = "#34d399" if is_selected else "#10b981"
        cv.create_rectangle(lx0, ly0, lx1, ly1, outline=outline_col, width=2, tags="overlay")

        if is_selected:
            arm = max(8, min(18, sw // 4, sh // 4))
            for cx_c, cy_c, dx_c, dy_c in (
                (lx0, ly0, arm, arm),
                (lx1, ly0, -arm, arm),
                (lx0, ly1, arm, -arm),
                (lx1, ly1, -arm, -arm),
            ):
                cv.create_line(cx_c, cy_c, cx_c + dx_c, cy_c, fill="#34d399", width=4, tags="overlay")
                cv.create_line(cx_c, cy_c, cx_c, cy_c + dy_c, fill="#34d399", width=4, tags="overlay")

        if shift_lock and sh >= 40:
            crown_y = ly0 + round(sh * (21.0 / 310.0))
            eyes_y = ly0 + round(sh * (113.0 / 310.0))
            cv.create_line(lx0 + 4, crown_y, lx1 - 4, crown_y, fill="#38bdf8", dash=(4, 3), tags="overlay")
            cv.create_line(lx0 + 4, eyes_y, lx1 - 4, eyes_y, fill="#38bdf8", dash=(4, 3), tags="overlay")

        min_side = min(sw, sh)
        qual = "Óptimo" if min_side >= 200 else ("Media" if min_side >= 125 else "Baja res.")
        accent = "#34d399" if is_selected and min_side >= 125 else ("#10b981" if min_side >= 200 else ("#f59e0b" if min_side >= 125 else "#f43f5e"))
        suffix = " · Intro = Aceptar" if is_selected else ""
        prefix = "✓ " if is_selected else ""
        label = f"{prefix}{sw} × {sh} px · {qual}{' · DF11' if shift_lock else ''}{suffix}"
        bw = max(156, len(label) * 7 + 18)
        bx = max(6, min(vw - bw - 6, lx0))
        by = ly0 - 28 if ly0 >= 34 else min(vh - 30, ly1 + 6)
        cv.create_rectangle(bx, by, bx + bw, by + 22, fill="#090d16", outline=accent, width=1, tags="overlay")
        cv.create_text(bx + 8, by + 11, text=label, fill=accent, anchor="w", font=("Consolas", 9, "bold"), tags="overlay")

        _draw_hud_banner(ly0, mode_str)

    def _pt_from_event(ev: Any) -> tuple[int, int]:
        xr = getattr(ev, "x_root", None)
        yr = getattr(ev, "y_root", None)
        if xr is not None and yr is not None:
            return (int(xr), int(yr))
        px, py = root.winfo_pointerxy()
        return (int(px), int(py))

    def _shift_from_event(ev: Any) -> bool | None:
        raw_state = getattr(ev, "state", None)
        if isinstance(raw_state, int):
            return bool(raw_state & TK_SHIFT_MASK)
        return None

    def _on_down(ev: Any) -> None:
        _ensure_focus()
        ctrl.on_down(_pt_from_event(ev), shift=_shift_from_event(ev))

    def _on_move(ev: Any) -> None:
        if ctrl.on_move(_pt_from_event(ev), shift=_shift_from_event(ev)):
            _repaint()

    def _on_up(ev: Any) -> None:
        _ensure_focus()
        ctrl.on_up(_pt_from_event(ev), shift=_shift_from_event(ev))
        _repaint()

    def _on_shift_press(_ev: Any) -> None:
        if ctrl.set_shift(True):
            _repaint()

    def _on_shift_release(_ev: Any) -> None:
        if ctrl.set_shift(False):
            _repaint()

    def _on_keypress(ev: Any) -> None:
        ks = str(getattr(ev, "keysym", "") or "")
        if ks in ("Shift_L", "Shift_R"):
            _on_shift_press(ev)
            return
        if ctrl.on_key(ks):
            _maybe_quit()

    root.bind_all("<KeyPress>", _on_keypress)
    root.bind_all("<KeyRelease-Shift_L>", _on_shift_release)
    root.bind_all("<KeyRelease-Shift_R>", _on_shift_release)
    cv.bind("<ButtonPress-1>", _on_down)
    cv.bind("<B1-Motion>", _on_move)
    cv.bind("<ButtonRelease-1>", _on_up)

    root.deiconify()
    root.update_idletasks()
    _ensure_focus()
    root.after(25, _ensure_focus)
    root.after(120, _ensure_focus)
    _repaint()

    root.mainloop()
    try:
        root.destroy()
    except Exception:
        pass

    rect = ctrl.accepted
    if ctrl.cancelled or not rect:
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
