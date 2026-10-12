"""
Updates in Pixel Forge's window (the installed Linux / Steam Deck app; see
updater.py for the work itself):

- at startup the app looks for a newer release, quietly. If there is one, a
  notification bar under the top bar says so. With "Update automatically"
  ticked (the default) it is downloaded and installed straight away, with a
  progress bar, and the notification then offers Restart Now; unticked, the
  notification offers Update Now instead;
- Check for Updates, at the right end of the status bar, does the same at
  any time and always answers in the notification bar.

Nothing here restarts the app by itself: an installed update is used from
the next start, or from Restart Now.

A mixin for PixelForgeApp. Its controls stay hidden until enable_updates(),
which main() calls only where the app can update itself.
"""

import threading
import tkinter as tk
from tkinter import messagebox, ttk

import updater
from ui_widgets import Tooltip

# Theme colours (kept in sync with pixel_forge's palette)
PANEL, TEXT, ACCENT, ACCENT_HI, CYAN = "#1c1c2b", "#e8e8f0", "#ff3e7f", "#ff6b9d", "#3ef0ff"
STARTUP_CHECK_MS = 1500   # after the window is up: the check must never slow starting


class UpdateMixin:
    def _build_update_ui(self):
        self._update_job = None         # a check or a download under way (on a thread)
        self._update_found = None       # the newer updater.Release, once one is known
        self._update_installed = None   # its version, once it is in place (a restart away)
        # (the tests put stand-ins here: no network, no real restart)
        self._update_fetch = updater.latest_release
        self._update_install = updater.install
        self._update_relaunch = updater.relaunch
        self.auto_update_var = tk.BooleanVar(value=bool(self.settings.get("auto_update", True)))

        s = ttk.Style(self.root)
        s.configure("Update.TButton", padding=(8, 3), background=ACCENT, foreground="#12121c",
                    bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT)
        s.map("Update.TButton", background=[("active", ACCENT_HI)])

        # Status bar, right end: [Check for Updates]
        self.update_btn = ttk.Button(self.status_bar, text="Check for Updates", style="Small.TButton",
                                     command=self.check_for_updates)
        Tooltip(self.update_btn, f"This is Pixel Forge {updater.VERSION}.\n"
                                 "Looks for a newer version and, if there is one, installs it.")

        # The notification bar (shown under the top bar when there is something to say)
        bar = self.update_bar = ttk.Frame(self.top_bar.master, style="Panel.TFrame", padding=(0, 4, 8, 4))
        tk.Frame(bar, bg=CYAN, width=3).pack(side="left", fill="y", padx=(0, 8))
        self.update_close = ttk.Button(bar, text="Later", style="Small.TButton", command=self.hide_update_bar)
        self.update_close.pack(side="right")
        self.update_action = ttk.Button(bar, style="Update.TButton")
        self.update_auto = ttk.Checkbutton(bar, text="Update automatically", variable=self.auto_update_var,
                                           command=self._on_auto_update)
        self.update_auto.pack(side="right", padx=(8, 12))
        Tooltip(self.update_auto, "Ticked: a newer version is downloaded and installed when Pixel Forge starts,\n"
                                  "and you're told when it's ready. Unticked: you're only told there is one.")
        self.update_text = ttk.Label(bar, anchor="w")
        self.update_text.pack(side="left", fill="x", expand=True)
        Tooltip(self.update_text, lambda: str(self.update_text.cget("text")))

    def enable_updates(self, check: bool = True):
        """This copy can update itself: show Check for Updates, say so if it
        was just updated, and look for a newer version once the window is up."""
        if not self.update_btn.winfo_manager():
            self.update_btn.pack(side="right", padx=(8, 0), before=self.status)
        before = updater.updated_from()
        if before and before != updater.VERSION:
            self._set_status(f"Pixel Forge was updated from {before} to {updater.VERSION}.")
        if check:
            self.root.after(STARTUP_CHECK_MS, lambda: self.check_for_updates(quiet=True))

    # ---- the notification bar ------------------------------------------------

    def _show_update_bar(self, text: str, action: str | None = None, command=None, close: str = "Close"):
        self.update_text.configure(text=text)
        self.update_close.configure(text=close, width=len(close) + 1)
        if action:
            self.update_action.configure(text=action, command=command, width=len(action) + 1)
            if not self.update_action.winfo_manager():
                self.update_action.pack(side="right", padx=(0, 4), after=self.update_close)
        else:
            self.update_action.pack_forget()
        if not self.update_bar.winfo_manager():
            self.update_bar.pack(fill="x", pady=(0, 8), after=self.top_bar)

    def hide_update_bar(self):
        self.update_bar.pack_forget()

    def _on_auto_update(self):
        self.settings["auto_update"] = bool(self.auto_update_var.get())
        self._save_update_settings()

    def _save_update_settings(self):
        self._save_settings()

    # ---- checking --------------------------------------------------------------

    def check_for_updates(self, quiet: bool = False):
        """Look for a newer version. quiet (the startup check): say nothing
        unless there is one. Otherwise the answer always shows, in the bar."""
        if self._update_installed:
            self._show_installed()
            return
        if self._update_job is not None:
            job = self._update_job
            if not quiet and job.get("quiet"):  # the startup check is still looking: have it answer aloud
                job["quiet"] = False
                job["wait"] = self.waits.begin("update_check", "Checking for updates...")
            return
        job = {"done": threading.Event(), "error": None, "result": None, "quiet": quiet,
               "failed": "Couldn't check for updates",
               # (nobody waits on the startup check: only a check that was asked for gets a bar)
               "wait": None if quiet else self.waits.begin("update_check", "Checking for updates...")}
        self._update_run(job, self._update_fetch, self._update_checked)

    def _update_checked(self, job):
        if job["error"]:
            if not job["quiet"]:
                self._show_update_bar(job["error"], "Try Again", self.check_for_updates)
            return
        release = job["result"]
        if not updater.is_newer(release.version):
            self._update_found = None
            if not job["quiet"]:
                self._show_update_bar(f"You have the newest version (Pixel Forge {updater.VERSION}).")
            return
        self._update_found = release
        # Installed once already and still not it? Don't download it at every start: just say so.
        again = self.settings.get("updated_to") == release.version
        if self.auto_update_var.get() and not again:
            self.install_update()
        else:
            self._show_update_bar(f"Pixel Forge {release.version} is available (you have {updater.VERSION}).",
                                  "Update Now", self.install_update, close="Later")

    # ---- installing ------------------------------------------------------------

    def install_update(self):
        release = self._update_found
        if release is None or self._update_job is not None:
            return
        size = f" ({release.megabytes} MB)" if release.size else ""
        self._show_update_bar(f"Pixel Forge {release.version} is available: downloading it{size}...", close="Hide")
        job = {"done": threading.Event(), "error": None, "result": None, "release": release,
               "failed": "The update couldn't be installed",
               "wait": self.waits.begin("update", f"Downloading Pixel Forge {release.version}...")}
        job["wait"].progress(0.0)
        self._update_run(job, lambda: self._update_install(release, progress=job["wait"].progress),
                         self._update_installed_now, learn=False)

    def _update_installed_now(self, job):
        release = job["release"]
        if job["error"]:
            self._show_update_bar(job["error"], "Try Again", self.install_update)
            return
        self._update_installed = release.version
        self.settings["updated_to"] = release.version
        self._save_update_settings()
        self._show_installed()

    def _show_installed(self):
        self._show_update_bar(f"Pixel Forge {self._update_installed} is installed. Restart to use it.",
                              "Restart Now", self.restart_app, close="Later")

    def restart_app(self, ask: bool = True):
        """Close this window and start the updated app. Asks first when there
        is work in the window: it isn't carried over."""
        if ask and self.small_art is not None and not messagebox.askyesno(
                "Pixel Forge", "Restart Pixel Forge now?\n\n"
                               "Anything you haven't saved in this window will be lost."):
            return
        try:
            self._update_relaunch()
        except updater.UpdateError as exc:
            self._show_update_bar(str(exc))
            return
        self.root.destroy()

    # ---- the thread ------------------------------------------------------------

    def _update_run(self, job, work, then, learn: bool = True):
        """Run work() off the Tk loop, then then(job) back on it."""
        self._update_job = job

        def run():
            try:
                job["result"] = work()
            except updater.UpdateError as exc:
                job["error"] = str(exc)
            except Exception as exc:  # anything else: still tell the user, in the window
                job["error"] = f"{job['failed']}: {exc}"
            job["done"].set()

        threading.Thread(target=run, daemon=True).start()
        self._update_poll(job, then, learn)

    def _update_poll(self, job, then, learn):
        if not job["done"].is_set():
            self.root.after(100, lambda: self._update_poll(job, then, learn))
            return
        self._update_job = None
        if job["wait"] is not None:
            job["wait"].end(record=learn and job["error"] is None)
        then(job)
