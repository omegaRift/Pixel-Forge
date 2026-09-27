# Pixel Forge: UI redesign brief (v2, tightened)

Goal: replace the current 3-column layout (sidebar → Original → Pixel Art) with a
Photoshop-style workspace, fixing the problems in *Pixel Forge - UI Guide.docx*
section 9 (clipping at 900×720, fixed-height sidebar, squeezed reference image,
long status text). Reference mock-up: `image_4b657f.png` (if available).

## Target layout (900×720 minimum, 1140×800 default)

```
┌───────────────────────────────────────────────────────────────────────────┐
│ TOP BAR  [anvil] Pixel Forge │ Open │ Save Art │ Save Sprite │ Item name [____] │ Export: …\folder [Open][✕] │
├──┬───────────────────────────────────────────────────┬────────────────────┤
│T │  ┌ Original ┬ Pixel Art ┬ Minecraft ┐  [Match Original] │ PALETTE            │
│O │  │                                           │    │  paint colour ▣    │
│O │  │           active tab's canvas             │    │  swatches ■■■■■    │
│L │  │   (whole-number NEAREST zoom, centred)    │    ├────────────────────┤
│S │  │                                           │    │ ADJUSTMENTS  ▲▼    │
│  │  └───────────────────────────────────────────┘    │ (scrollable)       │
│44│  STATUS: one line, ellipsised; hover = details    │ Grid, Colours,     │
│px│                                                   │ Clean-up, Outline, │
│  │                                                   │ Subject, Scale/Move│
│  │                                                   ├────────────────────┤
│  │                                                   │ LAYERS (≤5 rows    │
│  │                                                   │ visible, scrolls)  │
│  │                                                   │ Blend · Opacity    │
│  │                                                   │ Merge ↓ · Merge vis│
└──┴───────────────────────────────────────────────────┴────────────────────┘
```

* **Top bar** (single row, ~38 px) replaces the big header: small anvil logo, file
  actions, Item name, export-folder row. Nothing in it may clip at 900 px: the
  export path shortens first, then Item name shrinks (min ~110 px).
* **Left tool strip** (44 px): square buttons, top to bottom: Move (M), Pen (B),
  Eraser (E), Fill (G), Picker (I), Zoom (Z). Undo/Redo below a separator.
  Single-character or small drawn icons, tooltip on hover with name + key.
* **Centre**: `ttk.Notebook` with tabs **Original / Pixel Art / Minecraft**,
  Match Original on the notebook's header row (right-aligned, never squeezed),
  one-line status bar under the notebook.
* **Right sidebar** (300 px): Palette (fixed) → Adjustments (scrollable, mouse
  wheel scrolls it only while hovered) → Layers (fixed height, own scroll).

## Behaviour rules (keep the app's behaviour identical unless listed)

1. **view_var still exists** with values `'sprite' | 'edit' | 'game'`:
   * Minecraft tab → `'game'`.
   * Pixel Art tab + **Move** tool → `'sprite'` (drag moves subject, wheel scales).
   * Pixel Art tab + Pen/Eraser/Fill/Picker → `'edit'` (painting; right-click erases).
   * Original tab → leave view_var unchanged. The Pixel Art tab keeps its mode.
   * Setting `view_var` + calling `_on_view()` (as tests do) must select the right
     tab/tool.
2. **Zoom tool** (Pixel Art tab only): click = next whole-number zoom level, right-
   click (or Alt+click) = previous, double-click = fit. Zoom is always an integer
   factor with NEAREST. When zoomed past the canvas, drag with the middle button
   (or Space+drag) pans. Default = fit (today's behaviour).
3. **Original tab**: the source image fitted (smooth scaling is fine) with the
   dashed crop box, full size (no longer squeezed by the layers panel).
4. **Minecraft tab** gets its **own canvas**; the palette stays visible (it's in the
   sidebar now), and the "tick Transparent BG" tip stays.
5. **Palette swatches** are always clickable. Clicking one picks the paint colour
   and switches to Pen (and to the Pixel Art tab if needed).
6. **Status**: one line (file · size → grid · colours · detection). Full text in a
   tooltip on hover. Temporary messages (saved, frozen Base, AI running) replace
   the line.
7. **Layers panel** is always visible; ≤5 rows shown, scroll for more (max 8).
8. All keyboard shortcuts keep working. Tool keys (M B E G I Z) are ignored while
   typing in a text field.

## Hard constraints

* tkinter + ttk (`clam`) + Pillow only. Windows 11, DPI-aware. Min size 900×720.
* Pixel art canvases: whole-number zoom + NEAREST only.
* Dark arcade theme tokens from the UI Guide section 6 (BG `#12121c`, PANEL
  `#1c1c2b`, BORDER `#2e2e45`, TEXT, MUTED, ACCENT `#ff3e7f`, ACCENT_HI, CYAN).
  One spacing scale: 4 / 8 / 12 / 16.
* **Keep every name in UI Guide section 11.** Widgets keep their attribute names
  even when they move (e.g. `toolbar` = the left tool strip, `layer_panel` = the
  sidebar layers section, `palette_canvas` = sidebar swatches, `name_row` = the
  Item name field's frame). New widgets: `notebook`, `game_canvas`, `adjust_scroll`.
  Private hooks tests also use: `_photos['art']`, `_art_origin`, `_art_k`,
  `_canvas_size()`, `_swatches`, `_match_job`, `_ai_job`, `history`,
  `display_art`, `small_art`.

## Phases (each ends with a working app, all tests passing, screenshots at
## 1140×800 and 900×720; wait for approval before the next)

1. **Shell**: top bar, left strip, centre, right sidebar frames. Existing widgets
   moved into roughly the right places. Old big header removed.
2. **Centre**: Notebook with the three tabs, `game_canvas`, one-line status bar,
   Match Original on the tab row, view_var ↔ tab/tool mapping.
3. **Right sidebar**: palette on top, scrollable Adjustments, layers panel with its
   own scroll and fixed props/actions rows.
4. **Tools & polish**: tool strip with icons + tooltips, Move/Zoom tools, spacing
   pass on the 4/8/12/16 scale, final check of UI Guide section 9 items.
