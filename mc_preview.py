"""
In-game preview: how a sprite reads as a Minecraft item icon.

Draws a creative-inventory-style mock-up - a tab row (the item as the
selected tab's icon), a slot grid with the item hovered and its tooltip,
and a hotbar - in Minecraft's GUI proportions: a slot is 18 GUI units, an
item icon 16. Everything is drawn from scratch with Pillow (no game files).

The mock-up is drawn at "texture density": one GUI unit = texture_size/16
pixels, so a 16x16 texture fills a slot pixel-for-pixel and a 32x32 one
shows at double density like a high-res resource pack. The caller then
enlarges it by a whole number with NEAREST, like the game's GUI scale.
With less room the grid can show fewer columns/rows (a cropped view), so
the icon can stay at a realistic size.
"""

from PIL import Image, ImageDraw, ImageFont

# Classic GUI colours
PANEL = (198, 198, 198)
PANEL_LIGHT = (255, 255, 255)
PANEL_DARK = (85, 85, 85)
OUTLINE = (0, 0, 0)
SLOT = (139, 139, 139)
SLOT_DARK = (55, 55, 55)
SLOT_LIGHT = (255, 255, 255)
TAB_IDLE = (160, 160, 160)
TITLE = (64, 64, 64)
TOOLTIP_BG = (16, 0, 16, 240)
TOOLTIP_TOP = (80, 0, 255)
TOOLTIP_BOTTOM = (40, 0, 127)

# Layout, in GUI units
TAB_W = 28
PANEL_Y = 28                  # tabs sit above the panel
GRID_X, GRID_Y = 9, 18        # first slot, inside the panel
SCROLL_W = 12                 # scrollbar, right of the grid
HOTBAR_GAP = 14
MARGIN = 2
FULL_COLS, FULL_ROWS = 9, 5   # the real creative inventory
MIN_COLS, MIN_ROWS = 5, 2


def layout_size(cols: int = FULL_COLS, rows: int = FULL_ROWS) -> tuple[int, int]:
    """Mock-up size in GUI units for a grid of cols x rows slots."""
    panel_w = GRID_X + cols * 18 + 4 + SCROLL_W + 5
    panel_h = GRID_Y + rows * 18 + 8
    hotbar_w = cols * 20 + 2
    width = max(panel_w, hotbar_w) + 2 * MARGIN
    height = PANEL_Y + panel_h + HOTBAR_GAP + 24 + 2 * MARGIN
    return width, height


