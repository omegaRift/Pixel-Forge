"""
Progress bars for anything the user waits on - the standard Pixel Forge
shares with Grass Block and MC GUI Designer:

- after SHOW_AFTER (400 ms), a bar along the bottom of the window says in
  words what it's waiting on ("Matching the original...");
- determinate when it can be measured: the work's own progress, or how long
  that kind of wait took before ("about 3 s left", then "5 s, longer than
  usual"); otherwise it moves without a measure and counts the seconds;
- it goes away when the wait ends, and quick waits never show it.

The work itself runs off the Tk loop (the caller's worker thread); a Wait
only tracks it. Typical times are remembered per kind (`times`, a dict the
app keeps in its settings).
"""

import math
import time
import tkinter as tk
from tkinter import ttk

SHOW_AFTER = 0.4   # seconds before a wait gets a bar (no flicker for quick ones)
TICK_MS = 100

BG, PANEL, BORDER, TEXT, MUTED, ACCENT = "#12121c", "#1c1c2b", "#2e2e45", "#e8e8f0", "#8a8aa3", "#ff3e7f"


class Wait:
    """One thing the user is waiting on. `progress()` may be called from the
    worker thread (it only sets a number); `end()` from the Tk thread."""

    def __init__(self, bar, kind, text, estimate):
        self.bar, self.kind, self.text, self.estimate = bar, kind, text, estimate
        self.started = time.monotonic()
        self.fraction = None
        self.ended = False

    def progress(self, fraction: float):
        self.fraction = max(0.0, min(1.0, fraction))

    def end(self, record: bool = True):
        """The wait is over. record=False: don't learn from it (it failed,
        or the caller records its own measure)."""
        if not self.ended:
            self.ended = True
            self.bar._ended(self, record)

    def describe(self, now=None):
        """(fraction or None for "no measure", words)."""
        elapsed = (now or time.monotonic()) - self.started
        if self.fraction is not None:
            f = self.fraction
            left = elapsed * (1 - f) / f if f > 0.05 else None
            return f, self.text + (f"  about {math.ceil(left)} s left" if left is not None else "")
        if self.estimate:
            if elapsed < self.estimate:
                return elapsed / self.estimate, f"{self.text}  about {math.ceil(self.estimate - elapsed)} s left"
            return None, f"{self.text}  {int(elapsed)} s, longer than usual"
        return None, f"{self.text}  {int(elapsed)} s"


class WaitBar:
    """Shows a window's waits along its bottom: in `host` (a frame), in place
    of the widgets in `covers` (put back afterwards)."""

    def __init__(self, root, host, covers=(), times=None, save=None):
        self.root, self.host, self.covers = root, host, list(covers)
        self.times = times if times is not None else {}   # kind -> typical seconds
        self.save = save or (lambda: None)                 # called after learning a time
        self.waits: list[Wait] = []
        self._ticking = False
        self._shown = None   # the Wait on show
        self._covered = []

        s = ttk.Style(root)
        s.configure("Wait.Horizontal.TProgressbar", troughcolor=BG, background=ACCENT, bordercolor=BORDER,
                    lightcolor=ACCENT, darkcolor=ACCENT, thickness=10)
        self.frame = ttk.Frame(host, style="Panel.TFrame")
        self.label = ttk.Label(self.frame, style="Muted.TLabel", anchor="w")
        self.label.pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(self.frame, style="Wait.Horizontal.TProgressbar", length=220,
                                        mode="determinate", maximum=1000)
        self.progress.pack(side="right", padx=(12, 0))

    # ---- waits ---------------------------------------------------------------

    def begin(self, kind: str, text: str, estimate: float | None = None) -> Wait:
        """Start tracking a wait. estimate: seconds it should take (default:
        what this kind took before, if known)."""
        wait = Wait(self, kind, text, estimate if estimate is not None else self.times.get(kind))
        self.waits.append(wait)
        if not self._ticking:
            self._ticking = True
            self.root.after(TICK_MS, self._tick)
        return wait

    def _ended(self, wait: Wait, record: bool):
        if wait in self.waits:
            self.waits.remove(wait)
        if record:
            self.learn(wait.kind, time.monotonic() - wait.started)
        self._refresh()

    def learn(self, kind: str, seconds: float):
        """Remember how long a kind of wait took (a running average)."""
        old = self.times.get(kind)
        self.times[kind] = round(seconds if old is None else 0.5 * old + 0.5 * seconds, 3)
        self.save()

    @property
    def showing(self) -> bool:
        return self._shown is not None

    # ---- showing ---------------------------------------------------------------

    def _tick(self):
        self._refresh()
        if self.waits:
            self.root.after(TICK_MS, self._tick)
        else:
            self._ticking = False

    def _refresh(self):
        now = time.monotonic()
        due = [w for w in self.waits if now - w.started >= SHOW_AFTER]
        if not due:
            self._hide()
            return
        wait = due[-1]  # the latest one is what the user just did
        fraction, words = wait.describe(now)
        if self._shown is None:
            self._covered = [(w, w.pack_info()) for w in self.covers if w.winfo_manager() == "pack"]
            for w, _ in self._covered:
                w.pack_forget()
            self.frame.pack(fill="x")
        self._shown = wait
        self.label.configure(text=words)
        if fraction is None:
            if str(self.progress.cget("mode")) != "indeterminate":
                self.progress.configure(mode="indeterminate")
                self.progress.start(15)
        else:
            if str(self.progress.cget("mode")) != "determinate":
                self.progress.stop()
                self.progress.configure(mode="determinate")
            self.progress.configure(value=round(fraction * 1000))

    def _hide(self):
        if self._shown is None:
            return
        self._shown = None
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self.label.configure(text="")
        self.frame.pack_forget()
        for w, info in self._covered:
            w.pack(**info)
        self._covered = []
