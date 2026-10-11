"""Screenshots at default + minimum size, and a list of squashed widgets."""
from harness import *  # the invisible app window: app, root, pump, capture, squashed, at, drag, find...
EXPORT = SCR / "layout_export"; EXPORT.mkdir(exist_ok=True)


def pump(sec=0.6):
    end = time.time() + sec
    while time.time() < end:
        root.update(); time.sleep(0.02)


grab = capture


LEAF = (tk.Button, tk.Label, tk.Entry, tk.Checkbutton, tk.Radiobutton, tk.Scale,
        __import__("tkinter.ttk", fromlist=["x"]).Button, __import__("tkinter.ttk", fromlist=["x"]).Label,
        __import__("tkinter.ttk", fromlist=["x"]).Checkbutton, __import__("tkinter.ttk", fromlist=["x"]).Radiobutton,
        __import__("tkinter.ttk", fromlist=["x"]).Scale, __import__("tkinter.ttk", fromlist=["x"]).Combobox)


def squashed():
    """Visible controls given noticeably less room than they asked for, or
    pushed outside the window."""
    out = []
    W, H = root.winfo_width(), root.winfo_height()
    def walk(w):
        for c in w.winfo_children():
            if c.winfo_ismapped() and isinstance(c, LEAF):
                x = c.winfo_rootx() - root.winfo_rootx(); y = c.winfo_rooty() - root.winfo_rooty()
                short_w = c.winfo_reqwidth() - c.winfo_width()
                short_h = c.winfo_reqheight() - c.winfo_height()
                # a Scale (slider) is allowed to be narrower than requested if it's still >= 60 px
                slider_ok = isinstance(c, (tk.Scale,)) or c.winfo_class() == "TScale" and c.winfo_width() >= 60
                entry_ok = c.winfo_class() == "Entry" and c.winfo_width() >= 80  # designed to shrink
                if ((short_w > 2 and not slider_ok and not entry_ok) or short_h > 2 or x + c.winfo_width() > W + 1
                        or y + c.winfo_height() > H + 1):
                    label = ""
                    try: label = c.cget("text")
                    except tk.TclError: pass
                    out.append(f"{c.winfo_class()} '{label}' {c.winfo_width()}x{c.winfo_height()} (wants {c.winfo_reqwidth()}x{c.winfo_reqheight()}) at {x},{y}")
            walk(c)
    walk(root)
    return out


axe = sorted(IMAGES.glob("Gemini*"))[1]
app.load_image(axe); app.transparent_var.set(True); app._settings_changed(); app.item_name.set("Flesh Axe")
app.set_export_dir(EXPORT)  # a realistic path (scratch settings only)
report = []
found = []
# The default and minimum sizes, and a Steam Deck's: 1280x800 in Gaming Mode, 1140x720 in Desktop Mode
for size in ("1140x800", "900x720", "1280x800", "1140x720"):
    root.geometry(f"{size}+40+40")
    for view in ("sprite", "edit", "game", "original"):
        if view == "original": app.notebook.select(0)
        else: app.view_var.set(view); app._on_view()
        if view == "edit" and len(app.layers) < 3:
            app.add_layer(); app.add_layer()
        pump()
        grab(f"{size}_{view}.png")
        issues = squashed()
        found += issues
        report.append(f"{size} {view}: {'OK - nothing squashed' if not issues else ''}")
        report += [f"    - {i}" for i in issues]
# Zoomed-in Edit view (Zoom tool, 2 clicks at the centre) at the default size
root.geometry("1140x800+40+40"); app.view_var.set("edit"); app._on_view(); pump()
app.select_tool("zoom"); pump()
cw, ch = app._canvas_size(app.art_canvas)
class _Ev:
    def __init__(self, **k): self.__dict__.update(k)
app._on_drag_start(_Ev(x=cw // 2, y=ch // 3)); pump(0.2)
found += squashed()
grab("1140x800_zoomed.png"); report.append(f"zoomed shot at {app.zoom_label.cget('text')}; squashed: {squashed() or 'none'}")
root.destroy()
print("\n".join(report))
assert not found, f"{len(found)} squashed controls (listed above)"
print("ALL OK")
