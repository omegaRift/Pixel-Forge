"""
Texture projection in Pixel Forge's editor: open a texture image and project
it onto the selected layer. It fills whatever is drawn on that layer (the
drawing gives the shape) and keeps filling as you draw more; the TEXTURE
panel sets its size (it tiles when smaller than the sprite), position, how
it mixes with the drawn colours, and its strength. The layer's own pixels
are never changed (layers.Projection is applied when layers are combined).

A mixin for PixelForgeApp, like editor_ui: it uses the app's widgets and the
layer editor's state.
"""

from dataclasses import replace
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from layers import BLEND_MODES, default_projection
from platform_support import MONO, bind_wheel, pt
from ui_widgets import Tooltip

# Theme colours (kept in sync with pixel_forge's palette)
BG, PANEL, BORDER, MUTED = "#12121c", "#1c1c2b", "#2e2e45", "#8a8aa3"
TEXTURE_TYPES = [("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"), ("All files", "*.*")]


def _short(name: str, n: int) -> str:
    return name if len(name) <= n else name[: n - 3] + "..."


class ProjectionMixin:
    # ---- widgets -------------------------------------------------------------

    def _build_projection_ui(self):
        """'Texture [Project...]' in the layers panel, and the TEXTURE panel
        at the top of the Adjustments area (shown while the selected layer
        has a projected texture)."""
        self._proj_loading = False
        self._proj_slider = {"size": {"down": False, "saved": False}, "strength": {"down": False, "saved": False}}

        # Layers panel: above Merge Down / Merge All / Regenerate.
        row = ttk.Frame(self.layer_panel, style="Panel.TFrame")
        row.pack(fill="x", pady=(8, 0), before=self._layer_buttons["merge"].master)
        ttk.Label(row, text="Texture", width=8).pack(side="left")
        self.project_btn = ttk.Button(row, text="Project...", style="Small.TButton", width=0,
                                      command=self.project_texture)
        self.project_btn.pack(side="left")
        Tooltip(self.project_btn, "Open a texture image and project it onto this layer:\n"
                                  "it fills whatever is drawn on it (and whatever you draw next)")
        self.proj_remove_small = ttk.Button(row, text="✕", style="Arrow.TButton", width=2,
                                            command=self.remove_projection)
        Tooltip(self.proj_remove_small, "Remove the projected texture")
        self.proj_layer_label = ttk.Label(row, style="Muted.TLabel")

        # TEXTURE panel (Adjustments area)
        p = self.projection_panel = ttk.Frame(self.adjust_area.inner, style="Panel.TFrame")
        head = ttk.Frame(p, style="Panel.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="TEXTURE", style="Head.TLabel").pack(side="left")
        self.proj_target = ttk.Label(head, style="Muted.TLabel")
        self.proj_target.pack(side="right")

        row = ttk.Frame(p, style="Panel.TFrame")
        row.pack(fill="x", pady=(8, 0))
        self.proj_thumb = tk.Label(row, bg=BG, bd=0)
        self.proj_thumb.pack(side="left", padx=(0, 8))
        change = ttk.Button(row, text="Change...", style="Small.TButton", width=0, command=self.change_projection)
        change.pack(side="right")
        Tooltip(change, "Project a different texture (keeps position, mix and strength)")
        self.proj_name = ttk.Label(row, style="Value.TLabel")
        self.proj_name.pack(side="left")

        self.proj_size_var = tk.IntVar(value=16)
        self.proj_size_scale, self.proj_size_label = self._slider(p, "Size", 1, 32, self.proj_size_var,
                                                                  self._on_proj_size)
        Tooltip(self.proj_size_scale, "How wide the texture is on the sprite, in pixels\n"
                                      "(smaller than the sprite: it repeats)")

        row = ttk.Frame(p, style="Panel.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Move").pack(side="left")
        reset = ttk.Button(row, text="Reset", style="Small.TButton", width=5,
                           command=lambda: self._proj_set(offset=(0.0, 0.0)))
        reset.pack(side="right")
        for text, dx, dy in (("→", 1, 0), ("↓", 0, 1), ("↑", 0, -1), ("←", -1, 0)):
            ttk.Button(row, text=text, style="Arrow.TButton", width=2,
                       command=lambda dx=dx, dy=dy: self.nudge_projection(dx, dy)).pack(side="right", padx=(0, 3))

        row = ttk.Frame(p, style="Panel.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Mix", width=8).pack(side="left")
        self.proj_mode_box = ttk.Combobox(row, values=list(BLEND_MODES), state="readonly", font=(MONO, pt(10)),
                                          width=max(len(m) for m in BLEND_MODES) + 1)
        self.proj_mode_box.pack(side="left", fill="x", expand=True)
        self.proj_mode_box.bind("<<ComboboxSelected>>", lambda e: self._proj_set(mode=self.proj_mode_box.get()))
        bind_wheel(self.proj_mode_box, lambda e: "break")
        Tooltip(self.proj_mode_box, "How the texture mixes with the drawn colours:\n"
                                    "Normal = the texture's own colours; Multiply / Overlay / Soft Light keep your shading")

        self.proj_strength_var = tk.IntVar(value=100)
        self.proj_strength_scale, self.proj_strength_label = self._slider(p, "Strength", 0, 100,
                                                                          self.proj_strength_var,
                                                                          self._on_proj_strength)
        for key, scale in (("size", self.proj_size_scale), ("strength", self.proj_strength_scale)):
            state = self._proj_slider[key]
            scale.bind("<ButtonPress-1>", lambda e, s=state: s.update(down=True, saved=False), add="+")
            scale.bind("<ButtonRelease-1>", lambda e, s=state: s.update(down=False), add="+")

        row = ttk.Frame(p, style="Panel.TFrame")
        row.pack(fill="x", pady=(8, 0))
        remove = ttk.Button(row, text="Remove", style="Small.TButton", width=0, command=self.remove_projection)
        remove.pack(side="right")
        Tooltip(remove, "Remove the projected texture (the drawing shows as it is)")
        self.proj_hint = ttk.Label(p, style="Muted.TLabel", justify="left", wraplength=250)
        self.proj_hint.pack(anchor="w", pady=(8, 0))
        tk.Frame(p, bg=BORDER, height=1).pack(fill="x", pady=(12, 8))

    # ---- showing it ------------------------------------------------------------

    def _projected_layer(self):
        if not self.layers:
            return None
        layer = self.layers[self.active_layer]
        return layer if layer.projection is not None else None

    def _update_projection_ui(self):
        """Layers-panel row + TEXTURE panel, for the selected layer."""
        if not hasattr(self, "projection_panel"):
            return
        layer = self.layers[self.active_layer] if self.layers else None
        self.project_btn.configure(state="normal" if layer is not None and layer.gradient is None else "disabled")
        proj = layer.projection if layer is not None else None
        for w in (self.proj_remove_small, self.proj_layer_label):
            w.pack_forget()
        if proj is not None:
            self.proj_remove_small.pack(side="right")
            self.proj_layer_label.configure(text=_short(proj.name, 14))
            self.proj_layer_label.pack(side="left", padx=(8, 0))

        panel = self.projection_panel
        if proj is None:
            if panel.winfo_manager():
                panel.pack_forget()
            return
        if not panel.winfo_manager():
            grad = getattr(self, "gradient_panel", None)
            if grad is not None and grad.winfo_manager():
                panel.pack(fill="x", after=grad)
            else:
                first = self.adjust_area.inner.pack_slaves()
                panel.pack(fill="x", **({"before": first[0]} if first else {}))
            self.adjust_area.canvas.yview_moveto(0)
        grid = layer.image.width
        size = max(1, round(proj.scale * grid))
        self._proj_loading = True
        try:
            self.proj_size_scale.configure(to=max(2 * grid, size))
            self.proj_size_var.set(size)
            self.proj_size_scale.set(size)
            self.proj_size_label.configure(text=f"{size} px")
            self.proj_strength_var.set(proj.strength)
            self.proj_strength_scale.set(proj.strength)
            self.proj_strength_label.configure(text=f"{proj.strength}%")
            self.proj_mode_box.set(proj.mode)
        finally:
            self._proj_loading = False
        thumb = proj.texture.copy()
        thumb.thumbnail((32, 32), Image.Resampling.NEAREST if max(thumb.size) <= 32 else Image.Resampling.BOX)
        k = max(1, 32 // max(thumb.size))
        thumb = thumb.resize((thumb.width * k, thumb.height * k), Image.Resampling.NEAREST)
        backing = Image.new("RGBA", thumb.size, (52, 52, 74, 255))
        backing.alpha_composite(thumb)
        self._proj_photo = ImageTk.PhotoImage(backing)
        self.proj_thumb.configure(image=self._proj_photo)
        self.proj_name.configure(text=_short(proj.name or "texture", 16))
        self.proj_target.configure(text=_short(layer.name, 18))
        empty = layer.image.getchannel("A").getbbox() is None
        self.proj_hint.configure(text=(
            f"Draw on '{layer.name}' - the texture shows wherever you draw." if empty else
            f"The texture fills what's drawn on '{layer.name}', and whatever you draw next. "
            "Mix: Multiply, Overlay or Soft Light keep your shading."))

    # ---- actions (each is one undo step) ---------------------------------------

    def _ask_texture(self):
        """A texture image chosen by the user, as (RGBA image, file name), or None."""
        path = filedialog.askopenfilename(title="Texture to project", filetypes=TEXTURE_TYPES, parent=self.root)
        if not path:
            return None
        try:
            img = Image.open(path)
            img.seek(0)  # an animation: its first frame
            img = img.convert("RGBA")
        except Exception as exc:
            messagebox.showerror("Pixel Forge", f"Couldn't open that texture:\n\n{exc}", parent=self.root)
            return None
        return img, Path(path).name

    def project_texture(self):
        """Open a texture and project it onto the selected layer."""
        layer = self.layers[self.active_layer] if self.layers else None
        if layer is None:
            self._set_status("Open an image first, then project a texture onto one of its layers.")
            return
        if layer.gradient is not None:
            self._set_status(f"'{layer.name}' is a gradient layer: select a drawn layer to project a texture onto.")
            return
        chosen = self._ask_texture()
        if chosen is None:
            return
        texture, name = chosen
        self._snapshot()
        old = layer.projection
        layer.projection = default_projection(texture, layer.image.width, name)
        if old is not None:  # changing the texture: keep where it is and how it mixes
            layer.projection = replace(layer.projection, offset=old.offset, mode=old.mode, strength=old.strength)
        empty = layer.image.getchannel("A").getbbox() is None
        note = (f"Texture '{name}' is on '{layer.name}': draw on it and the texture fills what you draw."
                if empty else f"Projected '{name}' onto '{layer.name}' (its settings are at the top of the right panel).")
        self._status_note = note
        self._set_status(note)
        self._layers_changed()

    change_projection = project_texture

    def remove_projection(self):
        layer = self._projected_layer()
        if layer is None:
            return
        self._snapshot()
        layer.projection = None
        self._layers_changed()

    def _proj_set(self, snapshot=True, **changes):
        layer = self._projected_layer()
        if layer is None or self._proj_loading:
            return
        new = replace(layer.projection, **changes)
        if all(getattr(new, k) == getattr(layer.projection, k) for k in changes):
            return
        if snapshot:
            self._snapshot()
        layer.projection = new
        self._layers_changed()

    def nudge_projection(self, dx: int, dy: int):
        """Move the texture by whole sprite pixels (right / down positive)."""
        layer = self._projected_layer()
        if layer is not None:
            grid = layer.image.width
            ox, oy = layer.projection.offset
            self._proj_set(offset=((round(ox * grid) + dx) / grid, (round(oy * grid) + dy) / grid))

    def _slider_first(self, key) -> bool:
        state = self._proj_slider[key]
        first = not (state["down"] and state["saved"])
        if state["down"]:
            state["saved"] = True
        return first

    def _on_proj_size(self, value):
        layer = self._projected_layer()
        size = round(float(value))
        if layer is None or self._proj_loading or size == round(layer.projection.scale * layer.image.width):
            return
        self.proj_size_label.configure(text=f"{size} px")
        self._proj_set(snapshot=self._slider_first("size"), scale=size / layer.image.width)

    def _on_proj_strength(self, value):
        layer = self._projected_layer()
        strength = round(float(value))
        if layer is None or self._proj_loading or strength == layer.projection.strength:
            return
        self.proj_strength_label.configure(text=f"{strength}%")
        self._proj_set(snapshot=self._slider_first("strength"), strength=strength)
