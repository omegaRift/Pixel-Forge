"""
Small reusable Tk widgets for Pixel Forge's UI (no app logic):

  Tooltip     - a hover tip, fixed text or computed when shown
  ScrollArea  - a vertically scrolling frame; its scrollbar appears only
                when the content is taller than the space available
"""

import tkinter as tk
from tkinter import ttk

# Theme (kept in sync with pixel_forge's palette)
BG, PANEL, BORDER, TEXT = "#12121c", "#1c1c2b", "#2e2e45", "#e8e8f0"
FONT = ("Consolas", 10)


class Tooltip:
    """A small hover tip. `text` is a string or a function returning one
    (an empty string means: nothing to show right now)."""

    def __init__(self, widget, text, delay=450):
        self.widget, self.text, self.delay = widget, text, delay
        self._after = self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._hide()
        self._after = self.widget.after(self.delay, self._show)

    def _show(self):
        text = self.text() if callable(self.text) else self.text
        if not text:
            return
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        tk.Label(self._tip, text=text, justify="left", bg=BORDER, fg=TEXT, font=FONT,
                 padx=8, pady=5, wraplength=520).pack()
        self._tip.update_idletasks()
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        if y + self._tip.winfo_reqheight() > self.widget.winfo_screenheight():  # no room below: go above
            y = self.widget.winfo_rooty() - self._tip.winfo_reqheight() - 6
        x = min(x, self.widget.winfo_screenwidth() - self._tip.winfo_reqwidth() - 4)
        self._tip.wm_geometry(f"+{x}+{y}")

    def _hide(self, _event=None):
        if self._after:
            self.widget.after_cancel(self._after)
            self._after = None
        if self._tip:
            self._tip.destroy()
            self._tip = None


class ScrollArea(ttk.Frame):
    """A frame whose content (put it in `.inner`) scrolls vertically.

    The canvas asks for only `height` px, so in a pack layout it takes what
    the other widgets leave and scrolls the rest; the scrollbar is shown
    only while the content doesn't fit. Wheel scrolling is done by the app
    (see PixelForgeApp._on_global_wheel) via contains() + scroll().
    """

    def __init__(self, parent, bg=PANEL, style="Panel.TFrame", height=100, step=20):
        super().__init__(parent, style=style)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, height=height, yscrollincrement=step)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                 style="Dark.Vertical.TScrollbar")
        self.inner = ttk.Frame(self.canvas, style=style)
        self._window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self._bar_shown = False
        self.inner.bind("<Configure>", self._update, add="+")
        self.canvas.bind("<Configure>", self._update, add="+")

    BAR_ROOM = 14  # px kept free at the right for the scrollbar while it's shown

    def _update(self, _event=None):
        # The scrollbar is *placed* over the right edge rather than packed:
        # packing it would change this widget's size, which can change
        # whether it's needed - an endless show/hide layout loop.
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        content = self.inner.winfo_reqheight()
        need = content > height + 1
        self.canvas.itemconfigure(self._window, width=max(1, width - (self.BAR_ROOM if need else 0)))
        self.canvas.configure(scrollregion=(0, 0, width, content))
        if need != self._bar_shown:
            self._bar_shown = need
            if need:
                self.bar.place(relx=1.0, rely=0, relheight=1.0, anchor="ne", width=self.BAR_ROOM - 4)
            else:
                self.bar.place_forget()
        if not need:
            self.canvas.yview_moveto(0)

    @property
    def scrollable(self) -> bool:
        return self._bar_shown

    def contains(self, widget) -> bool:
        while widget is not None:
            if widget is self:
                return True
            widget = getattr(widget, "master", None)
        return False

    def scroll(self, units: int):
        if self._bar_shown:
            self.canvas.yview_scroll(units, "units")

    def show(self, widget):
        """Scroll just enough to make a child of .inner fully visible."""
        if not self._bar_shown or not widget.winfo_exists():  # rows are rebuilt often
            return
        self.inner.update_idletasks()
        total = max(1, self.inner.winfo_reqheight())
        top, bottom = widget.winfo_y(), widget.winfo_y() + widget.winfo_height()
        view_top = self.canvas.canvasy(0)
        view_bottom = view_top + self.canvas.winfo_height()
        if top < view_top:
            self.canvas.yview_moveto(top / total)
        elif bottom > view_bottom:
            self.canvas.yview_moveto((bottom - self.canvas.winfo_height()) / total)