def best_fit(avail_w: int, avail_h: int, texture: int = 16) -> tuple[int, int, int]:
    """Pick (gui_scale, cols, rows) for a screen area of avail_w x avail_h px.

    Prefers the biggest GUI scale (up to 4) that still shows at least a
    MIN_COLS x MIN_ROWS grid, then as much of the full 9x5 grid as fits.
    If even that doesn't fit, the smallest layout at scale 1."""
    k = max(1, texture // 16)  # pixels per GUI unit before scaling
    for scale in (4, 3, 2, 1):
        unit = k * scale
        for cols in range(FULL_COLS, MIN_COLS - 1, -1):
            if layout_size(cols, MIN_ROWS)[0] * unit > avail_w:
                continue
            for rows in range(FULL_ROWS, MIN_ROWS - 1, -1):
                if layout_size(cols, rows)[1] * unit <= avail_h:
                    return scale, cols, rows
    return 1, MIN_COLS, MIN_ROWS


def pretty_name(stem: str) -> str:
    """'flesh_axe' -> 'Flesh Axe'; long generated names are shortened."""
    words = stem.replace("-", " ").replace("_", " ").split()
    name = " ".join(w.capitalize() for w in words) or "Item"
    return name if len(name) <= 28 else name[:25] + "..."  # bitmap font: ASCII only


def render_inventory(sprite: Image.Image, name: str, tab_title: str = "Pixel Forge",
                     cols: int = FULL_COLS, rows: int = FULL_ROWS) -> Image.Image:
    """The mock-up, at texture density (see module docstring). `name` is
    the item's tooltip; `tab_title` heads the creative tab."""
    k = max(1, sprite.width // 16)  # pixels per GUI unit
    sprite = sprite.convert("RGBA").resize((16 * k, 16 * k), Image.Resampling.NEAREST)

    width, height = layout_size(cols, rows)
    panel_w = GRID_X + cols * 18 + 4 + SCROLL_W + 5
    panel_h = GRID_Y + rows * 18 + 8
    hotbar_y = PANEL_Y + panel_h + HOTBAR_GAP
    img = Image.new("RGBA", (width * k, height * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def rect(x0, y0, x1, y1, fill):
        """Filled rectangle in GUI units (x1/y1 exclusive)."""
        d.rectangle(((MARGIN + x0) * k, (MARGIN + y0) * k,
                     (MARGIN + x1) * k - 1, (MARGIN + y1) * k - 1), fill=fill)

    def bevel(x0, y0, x1, y1, fill, light, dark, outline=True):
        """The raised GUI look: black outline, light top-left, dark bottom-right."""
        if outline:
            rect(x0, y0, x1, y1, OUTLINE)
            x0, y0, x1, y1 = x0 + 1, y0 + 1, x1 - 1, y1 - 1
        rect(x0, y0, x1, y1, dark)
        rect(x0, y0, x1 - 1, y1 - 1, light)
        rect(x0 + 1, y0 + 1, x1 - 1, y1 - 1, fill)

    def text(x, y, s, fill):
        """Pixel text: drawn with the bitmap font at 1 px per unit, then
        enlarged by k with NEAREST so it stays crisp at any density."""
        w = text_width(s)
        layer = Image.new("RGBA", (w, 12), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((0, 0), s, font=_FONT, fill=fill)
        img.alpha_composite(layer.resize((w * k, 12 * k), Image.Resampling.NEAREST),
                            ((MARGIN + x) * k, (MARGIN + y) * k))

    def slot(x, y, item=None, hovered=False):
        """An 18x18 inset slot; the item sits in its inner 16x16."""
        rect(x, y, x + 18, y + 18, SLOT_LIGHT)
        rect(x, y, x + 17, y + 17, SLOT_DARK)
        rect(x + 1, y + 1, x + 17, y + 17, SLOT)
        if item is not None:
            img.alpha_composite(item, ((MARGIN + x + 1) * k, (MARGIN + y + 1) * k))
        if hovered:  # the white hover wash over the slot contents
            wash = Image.new("RGBA", (16 * k, 16 * k), (255, 255, 255, 80))
            img.alpha_composite(wash, ((MARGIN + x + 1) * k, (MARGIN + y + 1) * k))

    # Creative tabs: idle ones behind the panel, the selected one joined to it.
    tabs = max(1, (panel_w + 1) // (TAB_W + 1))
    for i in range(1, tabs):
        bevel(i * (TAB_W + 1), 2, i * (TAB_W + 1) + TAB_W, PANEL_Y + 3, TAB_IDLE, PANEL_LIGHT, PANEL_DARK)
    bevel(0, PANEL_Y, panel_w, PANEL_Y + panel_h, PANEL, PANEL_LIGHT, PANEL_DARK)
    bevel(0, 0, TAB_W, PANEL_Y + 2, PANEL, PANEL_LIGHT, PANEL_DARK)
    rect(1, PANEL_Y - 1, TAB_W - 1, PANEL_Y + 2, PANEL)  # open the seam into the panel
    img.alpha_composite(sprite, ((MARGIN + (TAB_W - 16) // 2) * k, (MARGIN + 7) * k))

    # Title, slot grid, scrollbar. The item sits in the first slot and again,
    # hovered, at the start of the second row, so its tooltip has room.
    text(8, PANEL_Y + 5, tab_title, TITLE)
    for row in range(rows):
        for col in range(cols):
            has_item = col == 0 and row in (0, 1)
            slot(GRID_X + col * 18, PANEL_Y + GRID_Y + row * 18, sprite if has_item else None,
                 hovered=(row, col) == (1, 0))
    sx = GRID_X + cols * 18 + 4
    rect(sx, PANEL_Y + GRID_Y, sx + SCROLL_W, PANEL_Y + GRID_Y + rows * 18, SLOT_DARK)
    bevel(sx, PANEL_Y + GRID_Y, sx + SCROLL_W, PANEL_Y + GRID_Y + 15, PANEL, PANEL_LIGHT, PANEL_DARK,
          outline=False)

    # Hotbar (one slot per grid column), item in the first one, selected.
    hotbar_w = cols * 20 + 2
    hx = max(0, (panel_w - hotbar_w) // 2)
    rect(hx, hotbar_y, hx + hotbar_w, hotbar_y + 22, (0, 0, 0, 170))
    for i in range(cols):
        bx = hx + 1 + i * 20
        rect(bx, hotbar_y + 1, bx + 20, hotbar_y + 21, (110, 110, 110, 200))
        rect(bx + 1, hotbar_y + 2, bx + 19, hotbar_y + 20, (40, 40, 40, 200))
        if i == 0:
            img.alpha_composite(sprite, ((MARGIN + bx + 2) * k, (MARGIN + hotbar_y + 3) * k))
    sel = (hx - 1, hotbar_y - 1, hx + 23, hotbar_y + 23)  # selection frame
    for inset, colour in ((0, (20, 20, 20)), (1, (235, 235, 235)), (2, (20, 20, 20))):
        x0, y0, x1, y1 = sel[0] + inset, sel[1] + inset, sel[2] - inset, sel[3] - inset
        for edge in ((x0, y0, x1, y0 + 1), (x0, y1 - 1, x1, y1), (x0, y0, x0 + 1, y1), (x1 - 1, y0, x1, y1)):
            rect(*edge, colour)

    # Tooltip for the hovered slot (up-right of the cursor, like the game):
    # dark body, purple gradient border. Kept inside the mock-up.
    tw, th = text_width(name) + 8, 15
    tx = min(GRID_X + 18 + 4, width - 2 * MARGIN - tw)
    ty = PANEL_Y + GRID_Y + 18 - 8
    rect(tx, ty, tx + tw, ty + th, TOOLTIP_BG)
    for i in range(th - 2):
        t = i / max(1, th - 3)
        c = tuple(int(a + (b - a) * t) for a, b in zip(TOOLTIP_TOP, TOOLTIP_BOTTOM))
        rect(tx + 1, ty + 1 + i, tx + 2, ty + 2 + i, c)
        rect(tx + tw - 2, ty + 1 + i, tx + tw - 1, ty + 2 + i, c)
    rect(tx + 1, ty + 1, tx + tw - 1, ty + 2, TOOLTIP_TOP)
    rect(tx + 1, ty + th - 2, tx + tw - 1, ty + th - 1, TOOLTIP_BOTTOM)
    text(tx + 4, ty + 2, name, (255, 255, 255))
    return img


# Pillow's classic bitmap font: pixel-crisp with no anti-aliasing, and its
# measured width is exactly what it draws.
_FONT = (ImageFont.load_default_imagefont() if hasattr(ImageFont, "load_default_imagefont")
         else ImageFont.load_default())


def text_width(s: str) -> int:
    """Width of `s` in GUI units (1 font pixel = 1 unit)."""
    left, _, right, _ = _FONT.getbbox(s)
    return right - left + 1
