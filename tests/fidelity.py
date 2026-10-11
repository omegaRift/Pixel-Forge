"""How close a sprite looks to its source picture: the measure Match Original
is checked against (test_match.py)."""

import math

from PIL import Image, ImageFilter


def to_lab(rgb):
    """sRGB (0-255) -> CIE Lab, where equal distances look about equally different."""
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(float(v)) for v in rgb[:3])
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116  # noqa: E731
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def d2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def fidelity_error(art, cut, grid):
    """Mean Lab distance between sprite and source, both viewed blurred at 4x."""
    S = 4
    src = cut.convert("RGBa").resize((grid * S,) * 2, Image.Resampling.BOX).convert("RGBA")
    spr = art.resize((grid * S,) * 2, Image.Resampling.NEAREST)
    bs = src.convert("RGB").filter(ImageFilter.GaussianBlur(S * 0.6)).load()
    ba = spr.convert("RGB").filter(ImageFilter.GaussianBlur(S * 0.6)).load()
    m = spr.getchannel("A").load()
    errs = [math.sqrt(d2(to_lab(bs[x, y]), to_lab(ba[x, y]))) for y in range(grid * S) for x in range(grid * S) if m[x, y]]
    return sum(errs) / len(errs)
