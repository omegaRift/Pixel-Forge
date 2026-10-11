"""palette_store: the SQLite palette library and recolouring."""
import shutil, sqlite3, sys
from pathlib import Path
from PIL import Image, ImageDraw
from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
import palette_store as PS

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
db = SCR / "ps_test" / "palettes.db"; shutil.rmtree(db.parent, ignore_errors=True)
store = PS.PaletteStore(db)
assert store.all() == [], "empty library (the file is made on first use)"

# colours_of: visible colours, most used first
img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
d = ImageDraw.Draw(img); d.rectangle((0, 0, 9, 9), fill=(200, 40, 40, 255)); d.rectangle((10, 10, 15, 15), fill=(40, 40, 200, 255))
img.putpixel((12, 2), (10, 200, 10, 128))
cols = PS.colours_of(img)
assert cols == [(200, 40, 40, 255), (40, 40, 200, 255), (10, 200, 10, 128)], cols

# save / get / all; names are unique in any case; replace keeps the name and id
p = store.save("Flesh Axe", cols, "flesh_axe.png")
assert p.name == "Flesh Axe" and p.colours == tuple(cols) and p.source == "flesh_axe.png" and db.exists()
try:
    store.save("flesh axe", cols[:1]); raise AssertionError("duplicate name accepted")
except PS.NameTaken:
    pass
q = store.save("FLESH AXE", cols[:2], "other.png", replace=True)
assert q.id == p.id and q.name == "Flesh Axe" and len(q.colours) == 2 and q.source == "other.png"
r = store.save("  Ruby  ", [(230, 20, 60, 255)])
assert r.name == "Ruby" and [x.name for x in store.all()] == ["Ruby", "Flesh Axe"]
for bad in ("", "   "):
    try:
        store.save(bad, cols); raise AssertionError("empty name accepted")
    except ValueError:
        pass
try:
    store.save("Nothing", []); raise AssertionError("empty palette accepted")
except ValueError:
    pass
print("save / replace / unique names / newest first OK")

# rename / delete; a new store object (another project, after a restart) sees the same library
try:
    store.rename(r.id, "flesh AXE"); raise AssertionError("rename onto a taken name")
except PS.NameTaken:
    pass
assert store.rename(r.id, "Ruby Red").name == "Ruby Red"
again = PS.PaletteStore(db)
assert [x.name for x in again.all()] == ["Ruby Red", "Flesh Axe"] and again.get(p.id).colours == tuple(cols[:2])
again.delete(r.id)
assert [x.name for x in store.all()] == ["Flesh Axe"] and store.get(r.id) is None
with sqlite3.connect(db) as con:
    raw = con.execute("SELECT colours FROM palettes").fetchone()[0]
assert raw == '["#c82828ff", "#2828c8ff"]', raw
print("rename / delete OK; the data is plain SQLite (colours as #rrggbbaa JSON)")

# MAX_COLOURS
many = [(i % 256, i // 256, 0, 255) for i in range(600)]
assert len(store.save("Big", many).colours) == PS.MAX_COLOURS

# recolour: nearest colour, alpha kept, see-through untouched
pal = [(0, 0, 0, 255), (255, 255, 255, 255), (220, 30, 30, 255)]
src = Image.new("RGBA", (4, 1))
for x, c in enumerate([(30, 20, 25, 255), (240, 230, 235, 200), (180, 60, 50, 255), (90, 90, 90, 0)]):
    src.putpixel((x, 0), c)
out = PS.recolour(src, pal)
assert [out.getpixel((x, 0)) for x in range(4)] == [(0, 0, 0, 255), (255, 255, 255, 200), (220, 30, 30, 255), (90, 90, 90, 0)]
assert PS.nearest((10, 10, 200), [(0, 0, 255, 255), (0, 255, 0, 255)]) == (0, 0, 255)
print("recolour: nearest colour, own alpha kept, see-through pixels untouched")
print("ALL OK")
