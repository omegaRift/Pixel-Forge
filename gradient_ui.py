"""
Gradients in Pixel Forge's editor: the Gradient tool and the GRADIENT panel.

Two kinds, both drawn from settings (layers.Gradient) so they stay editable:

  Colours  a gradient layer: drag across the sprite with the Gradient tool to
           add one (or to fill an empty selected layer), drag again to
           re-aim it. "Only on the sprite" clips it to the pixels below.
  Blend    a gradient blend on any other layer: the layer keeps its pixels
           and blend mode but fades from fully shown to see-through along
           the gradient - it becomes a gradient blending overlay. Turn it on
           with the Gradient toggle next to Blend, or drag in Blend mode.

The panel sits at the top of the sidebar's Adjustments area while the tool
is picked or a gradient layer / blended layer is selected. Painting on a
gradient layer turns it into ordinary pixels (Undo brings it back); painting
on a blended layer keeps the blend.

A mixin for PixelForgeApp, like editor_ui: it uses the app's widgets and the
layer editor's state.
"""

from dataclasses import replace
from math import atan2, cos, hypot, pi, sin
import tkinter as tk
from tkinter import colorchooser, ttk

from editor_ui import hex_colour
from layers import FADE, MAX_LAYERS, MAX_STEPS, MIN_STEPS, Gradient, Layer, bake, composite, render_gradient
from ui_widgets import Tooltip

# Theme colours (kept in sync with pixel_forge's palette)
BG, PANEL, BORDER, MUTED, CYAN = "#12121c", "#1c1c2b", "#2e2e45", "#8a8aa3", "#3ef0ff"
CHECKER = ("#2a2a3d", "#34344a")  # transparent swatches (same greys as editor_ui.checkerboard)
DRAG_MIN = 4                       # px the mouse must move before a click counts as a drag
ROW_ORDER = ("head", "mode", "shape", "colours", "fade_colour", "fade_to", "steps", "options", "hint", "rule")
STEPS_TIPS = {
    "colour": "How many colours the gradient uses - a few give pixel-art bands",
    "blend": "How many steps the fade takes. 2 steps + Dither fades with no half-see-through\n"
             "pixels at all (good for Minecraft textures, which can't show those)",
}


