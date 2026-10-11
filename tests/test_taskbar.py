import ctypes, os, sys, time, uuid
from ctypes import wintypes
from pathlib import Path
from PIL import Image

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
os.environ["APPDATA"] = str(SCR / "appdata_taskbar")
LAUNCHER = APP / "Pixel Forge.exe"
if not LAUNCHER.exists():  # (built by build-launcher.bat; not in the repository)
    print("SKIPPED: this suite needs the built launcher, Pixel Forge.exe (run build-launcher.bat)")
    raise SystemExit(0)
os.environ["PIXEL_FORGE_LAUNCHER"] = str(LAUNCHER)  # as if started by the launcher
from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
import pixel_forge as pf
import tkinter as tk

pf._windows_setup()
root = tk.Tk(); root.withdraw()
app = pf.PixelForgeApp(root)
root.geometry("900x720+40+40"); root.update_idletasks()
hwnd = int(root.wm_frame(), 16); u32 = ctypes.windll.user32
# hidden like the other tests (no TOOLWINDOW here: that would drop the taskbar identity)
u32.SetWindowLongW(hwnd, -20, u32.GetWindowLongW(hwnd, -20) | 0x80000 | 0x20 | 0x08000000)
u32.SetLayeredWindowAttributes(hwnd, 0, 0, 2); u32.ShowWindow(hwnd, 4)
for _ in range(10): root.update(); time.sleep(0.02)

assert pf.set_window_icons(hwnd), "exact icon frames loaded"
done = pf.set_taskbar_relaunch(hwnd)
print("set:", done)
assert done[2] == '"' + os.environ["PIXEL_FORGE_LAUNCHER"] + '"' and done[5] == "PixelForge.Desktop"

# Read the properties back from the window's property store
class GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]
def guid(t):
    u = uuid.UUID(t); g = GUID(u.fields[0], u.fields[1], u.fields[2]); g.d4[:] = u.bytes[8:]; return g
class PK(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]
class PV(ctypes.Structure):
    _fields_ = [("vt", wintypes.USHORT), ("r1", wintypes.WORD), ("r2", wintypes.WORD), ("r3", wintypes.WORD),
                ("value", ctypes.c_void_p), ("pad", ctypes.c_void_p)]
store = ctypes.c_void_p()
assert ctypes.windll.shell32.SHGetPropertyStoreForWindow(wintypes.HWND(hwnd), ctypes.byref(guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")), ctypes.byref(store)) == 0
vt = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
get_value = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(PK), ctypes.POINTER(PV))(vt[5])
fmt = guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3")
for pid, name in ((2, "RelaunchCommand"), (3, "RelaunchIconResource"), (4, "RelaunchDisplayName"), (5, "AppUserModel.ID")):
    v = PV(); get_value(store, ctypes.byref(PK(fmt, pid)), ctypes.byref(v))
    text = ctypes.wstring_at(v.value) if v.vt == 31 else None
    print(f"  read back {name}: {text}")
    assert text == done[pid]
    ctypes.windll.ole32.PropVariantClear(ctypes.byref(v))

# The window's own icon (what the taskbar button and Alt+Tab show)
WM_GETICON, ICON_BIG = 0x7F, 1
u32.SendMessageW.restype = ctypes.c_void_p; u32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
hicon = u32.SendMessageW(hwnd, WM_GETICON, ICON_BIG, None)
source = "WM_GETICON"
if not hicon:  # Tk may set the icon on the window class instead
    u32.GetClassLongPtrW.restype = ctypes.c_void_p
    hicon = u32.GetClassLongPtrW(wintypes.HWND(hwnd), -14)  # GCLP_HICON
    source = "window class"
print("icon handle from:", source, bool(hicon))
assert hicon, "window has an icon"
g32 = ctypes.windll.gdi32
dc = u32.GetDC(0); mdc = g32.CreateCompatibleDC(dc); bmp = g32.CreateCompatibleBitmap(dc, 32, 32); g32.SelectObject(mdc, bmp)
brush = g32.CreateSolidBrush(0x382828); rc = wintypes.RECT(0, 0, 32, 32); u32.FillRect(mdc, ctypes.byref(rc), brush)
u32.DrawIconEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]; u32.DrawIconEx(mdc, 0, 0, hicon, 32, 32, 0, None, 3)
class BMI(ctypes.Structure):
    _fields_ = [("a", wintypes.DWORD), ("w", wintypes.LONG), ("h", wintypes.LONG), ("p", wintypes.WORD), ("b", wintypes.WORD),
                ("c", wintypes.DWORD), ("s", wintypes.DWORD), ("x", wintypes.LONG), ("y", wintypes.LONG), ("u", wintypes.DWORD), ("i", wintypes.DWORD)]
buf = ctypes.create_string_buffer(32 * 32 * 4)
g32.GetDIBits(mdc, bmp, 0, 32, buf, ctypes.byref(BMI(ctypes.sizeof(BMI), 32, -32, 1, 32, 0, 0, 0, 0, 0, 0)), 0)
icon = Image.frombuffer("RGBA", (32, 32), buf, "raw", "BGRA", 0, 1).convert("RGB")
icon.resize((128, 128), Image.NEAREST).save(SCR / "window_icon.png")
# compare with the forge art composited on the same background
ref = Image.new("RGBA", (32, 32), (0x28, 0x28, 0x38, 255))
ico = Image.open(pf.FORGE_ICO); ico.size = (32, 32)
ref.alpha_composite(ico.convert("RGBA"))
diff = sum(abs(a - b) for a, b in zip(icon.tobytes(), ref.convert("RGB").tobytes())) / (32 * 32 * 3)
print(f"window icon vs forge.ico art: mean channel difference {diff:.2f}")
assert diff < 2
root.destroy()
print("ALL OK")
