"""Stand-in for Grass Block: call the real Pixel Forge.exe the way it will
(hidden, scratch APPDATA) and check exit codes, result files and textures."""
import json, os, shutil, subprocess, time
from pathlib import Path
from PIL import Image

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
EXE = APP / "Pixel Forge.exe"
if not EXE.exists():  # (built by build-launcher.bat; not in the repository)
    print("SKIPPED: this suite needs the built launcher, Pixel Forge.exe (run build-launcher.bat)")
    raise SystemExit(0)
WORK = SCR / "integ ws"   # a space in the path, like real mod folders
shutil.rmtree(WORK, ignore_errors=True); WORK.mkdir()
ENV = dict(os.environ, PIXEL_FORGE_HIDDEN="1", APPDATA=str(SCR / "appdata_integ"))
fails = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def texture(name, size=16, colour=(40, 160, 90, 255)):
    p = WORK / name
    Image.new("RGBA", size if isinstance(size, tuple) else (size, size), colour).save(p)
    return p


def run(*args, action=None, timeout=60):
    result = WORK / "result.json"
    result.unlink(missing_ok=True)
    env = dict(ENV)
    if action:
        env["PIXEL_FORGE_TEST_ACTION"] = action
    t = time.time()
    code = subprocess.run([str(EXE), *args, "--result", str(result)], env=env, timeout=timeout).returncode
    data = json.loads(result.read_text(encoding="utf-8")) if result.exists() else None
    return code, data, time.time() - t


# describe
code, data, _ = run("--describe")
check(code == 0 and data and data["protocol"] == 1 and "edit" in data["modes"], f"describe -> {code} {data}")

# paint + save: the texture changes, exit 0
tex = texture("flesh axe.png")
code, data, secs = run("--edit", str(tex), "--name", "Flesh Axe", "--caller", "Grass Block", action="paint-save")
img = Image.open(tex).convert("RGBA")
check(code == 0 and data["status"] == "saved" and data["width"] == 16, f"paint-save -> {code} {data} ({secs:.1f}s)")
check(img.getpixel((0, 0)) == (255, 0, 255, 255) and img.getpixel((5, 5)) == (40, 160, 90, 255),
      "paint-save wrote the painted pixel, rest unchanged")

# save unchanged: pixels identical (transparency kept)
tex2 = texture("glass.png", 32, (120, 200, 255, 90))
before = Image.open(tex2).convert("RGBA").tobytes()
code, data, _ = run("--edit", str(tex2), action="save")
check(code == 0 and Image.open(tex2).convert("RGBA").tobytes() == before, f"save unchanged -> {code}, pixels identical")

# cancel: exit 10, file untouched byte for byte
raw = tex.read_bytes()
code, data, _ = run("--edit", str(tex), action="cancel")
check(code == 10 and data["status"] == "cancelled" and tex.read_bytes() == raw, f"cancel -> {code} {data}")

# errors: exit 1 with a message, nothing written
for label, args in (("non-square", ["--edit", str(texture("wide.png", (32, 16)))]),
                    ("too small", ["--edit", str(texture("tiny.png", 4))]),
                    ("missing file", ["--edit", str(WORK / "nope.png")]),
                    ("not a PNG", ["--edit", str((WORK / "fake.png").write_text("hi") and WORK / "fake.png")]),
                    ("bad option", ["--edit", str(tex), "--bogus"])):
    code, data, _ = run(*args, timeout=30)
    check(code == 1 and data and data["status"] == "error" and data.get("message"), f"{label} -> {code} {data and data.get('message')}")
check(tex.read_bytes() == raw, "error runs left the texture alone")

print("\nALL PASS" if not fails else f"\n{len(fails)} FAILED")