def snap_45(start, end):
    """end, moved so that start -> end points in a multiple of 45 degrees."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = hypot(dx, dy)
    if not length:
        return end
    angle = round(atan2(dy, dx) / (pi / 4)) * (pi / 4)
    return start[0] + length * cos(angle), start[1] + length * sin(angle)


class GradientMixin:
    # ---- widgets -------------------------------------------------------------

    def _build_gradient_panel(self):
        """GRADIENT, at the top of the scrolling Adjustments area. Its rows
        depend on what it's editing (see _update_gradient_panel)."""
        # What a new gradient layer / a new blend starts with (the panel edits
        # these when nothing is selected to edit; editing updates them too).
        self._grad_template = Gradient(colours=(self.paint_colour, self.paint_colour[:3] + (0,)))
        self._grad_clip_template = True
        self._fade_template = FADE
        self._grad_drag = None       # {"x", "y", "start", "end", "begun", "kind"} while dragging
        self._grad_loading = False   # filling the widgets in: not an edit
        self._grad_redraw_due = False
        self._grad_sliders = {k: {"down": False, "saved": False} for k in ("steps", "fade_to")}
        self._grad_tool_on = False
        self._grad_layout = None     # the rows currently shown

        self.grad_mode = tk.StringVar(value="colour")  # what a drag on a normal layer does
        self.grad_shape = tk.StringVar(value="linear")
        self.grad_fade = tk.BooleanVar(value=True)
        self.grad_fade_to = tk.IntVar(value=0)
        self.grad_steps = tk.IntVar(value=self._grad_template.steps)
        self.grad_dither = tk.BooleanVar(value=False)
        self.grad_clip = tk.BooleanVar(value=True)

        p = self.gradient_panel = ttk.Frame(self.adjust_area.inner, style="Panel.TFrame")
        rows = self._grad_rows = {name: ttk.Frame(p, style="Panel.TFrame") for name in ROW_ORDER}

        self.grad_title = ttk.Label(rows["head"], text="GRADIENT", style="Head.TLabel")
        self.grad_title.pack(side="left")
        self.grad_target = ttk.Label(rows["head"], style="Muted.TLabel")  # the layer it edits
        self.grad_target.pack(side="right")

        ttk.Label(rows["mode"], text="Type", width=8).pack(side="left")
        for text, value, tip in (
                ("Colours", "colour", "Dragging adds a layer of gradient colours\n(an empty selected layer is filled instead)"),
                ("Blend", "blend", "Dragging makes the selected layer a gradient blending overlay:\n"
                                   "it fades from fully shown to see-through, into the layers below")):
            b = ttk.Radiobutton(rows["mode"], text=text, value=value, variable=self.grad_mode,
                                command=self._on_grad_mode)
            b.pack(side="left", padx=(0, 14))
            Tooltip(b, tip)

        ttk.Label(rows["shape"], text="Shape", width=8).pack(side="left")
        for text, value in (("Linear", "linear"), ("Radial", "radial")):
            ttk.Radiobutton(rows["shape"], text=text, value=value, variable=self.grad_shape,
                            command=lambda: self._grad_set(shape=self.grad_shape.get())).pack(side="left", padx=(0, 14))

        ttk.Label(rows["colours"], text="Colours", width=8).pack(side="left")
        self.grad_swatches = []
        for end, tip in ((0, "Start colour - click to choose\n(Gradient tool: click a palette colour)"),
                         (1, "End colour - click to choose\n(Gradient tool: right-click a palette colour)")):
            if end:
                ttk.Label(rows["colours"], text="→", style="Muted.TLabel").pack(side="left", padx=6)
            swatch = tk.Canvas(rows["colours"], width=18, height=18, bg=PANEL, highlightthickness=1,
                               highlightbackground=MUTED, cursor="hand2")
            swatch.pack(side="left")
            swatch.bind("<Button-1>", lambda e, end=end: self.pick_gradient_colour(end))
            Tooltip(swatch, tip)
            self.grad_swatches.append(swatch)
        swap = ttk.Button(rows["colours"], text="Swap", style="Small.TButton", width=0,
                          command=self.swap_gradient_colours)
        swap.pack(side="right")
        Tooltip(swap, "Swap the start and end colours (X)")

        fade = ttk.Checkbutton(rows["fade_colour"], text="Fade to transparent", variable=self.grad_fade,
                               command=self._on_grad_fade)
        fade.pack(anchor="w")
        Tooltip(fade, "The end fades out to see-through instead of a colour")

        self.grad_fade_to_scale, self.grad_fade_to_label = self._slider(rows["fade_to"], "Fade to", 0, 100,
                                                                        self.grad_fade_to, self._on_grad_fade_to)
        Tooltip(self.grad_fade_to_scale, "How much of the layer is left at the end: 0% = see-through")
        self.grad_steps_scale, self.grad_steps_label = self._slider(rows["steps"], "Steps", MIN_STEPS, MAX_STEPS,
                                                                    self.grad_steps, self._on_grad_steps)
        Tooltip(self.grad_steps_scale, lambda: STEPS_TIPS[self._gradient_kind()])
        for key, scale in (("steps", self.grad_steps_scale), ("fade_to", self.grad_fade_to_scale)):
            state = self._grad_sliders[key]
            scale.bind("<ButtonPress-1>", lambda e, s=state: s.update(down=True, saved=False), add="+")
            scale.bind("<ButtonRelease-1>", lambda e, s=state: s.update(down=False), add="+")

        self.grad_dither_check = ttk.Checkbutton(rows["options"], text="Dither", variable=self.grad_dither,
                                                 command=lambda: self._grad_set(dither=self.grad_dither.get()))
        Tooltip(self.grad_dither_check, "Mix neighbouring steps in a checker pattern (classic pixel-art shading)")
        self.grad_clip_check = ttk.Checkbutton(rows["options"], text="Only on the sprite", variable=self.grad_clip,
                                               command=self._on_grad_clip)
        Tooltip(self.grad_clip_check, "Show the gradient only where the layers below have pixels,\n"
                                      "not on the transparent background")
        self.grad_remove_btn = ttk.Button(rows["options"], text="Remove", style="Small.TButton", width=0,
                                          command=self.remove_gradient_blend)
        Tooltip(self.grad_remove_btn, "Remove the gradient blend: the layer shows fully again")
        self._grad_options = None    # which of those three are shown

        self.grad_hint = ttk.Label(rows["hint"], style="Muted.TLabel", justify="left", wraplength=250)
        self.grad_hint.pack(anchor="w")
        tk.Frame(rows["rule"], bg=BORDER, height=1).pack(fill="x")  # divider above SPRITE

    @staticmethod
    def _draw_grad_swatch(canvas, rgba):
        canvas.delete("all")
        if rgba[3]:
            canvas.configure(bg=hex_colour(rgba))
            return
        canvas.configure(bg=CHECKER[0])  # transparent: a little checkerboard
        for cy in range(3):
            for cx in range(3):
                if (cx + cy) % 2:
                    canvas.create_rectangle(1 + 6 * cx, 1 + 6 * cy, 7 + 6 * cx, 7 + 6 * cy, fill=CHECKER[1], outline="")

    # ---- what the panel and the tool work on ------------------------------------

    def _gradient_target(self):
        """("colour", layer) - the selected gradient layer
        ("colour", None)  - the gradient layer the next drag adds
        ("blend", layer)  - the selected layer's gradient blend (layer.fade is
                            None until the first drag or the toggle adds it)
        None              - nothing to show"""
        layer = self.layers[self.active_layer] if self.layers else None
        tool = self.tool_var.get() == "gradient"
        if layer is not None and layer.gradient is not None:
            return "colour", layer
        if tool:
            return ("blend", layer) if self.grad_mode.get() == "blend" and layer is not None else ("colour", None)
        if layer is not None and layer.fade is not None:
            return "blend", layer
        return None

    def _gradient_kind(self) -> str:
        target = self._gradient_target()
        return target[0] if target else "colour"

    def _target_settings(self, target) -> Gradient:
        kind, layer = target
        if kind == "colour":
            return layer.gradient if layer else self._grad_template
        return layer.fade if layer.fade is not None else self._fade_template

    def _update_gradient_panel(self):
        """Show or hide the panel, pick its rows, and fill them in from what it
        edits (see _gradient_target)."""
        panel = getattr(self, "gradient_panel", None)
        if panel is None:
            return
        target = self._gradient_target()
        if target and not panel.winfo_manager():
            first = self.adjust_area.inner.pack_slaves()
            panel.pack(fill="x", **({"before": first[0]} if first else {}))
            self.adjust_area.canvas.yview_moveto(0)  # it's at the top: make sure it's in view
        elif not target and panel.winfo_manager():
            panel.pack_forget()
        if not target:
            return
        kind, layer = target
        tool = self.tool_var.get() == "gradient"
        g = self._target_settings(target)

        rows = ["head", "shape"]
        if tool and not (layer is not None and layer.gradient is not None):
            rows.append("mode")  # a drag on this layer could do either
        rows += ["colours", "fade_colour"] if kind == "colour" else ["fade_to"]
        rows += ["steps", "options", "hint", "rule"]
        layout = [name for name in ROW_ORDER if name in rows]
        if layout != self._grad_layout:
            self._grad_layout = layout
            for frame in self._grad_rows.values():
                frame.pack_forget()
            for name in layout:
                pady = {"head": (0, 0), "rule": (12, 8)}.get(name, (8, 0))
                self._grad_rows[name].pack(fill="x", pady=pady)
        options = [self.grad_dither_check]
        if kind == "colour":
            options.append(self.grad_clip_check)
        elif layer.fade is not None:
            options.append(self.grad_remove_btn)
        if options != self._grad_options:
            self._grad_options = options
            for w in (self.grad_dither_check, self.grad_clip_check, self.grad_remove_btn):
                w.pack_forget()
            for w in options:
                w.pack(side="right" if w is self.grad_remove_btn else "left", padx=(0, 12))

        self._grad_loading = True
        try:
            self.grad_shape.set(g.shape)
            self.grad_steps.set(g.steps)
            self.grad_steps_scale.set(g.steps)
            self.grad_steps_label.configure(text=str(g.steps))
            self.grad_dither.set(g.dither)
            if kind == "colour":
                self.grad_fade.set(g.colours[1][3] == 0)
                self.grad_clip.set(layer.clip if layer else self._grad_clip_template)
            else:
                left = round(g.colours[1][3] / 2.55)
                self.grad_fade_to.set(left)
                self.grad_fade_to_scale.set(left)
                self.grad_fade_to_label.configure(text=f"{left}%")
        finally:
            self._grad_loading = False
        if kind == "colour":
            for swatch, rgba in zip(self.grad_swatches, g.colours):
                self._draw_grad_swatch(swatch, rgba)

        self.grad_title.configure(text="GRADIENT" if kind == "colour" else "GRADIENT BLEND")
        name = layer.name if layer else "new layer"
        self.grad_target.configure(text=name if len(name) <= 18 else name[:15] + "...")
        self.grad_hint.configure(text=self._gradient_hint(kind, layer, tool))

    def _gradient_hint(self, kind, layer, tool) -> str:
        if self.original is None:
            return "Open an image, then drag across the sprite with the Gradient tool."
        if kind == "colour":
            if layer is None:
                active = self.layers[self.active_layer] if self.layers else None
                if active is not None and self._is_empty(active):
                    return f"Drag across the sprite to fill '{active.name}' with a gradient. Shift: 45° steps."
                return "Drag across the sprite to add a gradient layer. Shift: 45° steps."
            if tool:
                return "Drag across the sprite to re-aim it. Shift: 45° steps."
            return "Re-aim it with the Gradient tool (Shift+G). Painting on it turns it into normal pixels."
        if layer.fade is None:
            return (f"Drag across the sprite: '{layer.name}' will show fully where you start "
                    "and fade into the layers below by where you let go.")
        if tool:
            return f"Drag across the sprite to re-aim how '{layer.name}' fades. Shift: 45° steps."
        return "Re-aim it with the Gradient tool (Shift+G). You can still paint on the layer: the blend stays."

    @staticmethod
    def _is_empty(layer: Layer) -> bool:
        """A layer with nothing on it (and not the generated Base)."""
        return not layer.generated and layer.gradient is None and layer.image.getchannel("A").getbbox() is None

    def _gradient_tool_changed(self):
        """The tool may have changed (editor_ui._on_tool calls this)."""
        on = self.tool_var.get() == "gradient"
        if on != self._grad_tool_on:
            self._grad_tool_on = on
            if on:
                self._set_status("Gradient: drag across the sprite. Colours adds a gradient layer; Blend fades the "
                                 "selected layer into the ones below. Settings: top of the right panel.")
            if self.small_art is not None and self._art_mode == "edit":
                self._draw_art()  # show / hide the direction guide
        self._update_gradient_panel()

    def _on_grad_mode(self):
        self._update_gradient_panel()
        if self.small_art is not None and self._art_mode == "edit":
            self._draw_art()  # the guide shows what a drag would re-aim

    def _notify(self, note: str):
        """A note about what just happened, kept through the next status update."""
        self._status_note = note
        self._set_status(note)

    # ---- changing the settings (each is one undo step) ----------------------

    def _grad_set(self, snapshot=True, **changes):
        """Change the settings of what the panel edits - and of what the next
        new gradient layer / blend starts with."""
        if self._grad_loading:
            return
        target = self._gradient_target()
        if target is None:
            return
        kind, layer = target
        if kind == "colour":
            self._grad_template = replace(self._grad_template, **changes)
            current = layer.gradient if layer else None
        else:
            self._fade_template = replace(self._fade_template, **changes)
            current = layer.fade
        if current is not None:
            new = replace(current, **changes)
            if new != current:
                if snapshot:
                    self._snapshot()
                if kind == "colour":
                    self._set_layer_gradient(layer, new)
                else:
                    layer.fade = new
                self._layers_changed()  # (this refreshes the panel too)
                return
        self._update_gradient_panel()

    def _set_layer_gradient(self, layer: Layer, g: Gradient):
        layer.gradient = g
        layer.image = render_gradient(g, self.small_art.width)

    def _slider_snapshot(self, key) -> bool:
        """One undo step per slider drag: only the drag's first change saves."""
        state = self._grad_sliders[key]
        first = not (state["down"] and state["saved"])
        if state["down"]:
            state["saved"] = True
        return first

    def _on_grad_fade(self):
        if self._grad_loading or self._gradient_kind() != "colour":
            return
        start, end = self._target_settings(self._gradient_target()).colours
        self._grad_set(colours=(start, end[:3] + (0 if self.grad_fade.get() else 255,)))

    def _on_grad_fade_to(self, value):
        left = round(float(value))
        target = self._gradient_target()
        if self._grad_loading or not target or target[0] != "blend":
            return
        if round(self._target_settings(target).colours[1][3] / 2.55) == left:
            return
        self.grad_fade_to.set(left)
        self.grad_fade_to_label.configure(text=f"{left}%")
        self._grad_set(snapshot=self._slider_snapshot("fade_to"),
                       colours=(FADE.colours[0], FADE.colours[1][:3] + (round(left * 2.55),)))

    def _on_grad_steps(self, value):
        n = round(float(value))
        target = self._gradient_target()
        if self._grad_loading or not target or n == self._target_settings(target).steps:
            return
        self.grad_steps.set(n)
        self.grad_steps_label.configure(text=str(n))
        self._grad_set(snapshot=self._slider_snapshot("steps"), steps=n)

    def _on_grad_clip(self):
        target = self._gradient_target()
        if self._grad_loading or not target or target[0] != "colour":
            return
        clip = self.grad_clip.get()
        self._grad_clip_template = clip
        layer = target[1]
        if layer is not None and layer.clip != clip:
            self._snapshot()
            layer.clip = clip
            self._layers_changed()

    def pick_gradient_colour(self, end: int):
        if self._gradient_kind() != "colour":
            return
        g = self._target_settings(self._gradient_target())
        rgb, _ = colorchooser.askcolor(color=hex_colour(g.colours[end]), parent=self.root,
                                       title="Gradient start colour" if end == 0 else "Gradient end colour")
        if rgb:
            self.set_gradient_colour(end, tuple(int(c) for c in rgb))

    def set_gradient_colour(self, end: int, rgb):
        """Set the colour gradient's start (0) or end (1) colour - opaque, so
        picking an end colour also ends a fade to transparent."""
        if self._gradient_kind() != "colour":
            return
        colours = list(self._target_settings(self._gradient_target()).colours)
        colours[end] = tuple(rgb[:3]) + (255,)
        self._grad_set(colours=tuple(colours))

    def swap_gradient_colours(self):
        if self._gradient_kind() != "colour":
            return
        start, end = self._target_settings(self._gradient_target()).colours
        self._grad_set(colours=(end, start))

    def _gradient_palette_pick(self, end: int, rgba):
        """A palette colour clicked (end 0) / right-clicked (end 1) with the
        Gradient tool: a colour gradient's start / end colour. (A blend has
        no colours: a click just sets the paint colour.)"""
        if self._gradient_kind() == "colour":
            self.set_gradient_colour(end, rgba)
        elif end == 0:
            self.set_paint_colour(rgba)

    # ---- gradient blends ----------------------------------------------------------

    def add_gradient_blend(self):
        """Turn the selected layer into a gradient blending overlay: it keeps
        its pixels and blend mode, and fades into the layers below along a
        gradient (top to bottom to start with - drag to re-aim it)."""
        layer = self.layers[self.active_layer] if self.layers else None
        if layer is None or layer.gradient is not None or layer.fade is not None:
            if self.layers:
                self._refresh_layer_panel()  # (puts the toggle back as it was)
            return
        self._snapshot()
        layer.fade = self._fade_template
        self.grad_mode.set("blend")
        self.select_tool("gradient")  # the panel shows the blend; a drag re-aims it
        self._notify(f"'{layer.name}' now fades into the layers below. Drag across the sprite to aim the fade.")
        self._layers_changed()

    def remove_gradient_blend(self):
        layer = self.layers[self.active_layer] if self.layers else None
        if layer is None or layer.fade is None:
            if self.layers:
                self._refresh_layer_panel()
            return
        self._snapshot()
        layer.fade = None
        self._layers_changed()

    def _on_blend_toggle(self):
        """The Gradient toggle next to Blend (layers panel)."""
        if self.grad_blend_var.get():
            self.add_gradient_blend()
        else:
            self.remove_gradient_blend()

    # ---- the Gradient tool ------------------------------------------------------

    def _art_point(self, x, y):
        """A canvas position as a position on the sprite: fractions, 0..1
        across it (outside the sprite is fine: the gradient continues)."""
        ox, oy, k = self._art_origin
        size = self.small_art.width * k
        return (x - ox) / size, (y - oy) / size

    def _gradient_press(self, event):
        self._grad_drag = {"x": event.x, "y": event.y, "start": self._art_point(event.x, event.y), "begun": False}

    def _gradient_drag(self, event):
        d = self._grad_drag
        if d is None:
            return
        if not d["begun"]:
            if abs(event.x - d["x"]) + abs(event.y - d["y"]) < DRAG_MIN:
                return  # so far just a click
            d["kind"] = self._begin_gradient()
            if d["kind"] is None:
                self._grad_drag = None
                return
            d["begun"] = True
        self._grad_track(d, event)
        if not self._grad_redraw_due:  # one redraw per frame, however fast the mouse moves
            self._grad_redraw_due = True
            self.root.after(15, self._gradient_redraw)

    def _grad_track(self, d, event):
        end = self._art_point(event.x, event.y)
        d["end"] = snap_45(d["start"], end) if getattr(event, "state", 0) & 0x1 else end  # Shift

    def _aim_gradient(self, d):
        layer = self.layers[self.active_layer]
        if d["kind"] == "blend":
            layer.fade = replace(layer.fade, start=d["start"], end=d["end"])
        else:
            self._set_layer_gradient(layer, replace(layer.gradient, start=d["start"], end=d["end"]))

    def _gradient_redraw(self):
        self._grad_redraw_due = False
        d = self._grad_drag
        if d and d["begun"] and "end" in d:
            self._aim_gradient(d)
            self._layers_changed(quick=True)

    def _gradient_release(self, event):
        d, self._grad_drag = self._grad_drag, None
        if d is None:
            return
        if not d["begun"]:
            self._set_status("Gradient: drag across the sprite, from where it starts to where it ends.")
            return
        if event is not None:
            self._grad_track(d, event)
        self._aim_gradient(d)
        self._layers_changed()

    def _begin_gradient(self):
        """A drag started. Returns what it aims - "colour" or "blend" - or
        None if it can't. One undo step, whatever it does."""
        kind, target = self._gradient_target()
        active = self.layers[self.active_layer]
        if kind == "blend" or target is not None:  # re-aim a gradient layer / blend (or add the blend)
            if not active.visible:
                self._set_status(f"'{active.name}' is hidden - show it (tick its box) first.")
                return None
            self._snapshot()
            if kind == "blend" and active.fade is None:
                active.fade = self._fade_template
                self._refresh_layer_panel()
            return kind
        g, size = self._grad_template, self.small_art.width
        if self._is_empty(active):  # an empty layer: it becomes the gradient layer
            self._snapshot()
            active.gradient, active.clip, active.image = g, self._grad_clip_template, render_gradient(g, size)
            active.fade = None  # (a gradient layer fades with its own colours)
            self._refresh_layer_panel()
            return "colour"
        if len(self.layers) >= MAX_LAYERS:
            self._set_status(f"Can't add a gradient layer: {MAX_LAYERS} layers is the most. "
                             "Merge or delete one first.")
            return None
        self._snapshot()
        used = {l.name for l in self.layers}
        n = next(k for k in range(1, 100) if f"Gradient {k}" not in used)
        self.layers.insert(self.active_layer + 1, Layer(f"Gradient {n}", render_gradient(g, size),
                                                        gradient=g, clip=self._grad_clip_template))
        self.active_layer += 1
        self._refresh_layer_panel()
        return "colour"

    def _draw_gradient_guide(self, c):
        """The direction of what a drag re-aims, over the sprite (Gradient tool)."""
        if self.tool_var.get() != "gradient":
            return
        target = self._gradient_target()
        if not target or target[1] is None:
            return
        kind, layer = target
        g = layer.gradient if kind == "colour" else layer.fade
        if g is None:
            return
        ox, oy, k = self._art_origin
        size = self.small_art.width * k
        x0, y0 = ox + g.start[0] * size, oy + g.start[1] * size
        x1, y1 = ox + g.end[0] * size, oy + g.end[1] * size
        if g.shape == "radial":
            r = hypot(x1 - x0, y1 - y0)
            c.create_oval(x0 - r, y0 - r, x0 + r, y0 + r, outline=CYAN, dash=(4, 4), tags="guide")
        c.create_line(x0, y0, x1, y1, fill=BG, width=3, tags="guide")  # dark edge: visible on any colour
        c.create_line(x0, y0, x1, y1, fill=CYAN, dash=(6, 3) if kind == "blend" else None, tags="guide")
        c.create_oval(x0 - 4, y0 - 4, x0 + 4, y0 + 4, fill=CYAN, outline=BG, tags="guide")               # start
        c.create_oval(x1 - 4, y1 - 4, x1 + 4, y1 + 4, fill=BG, outline=CYAN, width=2, tags="guide")      # end

    # ---- painting on a gradient layer --------------------------------------------

    def _flatten_gradient(self, i: int):
        """Painting on a gradient layer: it becomes ordinary pixels first -
        exactly what it shows now, clip included."""
        layer = self.layers[i]
        baked = bake(layer, composite(self.layers[:i], self.small_art.width))
        layer.image, layer.gradient, layer.clip, layer.fade = baked.image, None, False, None
        self._notify(f"'{layer.name}' is now a normal layer, so you can paint on it (Undo brings the gradient back).")
